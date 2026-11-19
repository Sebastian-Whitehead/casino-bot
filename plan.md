# Plan: chips everywhere + one shared game structure

Branch: `supabase-migration`. Goal: every game bets **chips**, players buy chips with bank money at a configurable rate, and all games share one betting embed and interaction flow. Fixes the open bugs found in `Todo.txt` and `Winter test log.txt` on the way. The Supabase bank is a later phase (section 8); this plan only prepares the seam.

## 1. Decisions (change these first if you disagree)

| Topic | Decision |
|---|---|
| Chip rate | `chip_value` in `config.yml` (bank money per chip, default 10 = the old `token_price`). 1 old slots credit becomes 1 chip, so existing balances map 1:1. |
| Storage | No schema change. The existing `credits` column is the chip balance; code calls it chips. `money` stays the bank balance. Supabase will own `money` later. |
| Chip flow | Chips are created only by `/cashier` or `/buy` (bank to chips) and destroyed only by `/cashier` Cash Out or `/cashout`. Bets and wins move chips between player and casino. Casino chip balance may go negative; only the bank side needs to stay solvent. |
| Integers only | All chip amounts are `int`. Payout = `floor(bet * multiplier)` through one helper. Today `coinflip_multiplier: 1.5` produced `$2.5` / `$7.5` bets in the log. |
| Multiplier meaning | Total return including the stake (bet is deducted first, then `bet * mult` is paid on a win). Net profit is `bet * (mult - 1)`. Document this in `config.yml.example`. |
| In-game currency display | Chips only. Dollar values appear only in `/cashier`, `/buy`, `/cashout` and `/balance`. |
| Bonus (`!add`) | Stays as the interim source of bank money (see bug B9 for the cooldown fix). |

Decided: with floor rounding a 1-chip coinflip at 1.5x would return only the stake, so the coinflip minimum bet is raised to 2 chips (`coinflip_min_bet: 2` in config; `coinflip_multiplier` stays 1.5). `BaseBettingView.cap_bet` takes a per-game `min_bet` (default 1) instead of the hard-coded 1.

Decided: old cash values are deleted. Package A adds a one-time migration that backs up `economy.db`, sets every player's `money` to 0 and resets the casino's `money` to `CASINO_START_BALANCE`. Player `credits` carry over as chips. Until the Supabase bank exists, players get bank money only from the `!add` bonus (Package C keeps it, with the real cooldown) or the owner `!set` command.

## 2. What already exists to build on

- `modules/base_betting_view.py` `BaseBettingView`: the bet buttons (x10, +10, +1, /10, -10, -1, close), owner check, `bet_embed()`, `refresh_bet_message()`. Already shared by all four games. Currency is switched by `balance_index` / `currency_name`.
- `modules/base_game_cog.py` `BettingGameCog.prepare_bet_round()`: balance check, deduction, refresh, deletes the previous game message. Already used by all four games.
- `modules/challenge.py` `ChallengeGameCog` / `ChallengeView`: two-player stake flow for coinflip and dice.

What is still duplicated and gets pulled into the shared layer:
- The slash command preamble in every cog: channel restriction, "Game started", thread creation, starting bet, first embed. (coinflip.py, roller.py, slots.py, blackjack.py)
- Four near-identical "Play Again" result views and four result embeds with hand-built wallet text.
- Per-game logging `print`, payout math and message editing with no error handling.
- `end_game_by_thread` (blackjack, slots) and two different close buttons (base and roller).
- Currency hard-coded as `$` / `credits` in embeds, strings and `balance_index`.

## 3. Target design

### 3.1 Economy contract (Package A)
In `modules/economy.py`, keep `Entry = (user_id, money, chips)` and add strict operations. All of them validate `amount > 0`, never clamp, never go below zero for players, run in one transaction, and raise `InsufficientFundsException` (from `helpers.py`) on shortfall:

```
get_chips(uid) -> int
buy_chips(uid, n) -> bool  # bank.withdraw(uid, n*CHIP_VALUE); False (nothing changed) if it fails, else chips += n, casino gets the money
cash_out(uid, n)     # reverse of buy_chips
place_bet(uid, n)    # player chips -= n, casino chips += n
pay_out(uid, n)      # casino chips -= n, player chips += n
```
`add_money` / `add_credits` stay only for the `!set` owner command and tests, then get removed once nothing calls them. Everything else calls the five methods above, which is also the seam the Supabase adapter will implement.

### 3.2 Shared game framework (Package B)
New `modules/game_ui.py` plus edits to `base_betting_view.py` and `base_game_cog.py`:

- `format_chips(n)` returns "12 chips" / "1 chip". The only place the currency word lives.
- `BaseBettingView` becomes chips-only: remove `balance_index`, `currency_name`, `bet_title` switching. One `bet_embed()`: "Current bet: N chips / Wallet: M chips".
- `safe_edit(message, **kw)` / `safe_send(...)`: wraps Discord edits and sends, catches `ClientOSError`/`HTTPException`, retries once, logs. Fixes the SSL crash in the test log.
- `GameResultView(cog, betting_view, replay_kwargs)`: one Play Again and one Back to Bet view for every game.
- `build_result_embed(title, won, net, wallet, extra=None)`: one result embed layout.
- `BaseGameCog(BettingGameCog)` owns the full lifecycle:
  1. `open_game()`: channel restriction, ephemeral ack, thread, starting bet (`min(default_bet, chips)`), first embed. Replaces the preamble in every cog.
  2. `prepare_bet_round()`: unchanged behavior, now calls `economy.place_bet`.
  3. Game hook: `async def play(self, betting_view, interaction, **choice) -> Outcome`, where `Outcome(won, payout, title, description, file=None, view_cls=None)`. A game only implements `play` plus its own choice buttons.
  4. `settle(view, outcome)`: `economy.pay_out`, log line, result embed, `GameResultView`, refresh the bet embed. Blackjack calls `settle` from its Stand/dealer step instead of returning straight from `play`.
  5. `end_game_by_thread()` and `active_games` registration once, so cleanup works for every game (also fixes blackjack not registering).
- `payout(bet, mult)` helper in `helpers.py`: `floor(bet * mult)`. Embeds show the real number paid.
- Tests (see B-tests): instantiate every view class and assert all `custom_id`s are unique within one message. This catches the dice duplicate-ID crash from the log.

### 3.3 Challenges
`ChallengeGameCog` switches to `place_bet` / `pay_out`. Fee rounds down; the casino fee stays as chips credited to the casino. Challenges remain direct player-vs-player; they just use chips.

### 3.4 Cashier (Package C)
`modules/bank.py` is built by Package A, `cogs/cashier.py` by Package C.

**Bank seam (`modules/bank.py`).** A tiny interface the Supabase bank will implement later:
```
class Bank:
    def balance(uid) -> int
    def withdraw(uid, amount) -> bool   # False if amount <= 0 or insufficient funds; never partial, never negative
    def deposit(uid, amount) -> bool
```
The placeholder `LocalBank` is backed by the `money` column in `economy.db`, so the `!add` bonus keeps working. It is the single place to swap for Supabase. `Economy.buy_chips` calls `bank.withdraw` first and returns `False` without touching chips when it fails; if crediting the chips then fails, it calls `bank.deposit` to refund. `cash_out` calls `bank.deposit`.

**`/cashier` command (casino channel only, same restriction as games).** Opens a private (ephemeral) embed owned by the user who ran it, with two modes switched by a **Buy / Cash Out** toggle button (Buy selected by default):
- Embed: "Chip Cashier" with the mode, the chip quantity selected, the price ("30 chips = $300"), and the player's bank and chip balances.
- Quantity buttons reuse the bet-button layout and logic from `BaseBettingView` (x10, +10, +1, /10, -10, -1; minimum 1 chip) and a **Max** button. The cap depends on the mode: Buy is capped by `bank.balance // CHIP_VALUE`, Cash Out by the player's chips. Switching mode re-caps the quantity.
- **Check Out** (label changes to **Cash Out** in that mode) calls `economy.buy_chips(uid, qty)` or `economy.cash_out(uid, qty)`. On `False` / insufficient chips the embed edits to a clear message ("Insufficient funds: you need $X, you have $Y", or "You only have N chips") and nothing changes. On success it shows the new chip and bank balances and disables the buttons.
- **Cancel** closes the embed.
- One view class with unique `custom_id`s (covered by the view uniqueness test). It re-checks price and balances at confirmation, since config or balances may have changed since the embed opened. Cashing out chips that are currently at a table is not possible: only chips in the wallet count.

**Other cashier-cog commands**
- **Shortcut commands, no UI:** `/buy amount` and `/cashout amount` (amount is an integer number of chips; `/cashout` also accepts `all`). They call the same `economy.buy_chips` / `economy.cash_out` as the buttons, so the rules cannot diverge. Same casino-channel restriction. The reply is ephemeral and states the result and the new balances, or the same insufficient-funds / insufficient-chips message as the embed. Amounts below 1 are rejected before touching the economy.
- `/balance` shows bank money and chips (replaces the one in `gambling_helpers.py`).
- The insufficient-chips message in games points to `/cashier` (and `/buy`).
- Retires `/buyc`, `/sellc` and the slots buy/sell instructions embed.

## 4. Bugs to fix (from `Todo.txt`, `Winter test log.txt`, code reading)

| ID | Bug | Source | Owner |
|---|---|---|---|
| B1 | `/buyc` with a negative amount mints money; success message is sent even when funds are missing | `slots.py` | C |
| B2 | `add_money` clamps the player at 0 but moves the full amount to/from the casino, so money is created or destroyed | `economy.py` | A |
| B3 | Float bets/payouts from `coinflip_multiplier: 1.5` stored in an INTEGER column | log: `Bet: $2.5`, `$7.5` | A |
| B4 | Embeds show a different payout than what is paid (dice shows 6x, pays 5x; coinflip shows 2x, pays 1.5x) | `roller.py`, `coinflip.py` | B + games |
| B5 | `ssl.SSLError` / `ClientOSError` on `bet_message.edit` kills the interaction | log, coinflip Tails | B |
| B6 | Dice `Component custom id cannot be duplicated` (reported fixed, no regression test) | log, `roller.py` | B tests |
| B7 | Slots `GameView.play_again` sets `self.auto_spin = False` on the wrong object, so Auto never stops; auto loop reuses a stale interaction | `slots.py` | E |
| B8 | Thread cleanup finds threads but never deletes them (cache-only `channel.threads`, hard-coded channel, no permission check, old threads not fetched) | Todo.txt, log (`threads: 5`) | D |
| B9 | `!add` bonus has a 1-second cooldown, not the configured `bonus_cooldown` hours, so it is infinite money | `gambling_helpers.py` | C |
| B10 | `wallet` CommandNotFound makes `on_command_error` itself crash (`'NoneType' object is not callable`) | log tail, `handlers.py` | D |
| B11 | Blackjack never registers in `active_games`, so inactivity cleanup skips it | `blackjack.py` | B + F |
| B12 | Dead/legacy files and out-of-date docs: root `modules/`, `discord/cogs/legacy_gambling.py`, README says discord.py | repo | G |

## 5. Work packages (for parallel workers)

Give each worker its own git worktree (`isolation: worktree`) and have it touch **only the files it owns**. Shared contracts are the signatures in section 3; Package A and B land first (A also owns `modules/bank.py`, the `Bank` seam that `buy_chips` / `cash_out` call), so everyone codes against real functions rather than guesses.

### Wave 1 (sequential foundation, one worker each, can start together)

**A: Chip config, economy and bank seam** (owns new `modules/bank.py` (see 3.4), `config.yml.example`, `modules/helpers.py` (constants only), `modules/economy.py`, new `tests/test_economy.py`)
- Add `chip_value` and `coinflip_min_bet`, remove `token_price`, make `default_bet` / `slots_default_bet` chip counts, add `payout()` helper, document multiplier meaning.
- Implement the strict operations in 3.1 and make `get_chips` the chip accessor. No schema change; the only data change is the one-time cash wipe described in section 1 (back up first, run once, guarded by a marker row or `PRAGMA user_version`).
- Tests with `ECONOMY_DB_PATH=<tmp>` set before import (include `bank.withdraw` returning `False` on insufficient funds, zero and negative amounts): buy/cash-out round trip, insufficient funds, negative/zero rejected, casino money stays solvent, `place_bet` + `pay_out` conserve chips.
- Done when: tests pass, no float anywhere in `economy.py`, helpers import cleanly.

**B: Shared game framework** (owns `modules/base_betting_view.py`, `modules/base_game_cog.py`, new `modules/game_ui.py`, new `tests/test_views.py`)
- Everything in 3.2. Codes against A's method names; stub with the signatures until A merges.
- Done when: a tiny fake game cog can run open to bet to play to settle with mocks, and the custom_id uniqueness test passes for the base view.

### Wave 2 (parallel, after A and B merge)

**C: Cashier and wallet** (owns new `cogs/cashier.py`, `cogs/gambling_helpers.py`, `cogs/leaderboard.py`, `cogs/help_command.py`)
- Section 3.4 (`/cashier` embed, Cash Out mode, `/buy`, `/cashout`, `/balance`), B1, B9 (persist last bonus claim in a small table, honor `bonus_cooldown`; or drop `!add` if you want no free money). Leaderboard ranks by chips + money or money only, your call.
- Update `/help` for the new commands and chip wording.

**D: Cleanup and error handling** (owns `modules/auto_thread_cleanup.py`, `cogs/handlers.py`, `bot.py`)
- B8: fetch threads via `channel.threads` plus `guild.active_threads()`, delete by last-message age, log the reason when skipped (missing `Manage Threads`, not found), keep `/cleanup_threads` working.
- B10: `on_command_error` ignores `CommandNotFound` safely; optionally answer with a hint to use the slash commands.
- Remove duplicated hard-coded values left in `bot.py`.

**E: Slots** (owns `cogs/slots.py`)
- Port to `BaseGameCog.play`; reels and GIF stay as they are. Chips only, `SLOTS_MULTS` through `payout()`. Fix B7. Delete `/buyc`, `/sellc` and the instructions embed (C owns the replacement).

**F: Blackjack** (owns `cogs/blackjack.py`)
- Port to `BaseGameCog`, with `settle()` called from the Stand/dealer step. Register in `active_games` (B11). Win, blackjack, push and loss all go through `pay_out`.

**G: Coinflip, dice and challenges** (owns `cogs/coinflip.py`, `cogs/roller.py`, `modules/challenge.py`)
- Port to `BaseGameCog` / `ChallengeGameCog` with chips. Remove the roller's own close button and nested `GuessView` ID duplication (B6). Fix B4. Enforce `coinflip_min_bet` (opening bet and challenge bet).

### Wave 3 (after Wave 2)

**H: Tests, docs, cleanup** (owns `README.md`, `llm.txt`, `CLAUDE.md`, `Todo.txt`, `requirements.txt`, Docker files, `tests/`)
- Smoke test: import `bot` with the example config in the Docker image and assert all cogs load; run the view uniqueness test across all games.
- Delete root `modules/`, `discord/cogs/legacy_gambling.py`, empty `test_economy.py` files (B12); update README, `llm.txt`, `CLAUDE.md`, `Todo.txt`.
- Final manual checklist (below).

## 6. Dependency graph

```
A ----\
       >--> C, D (D has no dependency; can start immediately)
B ----/ \--> E, F, G --> H
```
D touches nothing the others touch, so it can run in Wave 1 as well. Merge order: A, B, then C/D/E/F/G in any order, then H. Because each worker owns distinct files, merge conflicts should be limited to `config.yml.example` and docs.

## 7. Manual acceptance checklist (run in the test guild)
1. `/cashier`: set 30 chips with the buttons, Check Out; bank money drops by `30 * chip_value`, chips +30. With too little money the embed shows insufficient funds and nothing changes. Another user cannot press the buttons.
2. Each of blackjack, slots, coinflip, dice: open, adjust the bet with every button, play, Play Again, Back to Bet, close. Wallet is shown in chips only and matches `/balance`.
3. Payout shown in the embed equals the change in chips, for a win on every game. No decimals anywhere.
4. Challenge: coinflip and dice with a friend; accept, decline, tie, fee shown.
5. Bet more chips than owned: error that mentions `/cashier`.
6. `/buy 5`, `/buy 0`, `/buy -3`, `/buy 99999`, `/cashout 5`, `/cashout all`: correct balances; invalid or too-large amounts are rejected with a message and change nothing.
7. `/cashier` Cash Out mode, Max: cash out all chips: bank money returns at the same rate; casino bank is consistent in `/casino_balance`.
8. Leave a thread idle past `thread_timeout_minutes`: the cleanup actually deletes it.
9. `!wallet` and other unknown commands no longer throw.
10. `docker compose up` still boots with the example config.

## 8. Later: Supabase bank (not in this plan)
Because Package A makes the economy a small set of strict operations, the Supabase step is "implement the same five methods against Supabase" (an RPC or a SQL function doing buy/cash-out atomically with a ledger row), keep chips in a casino-owned table, and read the bank balance from the shared economy. `economy_service_plan.md` already describes the service, ledger and idempotency requirements. Before starting it, inspect the Supabase economy schema (read-only) to decide whether the bot talks to Supabase directly or through the service.

## 9. Risks
- Behavior change for players: existing cash is wiped (decided). Players start with their old slots credits as chips and 0 cash, and need the `!add` bonus to buy more until the Supabase bank exists. The wipe is irreversible apart from the backup copy of `economy.db`.
- The casino chip balance can go negative; this is accepted because cash-outs are paid from casino money, so watch `/casino_balance`.
- Discord UI behavior (button limits, ephemeral messages, GIF uploads) cannot be unit tested; the manual checklist is the real gate.
- None of this is runnable without a test guild and token; automated tests only cover economy and view construction.

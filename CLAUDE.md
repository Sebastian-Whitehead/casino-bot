# Casino Bot

Python Discord gambling bot for a friends' casino: blackjack, slots, coinflip, dice (plus two-player coinflip/dice challenges). Uses **nextcord**. Players buy **chips** with bank money (`/cashier`, `/buy`, `/cashout`) and every game bets chips. Data lives in SQLite at `discord/economy.db` (path overridable with `ECONOMY_DB_PATH`).

Design/history: `plan.md` (chips + cashier plan), `economy_service_plan.md` (future Supabase/service extraction). Open work: `Todo.txt`.

## Run and test

- `.venv` in the repo root; run `python discord/bot.py` from the repo root, or `docker compose up -d --build`.
- Needs `config.yml` (copy `config.yml.example`). It holds the bot token and is gitignored: never print, log or commit it. `DISCORD_TOKEN` env var overrides the token.
- Tests: `ECONOMY_DB_PATH=<temp file> .venv/Scripts/python -m unittest discover -s tests`. Always point `ECONOMY_DB_PATH` at a temp file; never test against the real `discord/economy.db`. Tests use fakes; nothing exercises a live Discord.

## Layout (`discord/` is the app)

- `bot.py`: setup, owner slash commands, loads every `cogs/*.py`, binds the casino account to `client.user.id` in `on_ready`.
- `modules/helpers.py`: loads `../config.yml`, exposes constants (`CHIP_VALUE`, `COINFLIP_MIN_BET`, `payout(bet, mult)` = floor), `make_embed`. **It calls `os.chdir` into `discord/` on import**; use `__file__`-based paths.
- `modules/economy.py`: singleton `Economy`. The `economy` table is just `(user_id, chips)`, and the entry tuple is `(user_id, chips)`. Strict ops: `get_chips`, `buy_chips -> bool`, `cash_out`, `place_bet`, `pay_out`, plus the wager methods below. A one-time guarded migration (PRAGMA user_version 3) wiped the old table (backup: `<db>.pre-restructure.bak`).
- `modules/bank.py`: `Bank` seam (`balance/withdraw/deposit`). `LocalBank` is a placeholder with its own `bank_accounts(user_id, balance)` table; the casino account is the counterparty and starts with `CASINO_START_BANK`. The Supabase bank replaces it.
- **Wager lifecycle (every game, `BettingGameCog` in `base_game_cog.py`):** 1 `validate_wager` (enough chips, min bet) -> 2 `confirm_wager` (ephemeral Confirm/Cancel; `confirm_bets` config; Play Again and auto-spin skip it) -> 3 `Economy.open_wager(game_id, ...)` withdraws the stake under a new game id -> 4 the game decides win/lose (`play()` or its own flow) -> 5 `settle` -> `Economy.settle_wager` pays once per game id. Failures or abandoned games call `refund_wager`; `bot.py` refunds leftover open wagers on startup. Challenges share one game id across both players' wagers. `Economy.settle_game(game_id, {user_id: payout})` resolves a whole game in one transaction and writes the `game_log` table (one row per participant: chips wagered/paid out, result win/loss/push, winner = user id, `house` if everyone lost, `none` on a push); refunds are not logged. Never call `place_bet`/`pay_out` from a game; use the wager methods. Wagers live in the `wagers` table (status open/settled/refunded).
- `modules/game_ui.py`, `base_betting_view.py`, `base_game_cog.py`: shared betting embed/buttons, `safe_edit`/`safe_send`, `GameResultView`, and `BaseGameCog` (`open_game`, `play() -> Outcome`, `start_round`, `settle`, `end_game_by_thread`). `Outcome.payout` is total chips returned including the stake.
- `modules/challenge.py`: `ChallengeGameCog` (two-player stakes, fee, tie refund) for coinflip and dice.
- `cogs/`: `blackjack`, `slots`, `coinflip`, `roller` (dice), `cashier` (`/cashier`, `/buy`, `/cashout`, `/balance`), `gambling_helpers` (`!add` bonus, `!set`, `!leaderboard`), `leaderboard`, `help_command`, `handlers` (prefix error handler).
- `modules/auto_thread_cleanup.py`: deletes expired threads in `casino_channel_id`.

## Gotchas

- Every game's buttons need unique `custom_id`s within one message (Discord rejects duplicates); the tests check this.
- Not verified live yet: the Discord flows (`/cashier`, challenges, auto-spin, thread cleanup). Use the checklist at the end of `plan.md`.
- Keep secrets out of docs and commits. Prefer small edits.

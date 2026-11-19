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
- `modules/economy.py`: singleton `Economy`. Tuple `(user_id, money, chips)`; the `credits` column is the chip balance. Strict ops: `get_chips`, `buy_chips -> bool`, `cash_out`, `place_bet`, `pay_out`. The legacy `add_money`/`add_credits` clamp at 0; only owner commands use them. A one-time guarded migration (PRAGMA user_version) wipes cash and backs up the db first.
- `modules/bank.py`: `Bank` seam (`balance/withdraw/deposit`) with `LocalBank` on the `money` column. The Supabase bank replaces this.
- `modules/game_ui.py`, `base_betting_view.py`, `base_game_cog.py`: shared betting embed/buttons, `safe_edit`/`safe_send`, `GameResultView`, and `BaseGameCog` (`open_game`, `play() -> Outcome`, `start_round`, `settle`, `end_game_by_thread`). `Outcome.payout` is total chips returned including the stake.
- `modules/challenge.py`: `ChallengeGameCog` (two-player stakes, fee, tie refund) for coinflip and dice.
- `cogs/`: `blackjack`, `slots`, `coinflip`, `roller` (dice), `cashier` (`/cashier`, `/buy`, `/cashout`, `/balance`), `gambling_helpers` (`!add` bonus, `!set`, `!leaderboard`), `leaderboard`, `help_command`, `handlers` (prefix error handler).
- `modules/auto_thread_cleanup.py`: deletes expired threads in `casino_channel_id`.

## Gotchas

- Every game's buttons need unique `custom_id`s within one message (Discord rejects duplicates); the tests check this.
- Not verified live yet: the Discord flows (`/cashier`, challenges, auto-spin, thread cleanup). Use the checklist at the end of `plan.md`.
- Keep secrets out of docs and commits. Prefer small edits.

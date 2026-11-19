# Casino Bot

Python Discord gambling bot for a friends' casino: blackjack, slots, coinflip, dice (plus two-player coinflip/dice challenges). Uses **nextcord** (not discord.py, despite README and `requirements.txt` saying so). Money lives in SQLite at `discord/economy.db`.

Detailed repo map: `llm.txt`. Future economy-service extraction plan: `economy_service_plan.md`. Open work: `Todo.txt`.

## Run

- `.venv` in the repo root; run `python discord/bot.py` from the repo root.
- Needs `config.yml` (copy `config.yml.example`). It holds the bot token and is gitignored — never print, log or commit it. `*.db` is also gitignored.
- Only check available: `python -m compileall -q discord modules`. There are no real tests (`test_economy.py` files are empty or manual scripts).

## Layout

- `discord/` is the active tree. Root `modules/` and `discord/cogs/legacy_gambling.py` are dead (the latter is skipped by the cog loader in `bot.py`). `cogs/gambling_helpers.py` and `cogs/handlers.py` are older prefix-command code that still loads.
- `discord/bot.py`: bot setup, owner slash commands, loads every `cogs/*.py`, binds the casino account to `client.user.id` in `on_ready`.
- `modules/helpers.py`: loads `../config.yml`, exposes config constants, `make_embed`. **It calls `os.chdir` to `discord/` on import**, so relative paths resolve from there. Use `__file__`-based paths.
- `modules/economy.py`: singleton `Economy`. Row tuple is `(user_id, money, credits)` — keep it stable. `add_money` for a non-casino user mirrors the opposite amount onto the casino and clamps balances at 0 instead of rejecting.
- `modules/base_betting_view.py`: shared bet-adjust UI (`balance_index` 1=money, 2=credits).
- `modules/base_game_cog.py` (`BettingGameCog.prepare_bet_round`): shared wager validation and deduction. `modules/challenge.py` (`ChallengeGameCog`): two-player stakes, fee, tie refund. Coinflip and dice inherit these.

## Gotchas

- Payouts are separate from `prepare_bet_round`. Check the deduction/payout timing in every game cog before touching money flow.
- `/buyc` and `/sellc` don't validate funds or negative input.
- Thread cleanup (`modules/auto_thread_cleanup.py`) uses a hard-coded channel ID and only sees cached threads, which is the open "finds but doesn't delete" bug.
- Many UI controls use fixed `custom_id`s; duplicates break buttons.
- Prefer small edits. Keep secrets out of docs and commits.

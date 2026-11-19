# Economy Service Implementation Plan

Status: planning document. This file is intended to be handed to a future coding session in a separate project.

## Goal

Extract the casino economy from the Discord bot into a standalone service that can be used by:

- The Discord bot
- A future web dashboard
- Administrative tools
- Future bots or game clients

The service must become the sole authority for balances, transfers, wager reservations, settlements, refunds, casino fees, and transaction history.

## Current system to migrate

Current database location: `discord/economy.db`

Current SQLite schema:

```sql
CREATE TABLE economy (
    user_id INTEGER NOT NULL PRIMARY KEY,
    money INTEGER NOT NULL DEFAULT 0,
    credits INTEGER NOT NULL DEFAULT 0
);
```

Current row contract:

```text
(user_id, money, credits)
```

Current semantics:

- `money` is the cash balance.
- `credits` is the slots-credit balance.
- New users start at 0 money and 0 credits.
- The casino account starts at 100000 money when first created.
- The casino account is ultimately bound to the authenticated Discord bot user ID.
- `add_money(player, negative_amount)` decreases the player and increases the casino by the opposite amount.
- `add_money(player, positive_amount)` increases the player and decreases the casino by the same amount.
- Current balances are clamped at zero rather than rejecting invalid withdrawals. The service should improve this by rejecting insufficient funds for financial operations.
- Existing casino fees from challenge games should credit the casino account.

Important migration rule: do not silently lose the old configured casino row when moving it to the bot's authenticated Discord ID.

## Target architecture

```text
+-------------------+       HTTPS/internal HTTP       +-------------------+
| Discord bot       | --------------------------------> | Economy API       |
+-------------------+                                  +---------+---------+
                                                                  |
+-------------------+                                             v
| Web dashboard     | --------------------------------> +-------------------+
+-------------------+                                  | PostgreSQL        |
                                                                  |
+-------------------+                                             v
| Admin tools       | --------------------------------> +-------------------+
                                                        | Transaction ledger|
                                                        +-------------------+
```

Recommended deployment:

```text
Docker Compose
  economy-api
  postgres
```

The API should be the only application that connects directly to PostgreSQL. Clients call the API over the private Docker network or authenticated HTTPS.

## Recommended technology

- Python API: FastAPI.
- Database: PostgreSQL.
- ORM/query layer: SQLAlchemy 2.x with Alembic migrations, or another typed PostgreSQL-compatible layer.
- Validation: Pydantic models.
- Driver: psycopg.
- Tests: pytest, with a PostgreSQL test service/container for transaction tests.
- Deployment: Dockerfile plus `docker-compose.yml`.
- Authentication: service-to-service API key initially; replace with signed tokens or a proper identity provider if clients grow.

Do not expose PostgreSQL to the Discord bot or dashboard. Do not allow multiple applications to open the SQLite file over a shared volume.

## PostgreSQL schema

Use integer smallest units for money. The existing bot uses whole-dollar integer values, so the first migration can use integer `money` and `credits`. If fractional currency is required later, introduce `money_minor` as an integer rather than PostgreSQL floating point.

### `accounts`

```sql
CREATE TABLE accounts (
    id BIGSERIAL PRIMARY KEY,
    external_user_id BIGINT NOT NULL,
    account_type TEXT NOT NULL DEFAULT 'user',
    money BIGINT NOT NULL DEFAULT 0 CHECK (money >= 0),
    credits BIGINT NOT NULL DEFAULT 0 CHECK (credits >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (external_user_id)
);

CREATE INDEX accounts_money_desc_idx ON accounts (money DESC);
```

`external_user_id` is the Discord user ID. `account_type` should normally be `user`; the casino is still represented by the bot's Discord user ID so `/casino_balance` works against the same account identity.

Alternative future schema: use a separate `system_accounts` table for the casino account if the service later supports multiple casinos. Do not add that complexity during the first migration unless multi-tenant behavior is required.

### `transactions`

Immutable audit record for every balance change.

```sql
CREATE TABLE transactions (
    id UUID PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    transaction_type TEXT NOT NULL,
    reference_id TEXT,
    actor_id BIGINT,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`transaction_type` examples:

- `migration`
- `admin_adjustment`
- `bonus`
- `cash_wager`
- `cash_payout`
- `cash_refund`
- `credit_purchase`
- `credit_sale`
- `credit_wager`
- `credit_payout`
- `challenge_fee`

### `transaction_entries`

Double-entry-style account movements associated with a transaction.

```sql
CREATE TABLE transaction_entries (
    id BIGSERIAL PRIMARY KEY,
    transaction_id UUID NOT NULL REFERENCES transactions(id),
    account_id BIGINT NOT NULL REFERENCES accounts(id),
    money_delta BIGINT NOT NULL DEFAULT 0,
    credits_delta BIGINT NOT NULL DEFAULT 0,
    CHECK (money_delta <> 0 OR credits_delta <> 0)
);

CREATE INDEX transaction_entries_account_idx
    ON transaction_entries (account_id, id);
```

A player wager and casino receipt should be represented in the same transaction. A payout and casino debit should also be represented together. This makes the audit trail explain why balances changed.

### `game_settlements`

Idempotent game-level state.

```sql
CREATE TABLE game_settlements (
    game_id UUID PRIMARY KEY,
    game_type TEXT NOT NULL,
    status TEXT NOT NULL,
    wager_currency TEXT NOT NULL,
    created_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    settled_at TIMESTAMPTZ,
    result JSONB,
    transaction_id UUID REFERENCES transactions(id)
);
```

`status` values:

- `reserved`
- `settled`
- `refunded`
- `cancelled`

The API must return the existing settlement when the same `game_id` is submitted again. It must never pay twice because a client retried a request.

### `service_clients`

For API authentication if API keys are stored in the service database.

```sql
CREATE TABLE service_clients (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    key_hash TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ
);
```

Prefer storing only hashes of API keys. For a small initial deployment, Docker secrets/environment variables may be sufficient, but do not commit keys.

## API conventions

Base path: `/api/v1`

Responses should be JSON. Use UTC timestamps in ISO 8601 format. Return a correlation/request ID in response headers and logs.

Standard errors:

```json
{
  "error": {
    "code": "INSUFFICIENT_FUNDS",
    "message": "Account does not have enough money.",
    "request_id": "..."
  }
}
```

Suggested status codes:

- `200` successful read/update
- `201` resource created
- `400` malformed request
- `401` missing/invalid client authentication
- `403` authenticated client lacks permission
- `404` account or game not found
- `409` idempotency conflict, duplicate challenge, or state conflict
- `422` validation error
- `500` unexpected server error

Every mutating endpoint must accept an idempotency key, preferably through `Idempotency-Key` and/or a body `reference_id`.

## Required API endpoints

### Health

`GET /health/live`

Returns process health.

`GET /health/ready`

Checks PostgreSQL connectivity and migrations.

### Accounts

`GET /accounts/{external_user_id}`

Response:

```json
{
  "external_user_id": 123,
  "money": 100,
  "credits": 25,
  "is_casino_account": false,
  "created_at": "...",
  "updated_at": "..."
}
```

Create missing user accounts lazily or expose:

`PUT /accounts/{external_user_id}`

This must be idempotent and create a zero-balance account if absent.

`GET /accounts/{external_user_id}/transactions?limit=50&cursor=...`

Return the account's immutable transaction history. Restrict this endpoint so users can see only their own history unless the client is an admin.

### Balance adjustments

`POST /accounts/{external_user_id}/money/adjust`

Admin/controlled-service operation. Request:

```json
{
  "amount": 100,
  "reason": "manual correction",
  "reference_id": "admin-action-123"
}
```

Positive amount credits the account. Negative amount withdraws and must fail if insufficient funds. Do not retain the old silent clamp behavior for new API operations.

`POST /accounts/{external_user_id}/credits/adjust`

Same shape, but adjusts credits.

### Credit exchange

`POST /accounts/{external_user_id}/credits/purchase`

Request:

```json
{
  "amount": 5,
  "price_per_credit": 10,
  "reference_id": "buyc-game-123"
}
```

Atomically withdraw `amount * price_per_credit` money and add `amount` credits. Reject zero/negative amounts and insufficient cash.

`POST /accounts/{external_user_id}/credits/sell`

Atomically withdraw credits and add cash. Reject zero/negative amounts and insufficient credits.

The service should normally own the configured token price instead of trusting a client-provided price. The client field above is useful for an initial migration only; production requests should send an expected price or omit it and let the service apply its configured value.

### Leaderboard

`GET /leaderboard?currency=money&limit=10`

Return top accounts ordered by balance. Exclude the casino account by default. Require an explicit admin option to include it.

### Casino account

`GET /casino/balance`

Resolve the casino account from service configuration, not from a client-supplied arbitrary user ID. The canonical account must be bound to the authenticated Discord bot ID during deployment/setup.

`POST /casino/bind`

Admin/setup-only endpoint. Request:

```json
{
  "external_user_id": 1406929502470410291,
  "migrate_from_external_user_id": 0,
  "reference_id": "initial-bot-binding"
}
```

Rules:

- Bind once during initial migration or explicit administrative rebinding.
- Never delete funds silently.
- If both rows exist, require an explicit merge policy and write a migration transaction.
- Record the binding in service configuration or a `settings` table so it survives API restarts.

### Game settlement

`POST /games/{game_id}/reserve`

Use for games where wager money should be reserved before the outcome is known. Request:

```json
{
  "game_type": "coinflip",
  "currency": "money",
  "players": [
    {"external_user_id": 111, "amount": 10},
    {"external_user_id": 222, "amount": 10}
  ],
  "reference_id": "discord-interaction-123"
}
```

For challenges, this should atomically verify both players and reserve/deduct both stakes. It may either use a separate reservations table or create a `reserved` game settlement transaction. The same `game_id` must be safe to retry.

`POST /games/{game_id}/settle`

Request:

```json
{
  "winner_external_user_id": 111,
  "result": {"heads": "111", "coin": "heads"},
  "fee_enabled": true,
  "fee_percent": 5
}
```

Rules:

- Accept only a currently `reserved` game.
- Compute the fee server-side from trusted service configuration.
- Credit the winner with the pot minus fee.
- Credit the casino account with the fee.
- Mark the game settled and write one transaction with all entries.
- Repeating the exact request returns the original result without changing balances.

`POST /games/{game_id}/refund`

Refund all reserved stakes, mark the game `refunded`, and make retries idempotent. Used for dice ties, cancelled games, and operational failures.

`GET /games/{game_id}`

Return game status, players, wager currency, settlement result, transaction reference, and timestamps. Do not expose sensitive client credentials.

## Transaction and concurrency rules

1. Every balance mutation must happen inside one PostgreSQL transaction.
2. Lock all affected account rows with `SELECT ... FOR UPDATE` in a deterministic account-ID order.
3. Check all balances after locking and before writing deltas.
4. Write account changes and immutable ledger entries in the same database transaction.
5. Use unique `game_id` and `idempotency_key` constraints to make retries safe.
6. Never calculate a payout from a balance read performed outside the transaction.
7. Never trust a client-provided fee or payout amount; the service calculates it.
8. Reject negative/zero amounts on public money/credit operations unless the endpoint explicitly represents a withdrawal/adjustment.
9. Keep casino fee, player stakes, refunds, and payouts auditable as linked ledger entries.
10. Add tests for concurrent withdrawals, simultaneous challenges, repeated settlement, repeated refund, and insufficient funds.

## Migration plan from `economy.db`

### Phase 1: freeze and inspect

- Stop the bot before copying the database.
- Make a backup of `discord/economy.db`.
- Record the configured casino ID and the authenticated bot Discord ID.
- Inspect all rows and identify whether both IDs already exist.
- Do not run the old manual `discord/test_economy.py` against the production database during migration.

### Phase 2: import into PostgreSQL

Build a one-shot migration command, for example:

```text
python -m economy_service.migrate_sqlite --sqlite-path ... --casino-id ... --bot-id ...
```

Migration behavior:

- Read rows from SQLite.
- Create one PostgreSQL account per distinct user ID.
- Preserve `money` and `credits` exactly.
- If the configured casino ID differs from the bot ID and the bot row does not exist, move the configured casino row to the bot ID and write a `migration` transaction.
- If both rows exist, stop and require an explicit merge decision; never overwrite either balance automatically.
- Add a migration ledger record for every imported account or one linked batch transaction.
- Verify imported row count and total money/credits totals.
- Verify the casino account ID and balance.

### Phase 3: compatibility adapter

Replace the bot's SQLite `Economy` implementation with an API client that preserves the methods most callers currently use:

```python
class EconomyClient:
    async def get_entry(self, user_id: int) -> tuple[int, int, int]: ...
    async def get_all_entries(self) -> list[tuple[int, int, int]]: ...
    async def top_entries(self, n: int = 0) -> list[tuple[int, int, int]]: ...
    async def add_money(self, user_id: int, amount: int): ...
    async def add_credits(self, user_id: int, amount: int): ...
    async def set_money(self, user_id: int, amount: int): ...
    async def set_credits(self, user_id: int, amount: int): ...
```

Prefer eventually changing callers to explicit service operations rather than preserving implicit `add_money` casino transfers forever. The adapter is a transition layer, not the final domain API.

### Phase 4: switch and verify

- Run the bot against a staging API/database first.
- Test solo blackjack, solo coinflip, solo dice, slots wagers, credit purchase/sale, challenge acceptance, challenge fee, dice tie refund, and casino balance commands.
- Compare balances and ledger entries against a known test scenario.
- Test API timeout/retry behavior and verify no duplicate payout.
- Disable direct SQLite writes.
- Keep the SQLite backup read-only until the new service has been verified.

### Phase 5: retire direct database access

- Remove `sqlite3` from the bot economy module.
- Remove `economy.db` from the runtime container.
- Keep the migration utility and backup procedure documented.
- Update `llm.txt`, `README.md`, and deployment documentation.

## Docker project structure

Recommended standalone project:

```text
economy-service/
  app/
    __init__.py
    main.py
    config.py
    auth.py
    dependencies.py
    api/
      __init__.py
      health.py
      accounts.py
      casino.py
      games.py
      leaderboard.py
    domain/
      accounts.py
      games.py
      ledger.py
    db/
      session.py
      models.py
      migrations/
    schemas/
      accounts.py
      games.py
      common.py
    repositories/
      accounts.py
      games.py
      ledger.py
    services/
      economy.py
      settlement.py
      migration.py
  tests/
    unit/
    integration/
  scripts/
    migrate_sqlite.py
    verify_migration.py
  Dockerfile
  docker-compose.yml
  alembic.ini
  pyproject.toml
  .env.example
  README.md
```

Suggested `docker-compose.yml` services:

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: casino
      POSTGRES_USER: casino
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data

  economy-api:
    build: .
    depends_on:
      - postgres
    environment:
      DATABASE_URL: postgresql+psycopg://casino:${POSTGRES_PASSWORD}@postgres:5432/casino
      API_KEYS: ${API_KEYS}
      CASINO_EXTERNAL_USER_ID: ${CASINO_EXTERNAL_USER_ID}
    ports:
      - "8000:8000"

volumes:
  postgres_data:
```

For production, do not publish PostgreSQL's port publicly. Put the API behind TLS/reverse proxy if clients are outside the Docker network. Use a managed PostgreSQL instance or tested backup/restore procedures for important data.

## Configuration for the service

Required environment variables:

```text
DATABASE_URL=...
CASINO_EXTERNAL_USER_ID=...
CHALLENGE_FEE_ENABLED=true
CHALLENGE_FEE_PERCENT=5
TOKEN_PRICE=10
API_KEYS=...
LOG_LEVEL=INFO
```

Do not commit real values. The current repository's `config.yml` contains a Discord token and should be treated as compromised if shared outside the local machine.

## Acceptance criteria

The implementation is complete when:

- Multiple clients can read/update balances through the API without direct database access.
- Concurrent withdrawals cannot produce negative balances or double-spend funds.
- Every mutation has an immutable ledger record.
- Repeating a settlement or refund request does not alter balances twice.
- Casino balance is tied to the configured authenticated bot Discord ID.
- Existing SQLite balances migrate without loss.
- Existing bot command behavior remains intact through the compatibility client.
- Challenge fees, player payouts, and tie refunds reconcile exactly.
- Docker restart preserves all data through PostgreSQL volumes/backups.
- Health checks, authentication, migration verification, and rollback procedures are documented and tested.

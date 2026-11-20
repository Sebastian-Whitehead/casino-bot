-- Casino bank transfer: moves money between a player's 'Main' account (found by discord_id) and the
-- 'Blue Horizon Casino' organization account in one transaction.
-- Modeled on public.fab_transfer: same security settings, error codes, locking order and idempotency handling.
--   P0001 invalid_transfer / player_account_unavailable / casino_account_unavailable
--   P0004 insufficient_funds   P0005 idempotency_key_reused
-- p_direction: 'to_casino' (player pays: chip purchase) or 'from_casino' (player is paid: cash-out, bonus).
-- p_transaction_type must be allowed by economy.transactions_type_check (e.g. 'purchase', 'sale', 'reward').

CREATE OR REPLACE FUNCTION public.fab_casino_transfer(
  p_discord_id bigint,
  p_amount bigint,
  p_direction text,
  p_transaction_type text,
  p_idempotency_key text
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_temp'
AS $function$
DECLARE
  v_player_id bigint;
  v_player_count bigint;
  v_player_account_id bigint;
  v_player_account_count bigint;
  v_casino_account_id bigint;
  v_casino_account_number text;
  v_casino_account_count bigint;
  v_source_id bigint;
  v_dest_id bigint;
  v_source_money bigint;
  v_transfer_id uuid;
BEGIN
  IF p_amount IS NULL OR p_amount <= 0 OR p_amount > 500000 OR
     p_direction IS NULL OR p_direction NOT IN ('to_casino', 'from_casino') OR
     p_transaction_type IS NULL OR length(p_transaction_type) = 0 OR
     p_idempotency_key IS NULL OR length(p_idempotency_key) = 0 THEN
    RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'invalid_transfer';
  END IF;

  SELECT count(*), min(id)
    INTO v_player_count, v_player_id
    FROM public.identities_player
    WHERE discord_id = p_discord_id;

  IF v_player_count <> 1 THEN
    RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'player_account_unavailable';
  END IF;

  SELECT count(*), min(id)
    INTO v_player_account_count, v_player_account_id
    FROM economy.accounts
    WHERE player_identity_id = v_player_id
      AND account_type = 'player'
      AND account_name = 'Main'
      AND archived_at IS NULL;

  IF v_player_account_count <> 1 THEN
    RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'player_account_unavailable';
  END IF;

  SELECT count(*), min(a.id), min(a.account_number)
    INTO v_casino_account_count, v_casino_account_id, v_casino_account_number
    FROM economy.accounts a
    JOIN public.identities_organizations o ON o.id = a.organization_id
    WHERE a.account_type = 'organization'
      AND o.name = 'Blue Horizon Casino'
      AND a.archived_at IS NULL;

  IF v_casino_account_count <> 1 THEN
    RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'casino_account_unavailable';
  END IF;

  IF p_direction = 'to_casino' THEN
    v_source_id := v_player_account_id;
    v_dest_id := v_casino_account_id;
  ELSE
    v_source_id := v_casino_account_id;
    v_dest_id := v_player_account_id;
  END IF;

  PERFORM id
  FROM economy.accounts
  WHERE id IN (v_source_id, v_dest_id)
  ORDER BY id
  FOR UPDATE;

  SELECT id INTO v_transfer_id
  FROM economy.transactions
  WHERE idempotency_key = p_idempotency_key;

  IF v_transfer_id IS NOT NULL THEN
    IF (SELECT count(*) FROM economy.transactions_entries WHERE transaction_id = v_transfer_id) = 2
       AND EXISTS (
         SELECT 1 FROM economy.transactions_entries
         WHERE transaction_id = v_transfer_id AND account_id = v_source_id AND money_delta = -p_amount
       )
       AND EXISTS (
         SELECT 1 FROM economy.transactions_entries
         WHERE transaction_id = v_transfer_id AND account_id = v_dest_id AND money_delta = p_amount
       ) THEN
      RETURN jsonb_build_object('transaction_id', v_transfer_id);
    ELSE
      RAISE EXCEPTION USING ERRCODE = 'P0005', MESSAGE = 'idempotency_key_reused';
    END IF;
  END IF;

  SELECT money INTO v_source_money
  FROM economy.accounts
  WHERE id = v_source_id;

  IF v_source_money < p_amount THEN
    RAISE EXCEPTION USING ERRCODE = 'P0004', MESSAGE = 'insufficient_funds';
  END IF;

  INSERT INTO economy.transactions (
    idempotency_key,
    transaction_type,
    reference_id,
    actor_account_id,
    actor_label,
    description
  )
  VALUES (
    p_idempotency_key,
    p_transaction_type,
    v_casino_account_number,
    v_player_account_id,
    'casino-bot',
    CASE p_direction WHEN 'to_casino' THEN 'Casino chips bought' ELSE 'Casino payout' END
  )
  ON CONFLICT (idempotency_key) DO NOTHING
  RETURNING id INTO v_transfer_id;

  IF v_transfer_id IS NULL THEN  -- lost a race with another request using the same key
    RAISE EXCEPTION USING ERRCODE = 'P0005', MESSAGE = 'idempotency_key_reused';
  END IF;

  INSERT INTO economy.transactions_entries (transaction_id, account_id, money_delta)
  VALUES
    (v_transfer_id, v_source_id, -p_amount),
    (v_transfer_id, v_dest_id, p_amount);

  UPDATE economy.accounts
  SET money = money - p_amount, updated_at = now()
  WHERE id = v_source_id;

  UPDATE economy.accounts
  SET money = money + p_amount, updated_at = now()
  WHERE id = v_dest_id;

  RETURN jsonb_build_object('transaction_id', v_transfer_id);
END;
$function$;

REVOKE ALL ON FUNCTION public.fab_casino_transfer(bigint, bigint, text, text, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fab_casino_transfer(bigint, bigint, text, text, text) TO service_role;

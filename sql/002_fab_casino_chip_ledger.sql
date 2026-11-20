-- Reconciliation helper: net cents the 'Blue Horizon Casino' account has taken in from chip purchases minus cash-outs.
-- Counts only ledger rows written by fab_casino_transfer ('casino-bot') of type 'purchase' / 'sale'
-- (bonuses are 'reward' and deliberately not counted). Read-only; same security settings as fab_casino_transfer.
-- Returns {"net_cents": <bigint>}. P0001 casino_account_unavailable.

CREATE OR REPLACE FUNCTION public.fab_casino_chip_ledger()
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_temp'
AS $function$
DECLARE
  v_casino_account_id bigint;
  v_casino_account_count bigint;
  v_net bigint;
BEGIN
  SELECT count(*), min(a.id)
    INTO v_casino_account_count, v_casino_account_id
    FROM economy.accounts a
    JOIN public.identities_organizations o ON o.id = a.organization_id
    WHERE a.account_type = 'organization'
      AND o.name = 'Blue Horizon Casino'
      AND a.archived_at IS NULL;

  IF v_casino_account_count <> 1 THEN
    RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'casino_account_unavailable';
  END IF;

  SELECT coalesce(sum(e.money_delta), 0)
    INTO v_net
    FROM economy.transactions_entries e
    JOIN economy.transactions t ON t.id = e.transaction_id
    WHERE e.account_id = v_casino_account_id
      AND t.actor_label = 'casino-bot'
      AND t.transaction_type IN ('purchase', 'sale');

  RETURN jsonb_build_object('net_cents', v_net);
END;
$function$;

REVOKE ALL ON FUNCTION public.fab_casino_chip_ledger() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fab_casino_chip_ledger() TO service_role;

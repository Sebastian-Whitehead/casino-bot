"""Restore discord/economy.db from a Supabase backup (table public.casino_backups).

Stop the bot first. Usage (from the repo root):
    .venv/Scripts/python scripts/restore_backup.py            # list backups
    .venv/Scripts/python scripts/restore_backup.py --latest   # restore the newest
    .venv/Scripts/python scripts/restore_backup.py --id 7     # restore backup 7
Options: --out PATH (default discord/economy.db; ECONOMY_DB_PATH is honoured), --yes (skip the prompt).
The current file is moved to <file>.before-restore first, and the backup's hash and integrity are checked.
"""
import argparse
import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import psycopg
import yaml

ROOT = Path(__file__).resolve().parent.parent


def db_url() -> str:
    url = os.environ.get('SUPABASE_DATABASE_URL')
    if not url:
        url = (yaml.safe_load((ROOT / 'config.yml').read_text(encoding='utf-8')).get('bot') or {}).get('supabase_database_url')
    if not url:
        sys.exit("No Supabase URL: set SUPABASE_DATABASE_URL or supabase_database_url in config.yml")
    return url.replace('?ssl=', '?sslmode=').replace('&ssl=', '&sslmode=')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--id', type=int)
    ap.add_argument('--latest', action='store_true')
    ap.add_argument('--out', default=os.environ.get('ECONOMY_DB_PATH') or str(ROOT / 'discord' / 'economy.db'))
    ap.add_argument('--yes', action='store_true')
    a = ap.parse_args()

    with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
        if not a.id and not a.latest:
            cur.execute("SELECT id, created_at, label, size_bytes FROM public.casino_backups ORDER BY created_at DESC, id DESC")
            for row in cur.fetchall():
                print(f"id {row[0]:>4}  {row[1]:%Y-%m-%d %H:%M:%S}  {row[3]:>9,} bytes  {row[2]}")
            print("\nRestore with --latest or --id N")
            return
        if a.id:
            cur.execute("SELECT id, created_at, sha256, data FROM public.casino_backups WHERE id = %s", (a.id,))
        else:
            cur.execute("SELECT id, created_at, sha256, data FROM public.casino_backups ORDER BY created_at DESC, id DESC LIMIT 1")
        row = cur.fetchone()
    if row is None:
        sys.exit("No such backup")
    bid, created, sha, data = row[0], row[1], row[2], bytes(row[3])
    if hashlib.sha256(data).hexdigest() != sha:
        sys.exit("Backup is corrupt (hash mismatch); nothing changed")

    fd, tmp = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        Path(tmp).write_bytes(data)
        check = sqlite3.connect(tmp)
        ok = check.execute("PRAGMA integrity_check").fetchone()[0]
        chips = check.execute("SELECT count(*), coalesce(sum(chips), 0) FROM economy").fetchone()
        check.close()
        if ok != 'ok':
            sys.exit(f"Backup failed the SQLite integrity check ({ok}); nothing changed")
        out = Path(a.out)
        print(f"Backup {bid} from {created:%Y-%m-%d %H:%M:%S}: {chips[0]} chip rows, {chips[1]} chips in total.")
        print(f"This replaces {out} (the current file is kept as {out.name}.before-restore).")
        if not a.yes and input("Type 'restore' to continue: ").strip() != 'restore':
            sys.exit("Cancelled")
        if out.exists():
            shutil.copy2(out, str(out) + '.before-restore')
        shutil.copy2(tmp, out)
        print("Restored. Start the bot, then run /reconcile.")
    finally:
        os.remove(tmp)


if __name__ == '__main__':
    main()

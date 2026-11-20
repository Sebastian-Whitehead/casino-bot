import asyncio
import logging

from modules.economy import Economy
from modules.helpers import BACKUP_INTERVAL_HOURS, BACKUP_KEEP, BACKUP_MAX_AGE_HOURS

logger = logging.getLogger(__name__)
_started = False  # on_ready can fire again after a reconnect: one loop only


def run_backup_once():
    """One snapshot upload. shortcut: synchronous (a ~50 KB upload every few hours); move to a thread if the DB grows large."""
    result = Economy().backup_to_supabase(BACKUP_KEEP, BACKUP_MAX_AGE_HOURS)
    if result:
        logger.info("[Backup] Uploaded backup %s (%s kept, %s pruned)", result['id'], result['kept'], result['deleted'])
    return result


def setup_backups(client):
    """Start the periodic backup loop; does nothing when backup_interval_hours is 0."""
    if not BACKUP_INTERVAL_HOURS or BACKUP_INTERVAL_HOURS <= 0:
        logger.info("[Backup] Disabled (backup_interval_hours is 0)")
        return

    global _started
    if _started:
        return
    _started = True

    async def loop():
        await client.wait_until_ready()
        while not client.is_closed():
            try:
                run_backup_once()
            except Exception:
                logger.exception("[Backup] Backup failed; will retry next interval")
            await asyncio.sleep(BACKUP_INTERVAL_HOURS * 3600)
    client.loop.create_task(loop())

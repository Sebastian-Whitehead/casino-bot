import asyncio
import logging

import nextcord as discord

from modules.helpers import THREAD_TIMEOUT_MINUTES, THREAD_CLEANUP_CHECK_SECONDS, CASINO_CHANNEL_ID

logger = logging.getLogger(__name__)


async def _collect_threads(channel) -> list:
    """Cached + active (from the API) + recently archived threads of the casino channel."""
    found = {t.id: t for t in channel.threads}
    # Cache misses are the usual reason threads were "found" but never seen: ask Discord too.
    try:
        for t in await channel.guild.active_threads():
            if t.parent_id == channel.id:
                found[t.id] = t
    except Exception as e:
        logger.warning("[Thread Cleanup] Could not fetch active threads: %s", e)
    try:
        async for t in channel.archived_threads(limit=50):
            found[t.id] = t
    except Exception as e:
        logger.warning("[Thread Cleanup] Could not fetch archived threads: %s", e)
    return list(found.values())


async def _last_activity(thread):
    """Time of the newest message, falling back to the thread's creation time."""
    try:
        async for msg in thread.history(limit=1):
            return msg.created_at
    except Exception as e:
        logger.warning("[Thread Cleanup] Could not read history of %r (%s): %s", thread.name, thread.id, e)
    return thread.created_at


async def cleanup_threads_once(client) -> int:
    """Delete expired threads in the casino channel. Returns how many were deleted."""
    channel = client.get_channel(CASINO_CHANNEL_ID)
    if not channel:
        logger.error("[Thread Cleanup] Channel with ID %s not found.", CASINO_CHANNEL_ID)
        return 0
    threads = await _collect_threads(channel)
    logger.info("[Thread Cleanup] Channel %r (ID: %s), threads: %d", channel.name, channel.id, len(threads))
    now = discord.utils.utcnow()
    deleted = 0
    for thread in threads:
        last = await _last_activity(thread)
        if last is None or (now - last).total_seconds() <= THREAD_TIMEOUT_MINUTES * 60:
            continue
        try:
            await thread.delete()
            deleted += 1
            logger.info("[Thread Cleanup] Deleted thread %r (ID: %s)", thread.name, thread.id)
        except discord.Forbidden:
            logger.error("[Thread Cleanup] Missing Manage Threads permission to delete %r (ID: %s)", thread.name, thread.id)
        except discord.NotFound:
            logger.warning("[Thread Cleanup] Thread %r (ID: %s) not found, already deleted?", thread.name, thread.id)
        except Exception as e:
            logger.error("[Thread Cleanup] Error deleting thread %r (ID: %s): %s", thread.name, thread.id, e)
    return deleted


def setup_auto_thread_cleanup(client):
    async def loop():
        await client.wait_until_ready()
        logger.info("[Thread Cleanup] Cleanup task started for channel %s", CASINO_CHANNEL_ID)
        while not client.is_closed():
            try:
                await cleanup_threads_once(client)
            except Exception as e:
                logger.error("[Thread Cleanup] Exception in cleanup loop: %s", e)
            await asyncio.sleep(THREAD_CLEANUP_CHECK_SECONDS)
    client.loop.create_task(loop())


async def run_thread_cleanup(client) -> int:
    """Manually trigger one cleanup pass; returns the number of threads deleted."""
    logger.info("[Thread Cleanup] Manual cleanup triggered.")
    deleted = await cleanup_threads_once(client)
    logger.info("[Thread Cleanup] Manual cleanup deleted %d thread(s).", deleted)
    return deleted

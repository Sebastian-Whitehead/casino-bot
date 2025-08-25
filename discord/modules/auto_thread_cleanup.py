import asyncio
import nextcord as discord
import sys

# Set your game channel ID (timeout is now loaded from config)
GAME_CHANNEL_ID = 1409120191534858361  # <-- Your specified channel ID


# Import thread timeout from shared config
from modules.helpers import THREAD_TIMEOUT_MINUTES, THREAD_CLEANUP_CHECK_SECONDS

# Debug: Print loaded config values at import
print(f"[Thread Cleanup][DEBUG] Loaded config: TIMEOUT_MINUTES={THREAD_TIMEOUT_MINUTES}, CLEANUP_CHECK_SECONDS={THREAD_CLEANUP_CHECK_SECONDS}")

def setup_auto_thread_cleanup(client):
    async def auto_delete_dormant_threads():
        safe_print(f"[Thread Cleanup] Cleanup task started. Looking for channel ID: {GAME_CHANNEL_ID}")
        await client.wait_until_ready()
        while not client.is_closed():
            try:
                channel = client.get_channel(GAME_CHANNEL_ID)
                if not channel:
                    safe_print(f"[Thread Cleanup][ERROR] Channel with ID {GAME_CHANNEL_ID} not found.")
                else:
                    safe_print(f"[Thread Cleanup] Found channel: {repr(channel.name)} (ID: {channel.id}), threads: {len(channel.threads)}")
                    now = discord.utils.utcnow()
                    for thread in channel.threads:
                        # Use thread object from cache (channel.threads)
                        if thread.archived:
                            continue
                        created_at = getattr(thread, 'created_at', None)
                        updated_at = getattr(thread, 'updated_at', None)
                        last_message_id = getattr(thread, 'last_message_id', None)
                        last_active = updated_at or created_at
                        try:
                            age_seconds = (now - last_active).total_seconds() if last_active else None
                        except Exception as e:
                            safe_print(f"[Thread Cleanup][ERROR] Exception calculating age_seconds: {e}")
                            age_seconds = None
                        # Only log when actually purging a thread
                        if age_seconds is not None and age_seconds > THREAD_TIMEOUT_MINUTES * 60:
                            safe_print(f"[Thread Cleanup] Purging thread: {repr(thread.name)} (ID: {thread.id}) in channel {repr(channel.name)} (ID: {channel.id}), age: {age_seconds:.1f}s")
                            try:
                                await thread.delete()
                            except Exception as e:
                                safe_print(f"[Thread Cleanup] Error deleting thread {repr(thread.name)} (ID: {thread.id}): {e}")
            except Exception as e:
                safe_print(f"[Thread Cleanup][ERROR] Exception in cleanup loop: {e}")
            await asyncio.sleep(THREAD_CLEANUP_CHECK_SECONDS)
    client.loop.create_task(auto_delete_dormant_threads())

def safe_print(*args, **kwargs):
    s = ' '.join(str(a) for a in args)
    try:
        print(s, **kwargs, flush=True)
    except UnicodeEncodeError:
        # Always encode as utf-8 and replace errors for Windows console
        print(s.encode('utf-8', errors='replace').decode('utf-8'), **kwargs, flush=True)

async def run_thread_cleanup(client):
    """Manually trigger the thread cleanup once (cached threads only)."""
    safe_print("[Thread Cleanup] Manual cleanup triggered.")
    channel = client.get_channel(GAME_CHANNEL_ID)
    if not channel:
        safe_print(f"[Thread Cleanup] Channel with ID {GAME_CHANNEL_ID} not found.")
        return
    threads = list(channel.threads)
    # Remove duplicates by thread ID (shouldn't be needed, but for safety)
    seen = set()
    unique_threads = []
    for t in threads:
        if t.id not in seen:
            unique_threads.append(t)
            seen.add(t.id)
    safe_print(f"[Thread Cleanup] Found channel: {repr(channel.name)} (ID: {channel.id}), threads: {len(unique_threads)}")
    now = discord.utils.utcnow()
    for thread in unique_threads:
        # Use thread object from cache (unique_threads)
        safe_print(f"[Thread Cleanup] Checking thread: {repr(thread.name)} (ID: {thread.id}), archived: {thread.archived}")
        if thread.archived:
            continue
        created_at = getattr(thread, 'created_at', None)
        updated_at = getattr(thread, 'updated_at', None)
        last_message_id = getattr(thread, 'last_message_id', None)
        last_active = updated_at or created_at
        age_seconds = (now - last_active).total_seconds() if last_active else None
        safe_print(f"[Thread Cleanup] created_at: {created_at}, updated_at: {updated_at}, last_message_id: {last_message_id}, now: {now}, age: {age_seconds:.1f}s, timeout: {THREAD_TIMEOUT_MINUTES*60}s")
        if age_seconds is not None and age_seconds > THREAD_TIMEOUT_MINUTES * 60:
            safe_print(f"[Thread Cleanup] Purging thread: {repr(thread.name)} (ID: {thread.id}) in channel {repr(channel.name)} (ID: {channel.id}), age: {age_seconds:.1f}s")
            try:
                await thread.delete()
            except Exception as e:
                safe_print(f"[Thread Cleanup] Error deleting thread {repr(thread.name)} (ID: {thread.id}): {e}")

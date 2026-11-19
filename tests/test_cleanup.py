import os
import sys
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

os.environ["ECONOMY_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "discord"))

import nextcord
from modules import auto_thread_cleanup as atc


def make_thread(tid, age_min, delete=None):
    t = MagicMock()
    t.id, t.name, t.parent_id = tid, f"t{tid}", 1
    t.created_at = nextcord.utils.utcnow() - timedelta(minutes=age_min)

    async def history(limit=1):  # last message == creation time here
        yield MagicMock(created_at=t.created_at)

    t.history = history
    t.delete = delete or AsyncMock()
    return t


def make_client(cached, active=()):
    async def archived(limit=50):
        return
        yield

    ch = MagicMock(id=1)
    ch.threads = list(cached)
    ch.guild.active_threads = AsyncMock(return_value=list(active))
    ch.archived_threads = archived
    client = MagicMock()
    client.get_channel.return_value = ch
    return client


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        atc.CASINO_CHANNEL_ID = 1
        atc.THREAD_TIMEOUT_MINUTES = 10

    async def test_expired_deleted_fresh_kept_and_api_threads_found(self):
        old, fresh, api_old = make_thread(1, 60), make_thread(2, 1), make_thread(3, 90)
        n = await atc.run_thread_cleanup(make_client([old, fresh], [api_old]))
        self.assertEqual(n, 2)
        old.delete.assert_awaited_once()
        api_old.delete.assert_awaited_once()
        fresh.delete.assert_not_awaited()

    async def test_permission_failure_is_logged_not_raised(self):
        bad = make_thread(1, 60, AsyncMock(side_effect=nextcord.Forbidden(MagicMock(status=403, reason="x"), "no")))
        with self.assertLogs(atc.logger, "ERROR") as cm:
            n = await atc.run_thread_cleanup(make_client([bad]))
        self.assertEqual(n, 0)
        self.assertIn("Manage Threads", cm.output[0])


if __name__ == "__main__":
    unittest.main()

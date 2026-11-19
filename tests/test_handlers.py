import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("ECONOMY_DB_PATH", os.path.join(tempfile.mkdtemp(), "h.db"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "discord"))

from nextcord.ext.commands.errors import (CommandInvokeError, CommandOnCooldown, MissingRequiredArgument,  # noqa: E402
                                          NotOwner)
from cogs.handlers import Handlers, cooldown_text  # noqa: E402
from modules.helpers import InsufficientFundsException  # noqa: E402


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    def ctx(self):
        cmd = SimpleNamespace(name="add", usage="add", signature="")
        return Mock(command=cmd, send=AsyncMock())

    async def test_cooldown_text(self):
        self.assertEqual(cooldown_text(3725), "1hrs 2min 5sec remaining.")

    async def test_insufficient_funds_inside_invoke_error(self):
        ctx = self.ctx()
        err = CommandInvokeError(InsufficientFundsException(1, 5))
        await Handlers(Mock()).on_command_error(ctx, err)
        self.assertIn("/cashier", ctx.send.await_args.args[0])

    async def test_missing_argument_shows_usage_not_crash(self):
        ctx = self.ctx()
        await Handlers(Mock()).on_command_error(ctx, MissingRequiredArgument(Mock(displayed_name="x")))
        self.assertIn("Usage:", ctx.send.await_args.args[0])

    async def test_not_owner_is_silent(self):
        ctx = self.ctx()
        await Handlers(Mock()).on_command_error(ctx, NotOwner())
        ctx.send.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

import aiohttp
import nextcord
from nextcord import ui, Interaction, ButtonStyle
from modules.helpers import make_embed


def format_chips(n: int) -> str:
    """The only place the currency word lives."""
    return f"{n} chip" if n == 1 else f"{n} chips"


async def _retry(label, func, **kw):
    # shortcut: files are single-use streams, so a retried send with file= may go out without it
    for attempt in (1, 2):
        try:
            return await func(**kw)
        except (aiohttp.ClientOSError, nextcord.HTTPException) as error:
            print(f"[game_ui] {label} failed (attempt {attempt}): {error!r}")
    return None


async def safe_edit(message, **kw):
    return await _retry("edit", message.edit, **kw)


async def safe_send(destination, **kw):
    return await _retry("send", destination.send, **kw)


def build_result_embed(title, won, net, wallet, extra=None):
    """net = payout - bet (negative on a loss); wallet = chips after settling."""
    if net > 0:
        headline = f"You won {format_chips(net)}!"
    elif net < 0:
        headline = f"You lost {format_chips(-net)}."
    else:
        headline = "Push: your bet was returned."
    lines = [headline]
    if extra:
        lines.append(extra)
    lines.append(f"Wallet: {format_chips(wallet)}")
    color = nextcord.Color.green() if won else nextcord.Color.red()
    return make_embed(title=title, description="\n".join(lines), color=color)


class GameResultView(ui.View):
    """Play Again / Back to Bet under a result message. Owner only."""

    def __init__(self, cog, betting_view, replay_kwargs=None):
        super().__init__(timeout=None)
        self.cog = cog
        self.betting_view = betting_view
        self.replay_kwargs = replay_kwargs or {}

    async def interaction_check(self, interaction: Interaction) -> bool:
        return interaction.user.id == self.betting_view.user.id

    @ui.button(label="Play Again", style=ButtonStyle.success, row=0, custom_id="result_play_again")
    async def play_again(self, button, interaction: Interaction):
        await self.cog.start_round(self.betting_view, interaction, confirmed=True, **self.replay_kwargs)  # same bet again

    @ui.button(label="Back to Bet", style=ButtonStyle.secondary, row=0, custom_id="result_back_to_bet")
    async def back_to_bet(self, button, interaction: Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer()
        try:
            await interaction.message.delete()
        except Exception:
            pass
        self.betting_view.game_message = None
        await self.betting_view.refresh_bet_message()


WRONG_CHANNEL = "This command can only be used in the designated casino channel."


async def ensure_casino_channel(interaction) -> bool:
    """The one casino-channel restriction: replies (ephemeral) and returns False when not allowed."""
    from modules.helpers import CASINO_CHANNEL_ID, RESTRICT_TO_CASINO_CHANNEL  # read live so tests can patch
    if not RESTRICT_TO_CASINO_CHANNEL or interaction.channel.id == CASINO_CHANNEL_ID:
        return True
    await interaction.response.send_message(WRONG_CHANNEL, ephemeral=True)
    return False

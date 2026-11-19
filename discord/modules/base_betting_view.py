from nextcord import ui, Interaction, ButtonStyle
from modules.helpers import make_embed
from modules.game_ui import format_chips, safe_edit

class BaseBettingView(ui.View):
    min_bet = 1  # per-game override, used by cap_bet

    def __init__(self, cog, user, bet, thread):
        super().__init__(timeout=None)
        self.cog = cog
        self.user = user
        self.bet = bet
        self.thread = thread
        self.bet_message = None
        self.game_message = None

    def get_balance(self) -> int:
        return self.cog.economy.get_chips(self.user.id)

    def cap_bet(self, new_bet: int) -> int:
        return max(self.min_bet, min(new_bet, self.get_balance()))

    def bet_embed(self):
        return make_embed(
            title="Set your bet",
            description=f"Current bet: {format_chips(self.bet)}\nWallet: {format_chips(self.get_balance())}")

    async def refresh_bet_message(self):
        if self.bet_message:
            await safe_edit(self.bet_message, embed=self.bet_embed(), view=self)

    async def interaction_check(self, interaction: Interaction) -> bool:
        return interaction.user.id == self.user.id

    @ui.button(label="x10", style=ButtonStyle.secondary, row=0, custom_id="bet_mul_10")
    async def bet_mul_10(self, button, interaction: Interaction):
        self.bet = self.cap_bet(self.bet * 10)
        await self.update_bet_message(interaction)

    @ui.button(label="+10", style=ButtonStyle.secondary, row=0, custom_id="bet_plus_10")
    async def bet_plus_10(self, button, interaction: Interaction):
        self.bet = self.cap_bet(self.bet + 10)
        await self.update_bet_message(interaction)

    @ui.button(label="+1", style=ButtonStyle.secondary, row=0, custom_id="bet_plus_1")
    async def bet_plus_1(self, button, interaction: Interaction):
        self.bet = self.cap_bet(self.bet + 1)
        await self.update_bet_message(interaction)

    @ui.button(label="/10", style=ButtonStyle.secondary, row=1, custom_id="bet_div_10")
    async def bet_div_10(self, button, interaction: Interaction):
        self.bet = self.cap_bet(self.bet // 10)
        await self.update_bet_message(interaction)

    @ui.button(label="-10", style=ButtonStyle.secondary, row=1, custom_id="bet_minus_10")
    async def bet_minus_10(self, button, interaction: Interaction):
        self.bet = self.cap_bet(self.bet - 10)
        await self.update_bet_message(interaction)

    @ui.button(label="-1", style=ButtonStyle.secondary, row=1, custom_id="bet_minus_1")
    async def bet_minus_1(self, button, interaction: Interaction):
        self.bet = self.cap_bet(self.bet - 1)
        await self.update_bet_message(interaction)

    @ui.button(emoji="❌", style=ButtonStyle.danger, row=2, custom_id="close")
    async def close(self, button, interaction: Interaction):
        if self.game_message:
            await self.game_message.delete()
        if self.bet_message:
            try:
                await self.bet_message.edit(view=None)
            except Exception:
                pass
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Game ended and thread closed.", ephemeral=True)
        except Exception:
            pass
        refund = getattr(self.cog, "refund_open_round", None)
        if refund:  # e.g. blackjack: closing mid-hand must not keep the stake
            refund(self)
        getattr(self.cog, "active_games", {}).pop(self.thread.id, None)
        try:
            await self.thread.edit(archived=True, locked=True)
        except Exception:
            pass

    async def update_bet_message(self, interaction):
        await interaction.response.edit_message(embed=self.bet_embed(), view=self)

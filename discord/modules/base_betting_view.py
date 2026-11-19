from nextcord import ui, Interaction, ButtonStyle
from modules.helpers import make_embed

class BaseBettingView(ui.View):
    balance_index = 1
    bet_title = "Set your bet ($)"
    currency_name = "cash"

    def __init__(self, cog, user, bet, thread):
        super().__init__(timeout=None)
        self.cog = cog
        self.user = user
        self.bet = bet
        self.thread = thread
        self.bet_message = None
        self.game_message = None

    def cap_bet(self, new_bet: int) -> int:
        balance = self.cog.economy.get_entry(self.user.id)[self.balance_index]
        return max(1, min(new_bet, balance))

    def get_balance(self):
        return self.cog.economy.get_entry(self.user.id)[self.balance_index]

    def bet_embed(self):
        balance = self.get_balance()
        if self.currency_name == "credits":
            description = f"Current bet: {self.bet} credits\nWallet: {balance} credits"
        else:
            description = f"Current bet: ${self.bet}\nWallet: ${balance}"
        return make_embed(title=self.bet_title, description=description)

    async def refresh_bet_message(self):
        if self.bet_message:
            await self.bet_message.edit(embed=self.bet_embed(), view=self)

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
        try:
            await self.thread.edit(archived=True, locked=True)
        except Exception:
            pass

    async def update_bet_message(self, interaction):
        await interaction.response.edit_message(embed=self.bet_embed(), view=self)

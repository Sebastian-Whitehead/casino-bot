import nextcord
from nextcord import ui, ButtonStyle, Interaction
from nextcord.ext import commands

from modules.economy import Economy
from modules.game_ui import ensure_casino_channel, format_chips
from modules.helpers import (
    CHIP_VALUE, TEST_GUILD_ID, TEST_MODE,
    InsufficientFundsException, make_embed,
)



def do_buy(economy, uid: int, n: int):
    """Returns (ok, message). Same rules for the view and /buy."""
    price = n * CHIP_VALUE
    have = economy.bank.balance(uid)
    if economy.buy_chips(uid, n):
        return True, f"Bought {format_chips(n)} for ${price:,}."
    return False, f"Insufficient funds: you need ${price:,}, you have ${have:,}."


def do_cash_out(economy, uid: int, n: int):
    chips = economy.get_chips(uid)
    if chips < n:
        return False, f"You only have {format_chips(chips)}."
    try:
        economy.cash_out(uid, n)
    except InsufficientFundsException:
        return False, "The casino cannot pay that out right now. Nothing changed."
    return True, f"Cashed out {format_chips(n)} for ${n * CHIP_VALUE:,}."


def balances_text(economy, uid: int) -> str:
    bank = "unlimited (test mode)" if TEST_MODE else f"${economy.bank.balance(uid):,}"
    return f"Bank: {bank}\nWallet: {format_chips(economy.get_chips(uid))}"


class CashierView(ui.View):
    def __init__(self, user, economy=None):
        super().__init__(timeout=300)
        self.user = user
        self.economy = economy or Economy()
        self.buying = True
        self.quantity = 1
        self.message = None
        self.done = False
        self._sync()

    def cap(self) -> int:
        uid = self.user.id
        n = self.economy.bank.balance(uid) // CHIP_VALUE if self.buying else self.economy.get_chips(uid)
        return max(1, n)

    def _sync(self):
        self.quantity = max(1, min(self.quantity, self.cap()))
        self.toggle.label = "Mode: Buy" if self.buying else "Mode: Cash Out"
        self.confirm.label = "Check Out" if self.buying else "Cash Out"
        for child in self.children:
            child.disabled = self.done

    def embed(self, note=None):
        mode = "Buy" if self.buying else "Cash Out"
        lines = [f"Mode: **{mode}**",
                 f"{format_chips(self.quantity)} = ${self.quantity * CHIP_VALUE:,}",
                 balances_text(self.economy, self.user.id)]
        if note:
            lines.append(f"\n{note}")
        return make_embed(title="Chip Cashier", description="\n".join(lines))

    async def interaction_check(self, interaction: Interaction) -> bool:
        return interaction.user.id == self.user.id

    async def _update(self, interaction, note=None):
        self._sync()
        await interaction.response.edit_message(embed=self.embed(note), view=self)

    async def _qty(self, interaction, fn):
        self.quantity = fn(self.quantity)
        await self._update(interaction)

    @ui.button(label="Mode: Buy", style=ButtonStyle.primary, row=0, custom_id="cashier_toggle")
    async def toggle(self, button, interaction: Interaction):
        self.buying = not self.buying
        await self._update(interaction)

    @ui.button(label="Check Out", style=ButtonStyle.success, row=0, custom_id="cashier_confirm")
    async def confirm(self, button, interaction: Interaction):
        act = do_buy if self.buying else do_cash_out
        ok, msg = act(self.economy, self.user.id, self.quantity)  # re-checked against live balances
        if ok:
            self.done = True
        await self._update(interaction, msg)

    @ui.button(label="Cancel", style=ButtonStyle.danger, row=0, custom_id="cashier_cancel")
    async def cancel(self, button, interaction: Interaction):
        self.done = True
        self.stop()
        await interaction.response.edit_message(embed=make_embed(title="Chip Cashier", description="Closed."), view=None)

    @ui.button(label="x10", style=ButtonStyle.secondary, row=1, custom_id="cashier_x10")
    async def x10(self, button, interaction: Interaction):
        await self._qty(interaction, lambda q: q * 10)

    @ui.button(label="+10", style=ButtonStyle.secondary, row=1, custom_id="cashier_p10")
    async def p10(self, button, interaction: Interaction):
        await self._qty(interaction, lambda q: q + 10)

    @ui.button(label="+1", style=ButtonStyle.secondary, row=1, custom_id="cashier_p1")
    async def p1(self, button, interaction: Interaction):
        await self._qty(interaction, lambda q: q + 1)

    @ui.button(label="/10", style=ButtonStyle.secondary, row=2, custom_id="cashier_d10")
    async def d10(self, button, interaction: Interaction):
        await self._qty(interaction, lambda q: q // 10)

    @ui.button(label="-10", style=ButtonStyle.secondary, row=2, custom_id="cashier_m10")
    async def m10(self, button, interaction: Interaction):
        await self._qty(interaction, lambda q: q - 10)

    @ui.button(label="-1", style=ButtonStyle.secondary, row=2, custom_id="cashier_m1")
    async def m1(self, button, interaction: Interaction):
        await self._qty(interaction, lambda q: q - 1)

    @ui.button(label="Max", style=ButtonStyle.secondary, row=2, custom_id="cashier_max")
    async def max_(self, button, interaction: Interaction):
        await self._qty(interaction, lambda q: self.cap())

    async def on_timeout(self):
        self.done = True
        self._sync()
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


class Cashier(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.economy = Economy()

    @nextcord.slash_command(name="cashier", description="Buy chips or cash them out.", guild_ids=[TEST_GUILD_ID])
    async def cashier(self, interaction: Interaction):
        if not await ensure_casino_channel(interaction):
            return
        view = CashierView(interaction.user, self.economy)
        await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)
        view.message = await interaction.original_message()

    @nextcord.slash_command(name="buy", description="Buy chips with your bank money.", guild_ids=[TEST_GUILD_ID])
    async def buy(self, interaction: Interaction, amount: int = nextcord.SlashOption(description="Chips to buy")):
        if not await ensure_casino_channel(interaction):
            return
        if amount < 1:
            return await interaction.response.send_message("Amount must be at least 1 chip.", ephemeral=True)
        _, msg = do_buy(self.economy, interaction.user.id, amount)
        await interaction.response.send_message(f"{msg}\n{balances_text(self.economy, interaction.user.id)}", ephemeral=True)

    @nextcord.slash_command(name="cashout", description="Cash chips out to bank money.", guild_ids=[TEST_GUILD_ID])
    async def cashout(self, interaction: Interaction,
                      amount: str = nextcord.SlashOption(description="Number of chips, or 'all'")):
        if not await ensure_casino_channel(interaction):
            return
        uid = interaction.user.id
        n = parse_cashout(amount, self.economy.get_chips(uid))
        if n is None:
            return await interaction.response.send_message("Amount must be a whole number of chips (1 or more) or 'all'.", ephemeral=True)
        _, msg = do_cash_out(self.economy, uid, n)
        await interaction.response.send_message(f"{msg}\n{balances_text(self.economy, uid)}", ephemeral=True)

    @nextcord.slash_command(name="balance", description="Show your bank money and chips.", guild_ids=[TEST_GUILD_ID])
    async def balance(self, interaction: Interaction, user: nextcord.Member = None):
        if not await ensure_casino_channel(interaction):
            return
        user = user or interaction.user
        embed = make_embed(title=f"{user.display_name}'s Balance", description=balances_text(self.economy, user.id))
        embed.set_thumbnail(url=user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=(user == interaction.user))


def parse_cashout(text: str, chips: int):
    """Chip count for /cashout, or None if invalid (< 1 or not a number)."""
    text = text.strip().lower()
    if text == "all":
        return chips if chips >= 1 else None
    try:
        n = int(text)
    except ValueError:
        return None
    return n if n >= 1 else None


def setup(client: commands.Bot):
    client.add_cog(Cashier(client))

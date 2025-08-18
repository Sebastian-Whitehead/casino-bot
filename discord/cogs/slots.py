import bisect
import os
import random
import nextcord as discord
from nextcord.ext import commands
from nextcord import ui, Interaction, ButtonStyle
from modules.economy import Economy
from modules.helpers import *
from PIL import Image


class BettingView(ui.View):
    def __init__(self, cog, user, bet, thread):
        super().__init__(timeout=None)
        self.cog = cog
        self.user = user
        self.bet = bet
        self.thread = thread
        self.bet_message = None
        self.game_message = None

    @ui.button(label="/10", style=ButtonStyle.secondary, row=0, custom_id="bet_div_10")
    async def bet_div_10(self, button, interaction: Interaction):
        self.bet = max(1, self.bet // 10)
        await self.update_bet_message(interaction)

    @ui.button(label="-10", style=ButtonStyle.secondary, row=0, custom_id="bet_minus_10")
    async def bet_minus_10(self, button, interaction: Interaction):
        self.bet = max(1, self.bet - 10)
        await self.update_bet_message(interaction)

    @ui.button(label="-1", style=ButtonStyle.secondary, row=0, custom_id="bet_minus_1")
    async def bet_minus_1(self, button, interaction: Interaction):
        self.bet = max(1, self.bet - 1)
        await self.update_bet_message(interaction)

    @ui.button(label="x10", style=ButtonStyle.secondary, row=1, custom_id="bet_mul_10")
    async def bet_mul_10(self, button, interaction: Interaction):
        balance = self.cog.economy.get_entry(self.user.id)[2]
        if self.bet < balance:
            self.bet = min(balance, self.bet * 10)
        await self.update_bet_message(interaction)

    @ui.button(label="+10", style=ButtonStyle.secondary, row=1, custom_id="bet_plus_10")
    async def bet_plus_10(self, button, interaction: Interaction):
        balance = self.cog.economy.get_entry(self.user.id)[2]
        if self.bet < balance:
            self.bet = min(balance, self.bet + 10)
        await self.update_bet_message(interaction)

    @ui.button(label="+1", style=ButtonStyle.secondary, row=1, custom_id="bet_plus_1")
    async def bet_plus_1(self, button, interaction: Interaction):
        balance = self.cog.economy.get_entry(self.user.id)[2]
        if self.bet < balance:
            self.bet = min(balance, self.bet + 1)
        await self.update_bet_message(interaction)

    @ui.button(label="Start", style=ButtonStyle.success, row=2, custom_id="bet_start")
    async def bet_start(self, button, interaction: Interaction):
        await self.cog.start_game(self, interaction)

    @ui.button(emoji="❌", style=ButtonStyle.danger, row=2, custom_id="close")
    async def close(self, button, interaction: Interaction):
        if self.game_message:
            await self.game_message.delete()
        if self.cog.active_games.get(self.user.id) is self:
            del self.cog.active_games[self.user.id]
        if self.bet_message:
            try:
                await self.bet_message.edit(view=None)
            except Exception:
                pass
        await interaction.response.send_message(
            "Game ended and thread closed.",
            ephemeral=True)
        try:
            await self.thread.edit(archived=True, locked=True)
        except Exception:
            pass

    async def update_bet_message(self, interaction):
        balance = self.cog.economy.get_entry(self.user.id)[2]
        embed = make_embed(
            title="Set your bet (credits)",
            description=f"Current bet: {self.bet} credits\nWallet: {balance} credits"
        )
        await interaction.response.edit_message(embed=embed, view=self)


class GameView(ui.View):
    def __init__(self, cog, user, bet, thread, betting_view):
        super().__init__(timeout=60)
        self.cog = cog
        self.user = user
        self.bet = bet
        self.thread = thread
        self.betting_view = betting_view
        self.game_message = None

    async def interaction_check(self, interaction: Interaction) -> bool:
        return interaction.user.id == self.user.id

    @ui.button(label="Play Again", style=ButtonStyle.success, custom_id="play_again")
    async def play_again(self, button, interaction: Interaction):
        await self.cog.start_game(self.betting_view, interaction)

    @ui.button(label="Back to Bet", style=ButtonStyle.secondary, custom_id="back_to_bet")
    async def back_to_bet(self, button, interaction: Interaction):
        if self.game_message:
            await self.game_message.delete()


class Slots(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.economy = Economy()
        self.active_games = {}

    @discord.slash_command(description="Play the slot machine. Bet must be 1-3 credits.", guild_ids=[629027778347532298])
    async def slots(self, interaction: discord.Interaction, bet: int = 1):
        await interaction.response.send_message("Game started! ✅", ephemeral=True)
        thread = await interaction.channel.create_thread(
            name=f"Slots - {interaction.user.display_name}",
            type=discord.ChannelType.public_thread
        )
        view = BettingView(self, interaction.user, bet, thread)
        balance = self.economy.get_entry(interaction.user.id)[2]
        embed = make_embed(
            title="Set your bet (credits)",
            description=f"Current bet: {bet} credits\nWallet: {balance} credits"
        )
        msg = await thread.send(embed=embed, view=view)
        view.bet_message = msg

    async def start_game(self, betting_view: BettingView, interaction: Interaction):
        # Subtract bet at game start
        self.economy.add_credits(betting_view.user.id, -betting_view.bet)
        # Update betting message to show new balance after bet is subtracted
        if betting_view.bet_message:
            balance = self.economy.get_entry(betting_view.user.id)[2]
            bet_embed = make_embed(
                title="Set your bet (credits)",
                description=f"Current bet: {betting_view.bet} credits\nWallet: {balance} credits"
            )
            await betting_view.bet_message.edit(embed=bet_embed, view=betting_view)
        # Delete old game message if it exists
        if betting_view.game_message:
            try:
                await betting_view.game_message.delete()
            except Exception:
                pass
        # Play slot game
        msg = await self.send_game_message(betting_view, betting_view.bet)
        betting_view.game_message = msg

    async def send_game_message(self, betting_view, bet):
        # Slot logic and image generation
        path = os.path.join(os.path.dirname(__file__), '..', 'modules')
        facade = Image.open(f'{path}/slot-face.png').convert('RGBA')
        reel = Image.open(f'{path}/slot-reel.png').convert('RGBA')
        rw, rh = reel.size
        item = 180
        items = rh // item
        s1 = random.randint(1, items-1)
        s2 = random.randint(1, items-1)
        s3 = random.randint(1, items-1)
        win_rate = 12/100
        if random.random() < win_rate:
            symbols_weights = [3.5, 7, 15, 25, 55]
            x = round(random.random()*100, 1)
            pos = bisect.bisect(symbols_weights, x)
            s1 = pos + (random.randint(1, int((items/6)-1)) * 6)
            s2 = pos + (random.randint(1, int((items/6)-1)) * 6)
            s3 = pos + (random.randint(1, int((items/6)-1)) * 6)
            s1 = s1 - 6 if s1 == items else s1
            s2 = s2 - 6 if s2 == items else s2
            s3 = s3 - 6 if s3 == items else s3
        images = []
        speed = 6
        for i in range(1, (item//speed)+1):
            bg = Image.new('RGBA', facade.size, color=(255,255,255))
            bg.paste(reel, (25 + rw*0, 100-(speed * i * s1)))
            bg.paste(reel, (25 + rw*1, 100-(speed * i * s2)))
            bg.paste(reel, (25 + rw*2, 100-(speed * i * s3)))
            bg.alpha_composite(facade)
            images.append(bg)
        fp = f'{betting_view.user.id}_slots.gif'
        images[0].save(
            fp,
            save_all=True,
            append_images=images[1:],
            duration=50
        )
        # win logic
        result = ('lost', bet)
        # (1+s1)%6 gets the symbol 0-5 inclusive
        if (1+s1)%6 == (1+s2)%6 == (1+s3)%6:
            symbol = (1+s1)%6
            reward = [4, 80, 40, 25, 10, 5][symbol] * bet
            result = ('won', reward)
            self.economy.add_credits(betting_view.user.id, reward)
        embed = make_embed(
            title=(
                f'You {result[0]} {result[1]} credits'+
                ('.' if result[0] == 'lost' else '!')
            ),
            description=(
                'You now have ' +
                f'**{self.economy.get_entry(betting_view.user.id)[2]}** ' +
                'credits.'
            ),
            color=(
                discord.Color.red() if result[0] == "lost"
                else discord.Color.green()
            )
        )
        file = discord.File(fp, filename=fp)
        embed.set_image(url=f"attachment://{fp}")
        view = GameView(self, betting_view.user, bet, betting_view.thread, betting_view)
        msg = await betting_view.thread.send(file=file, embed=embed, view=view)
        view.game_message = msg
        os.remove(fp)
        return msg

    @discord.slash_command(description=f"Purchase credits. Each credit is worth ${DEFAULT_BET}.", guild_ids=[629027778347532298])
    async def buyc(self, interaction: discord.Interaction, amount_to_buy: int):
        user_id = interaction.user.id
        profile = self.economy.get_entry(user_id)
        cost = amount_to_buy * DEFAULT_BET
        if profile[1] >= cost:
            self.economy.add_money(user_id, cost*-1)
            self.economy.add_credits(user_id, amount_to_buy)
        await interaction.response.send_message(f"Purchased {amount_to_buy} credits.", ephemeral=True)

    @discord.slash_command(description=f'Sell credits. Each credit is worth ${DEFAULT_BET}.', guild_ids=[629027778347532298])
    async def sellc(self, interaction: discord.Interaction, amount_to_sell: int):
        user_id = interaction.user.id
        profile = self.economy.get_entry(user_id)
        if profile[2] >= amount_to_sell:
            self.economy.add_credits(user_id, amount_to_sell*-1)
            self.economy.add_money(user_id, amount_to_sell*DEFAULT_BET)
        await interaction.response.send_message(f"Sold {amount_to_sell} credits.", ephemeral=True)

def setup(client: commands.Bot):
    client.add_cog(Slots(client))
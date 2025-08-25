import random
import nextcord as discord
from nextcord.ext import commands
from nextcord import ui, Interaction, ButtonStyle
from modules.economy import Economy
from modules.helpers import make_embed, DEFAULT_BET

class CoinFlipBettingView(ui.View):
    def __init__(self, cog, user, bet, thread):
        super().__init__(timeout=None)
        self.cog = cog
        self.user = user
        self.bet = bet
        self.thread = thread
        self.bet_message = None
        self.game_message = None

    def cap_bet(self, new_bet: int) -> int:
        balance = self.cog.economy.get_entry(self.user.id)[1]
        return max(1, min(new_bet, balance))

    @ui.button(label="/10", style=ButtonStyle.secondary, row=0, custom_id="bet_div_10")
    async def bet_div_10(self, button, interaction: Interaction):
        self.bet = self.cap_bet(self.bet // 10)
        await self.update_bet_message(interaction)

    @ui.button(label="-10", style=ButtonStyle.secondary, row=0, custom_id="bet_minus_10")
    async def bet_minus_10(self, button, interaction: Interaction):
        self.bet = self.cap_bet(self.bet - 10)
        await self.update_bet_message(interaction)

    @ui.button(label="-1", style=ButtonStyle.secondary, row=0, custom_id="bet_minus_1")
    async def bet_minus_1(self, button, interaction: Interaction):
        self.bet = self.cap_bet(self.bet - 1)
        await self.update_bet_message(interaction)

    @ui.button(label="x10", style=ButtonStyle.secondary, row=1, custom_id="bet_mul_10")
    async def bet_mul_10(self, button, interaction: Interaction):
        self.bet = self.cap_bet(self.bet * 10)
        await self.update_bet_message(interaction)

    @ui.button(label="+10", style=ButtonStyle.secondary, row=1, custom_id="bet_plus_10")
    async def bet_plus_10(self, button, interaction: Interaction):
        self.bet = self.cap_bet(self.bet + 10)
        await self.update_bet_message(interaction)

    @ui.button(label="+1", style=ButtonStyle.secondary, row=1, custom_id="bet_plus_1")
    async def bet_plus_1(self, button, interaction: Interaction):
        self.bet = self.cap_bet(self.bet + 1)
        await self.update_bet_message(interaction)

    @ui.button(label="Heads", style=ButtonStyle.primary, row=3, custom_id="coinflip_heads")
    async def choose_heads(self, button, interaction: Interaction):
        await self.cog.start_coinflip_game(self, interaction, user_choice="heads")

    @ui.button(label="Tails", style=ButtonStyle.primary, row=3, custom_id="coinflip_tails")
    async def choose_tails(self, button, interaction: Interaction):
        await self.cog.start_coinflip_game(self, interaction, user_choice="tails")

    @ui.button(emoji="❌", style=ButtonStyle.danger, row=3, custom_id="close")
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
        except Exception as e:
            print(f"[CoinFlip] Error sending game ended message: {e}")
        try:
            await self.thread.edit(archived=True, locked=True)
        except Exception:
            pass

    async def update_bet_message(self, interaction):
        balance = self.cog.economy.get_entry(self.user.id)[1]
        embed = make_embed(
            title="Set your bet ($)",
            description=f"Current bet: ${self.bet}\nWallet: ${balance}"
        )
        await interaction.response.edit_message(embed=embed, view=self)

class CoinFlipGameView(ui.View):
    def __init__(self, cog, user, bet, thread, betting_view, user_choice):
        super().__init__(timeout=60)
        self.cog = cog
        self.user = user
        self.bet = bet
        self.thread = thread
        self.betting_view = betting_view
        self.user_choice = user_choice
        self.game_message = None

    @ui.button(label="Play Again", style=ButtonStyle.success, custom_id="play_again")
    async def play_again(self, button, interaction: Interaction):
        await self.cog.start_coinflip_game(self.betting_view, interaction, user_choice=self.user_choice)

class CoinFlip(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.economy = Economy()
        self.active_games = {}  # {thread_id: BettingView}
        self.default_bet = DEFAULT_BET

    @discord.slash_command(
        name="coinflip",
        description="Flip a coin."
    )
    async def coinflip(self, interaction: discord.Interaction):
        if interaction.response.is_done():
            print("[CoinFlip] Coinflip interaction already responded to, aborting.")
            return
        try:
            await interaction.response.send_message("Game started! ✅", ephemeral=True)
        except Exception as e:
            print(f"[CoinFlip] Error sending game started: {e}")
            return
        thread = await interaction.channel.create_thread(
            name=f"Coin Flip - {interaction.user.display_name}",
            type=discord.ChannelType.public_thread
        )
        balance = self.economy.get_entry(interaction.user.id)[1]
        bet = min(self.default_bet, balance) if balance > 0 else 1
        view = CoinFlipBettingView(self, interaction.user, bet, thread)
        self.active_games[thread.id] = view
        embed = make_embed(
            title="Set your bet ($)",
            description=f"Current bet: ${bet}\nWallet: ${balance}"
        )
        msg = await thread.send(embed=embed, view=view)
        view.bet_message = msg

    async def start_coinflip_game(self, betting_view: CoinFlipBettingView, interaction: Interaction, user_choice: str):
        balance = self.economy.get_entry(betting_view.user.id)[1]
        if betting_view.bet > balance:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        f"You do not have enough money to place this bet! (You have ${balance}, bet is ${betting_view.bet})",
                        ephemeral=True
                    )
            except Exception as e:
                print(f"[CoinFlip] Error sending not enough money message: {e}")
            return
        self.economy.add_money(betting_view.user.id, -betting_view.bet)
        if betting_view.bet_message:
            balance = self.economy.get_entry(betting_view.user.id)[1]
            bet_embed = make_embed(
                title="Set your bet ($)",
                description=f"Current bet: ${betting_view.bet}\nWallet: ${balance}"
            )
            await betting_view.bet_message.edit(embed=bet_embed, view=betting_view)
        if betting_view.game_message:
            try:
                await betting_view.game_message.delete()
            except Exception:
                pass
        msg = await self.send_flip_message(betting_view, user_choice=user_choice)
        betting_view.game_message = msg

    async def send_flip_message(self, betting_view, user_choice):
        result = random.choice(["heads", "tails"])
        win = result == user_choice
        from modules.helpers import COINFLIP_MULT
        if win:
            self.economy.add_money(betting_view.user.id, betting_view.bet * COINFLIP_MULT)
        print(f"[CoinFlip] User: {betting_view.user} (ID: {betting_view.user.id}), Bet: ${betting_view.bet}, Result: {'win' if win else 'loss'}, Amount: {betting_view.bet*2 if win else -betting_view.bet}, Coin: {result}, User choice: {user_choice}")
        gif_path = f"modules/cf-{result}.gif"
        file = discord.File(gif_path, filename=f"cf-{result}.gif")
        embed = make_embed(
            title=f"Coin Flip: {result.capitalize()}",
            description=(
                f"You {'won' if win else 'lost'} ${betting_view.bet if not win else betting_view.bet*2}!\n"
                f"Result: {result.capitalize()}\nYour choice: {user_choice.capitalize()}\n"
                f"Wallet: ${self.economy.get_entry(betting_view.user.id)[1]}"
            ),
            color=(discord.Color.green() if win else discord.Color.red())
        )
        embed.set_image(url=f"attachment://cf-{result}.gif")
        view = CoinFlipGameView(self, betting_view.user, betting_view.bet, betting_view.thread, betting_view, user_choice)
        msg = await betting_view.thread.send(embed=embed, view=view, file=file)
        view.game_message = msg
        return msg

def setup(client):
    client.add_cog(CoinFlip(client))

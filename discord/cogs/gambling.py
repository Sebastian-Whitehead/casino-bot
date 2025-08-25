import random
import nextcord as discord
from nextcord.ext import commands
from nextcord import ui, Interaction, ButtonStyle
from modules.economy import Economy
from modules.helpers import InsufficientFundsException, make_embed

class BettingView(ui.View):
    def __init__(self, cog, user, bet, thread, game_type):
        super().__init__(timeout=None)
        self.cog = cog
        self.user = user
        self.bet = bet
        self.thread = thread
        self.game_type = game_type
        self.bet_message = None
        self.game_message = None

    def cap_bet(self, new_bet: int) -> int:
        """Cog-specific helper to cap bet to user balance, min 1."""
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

    @ui.button(label="Start", style=ButtonStyle.success, row=2, custom_id="bet_start")
    async def bet_start(self, button, interaction: Interaction):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
        except Exception as e:
            print(f"[Gambling] Error deferring interaction: {e}")
        await self.cog.start_game(self, interaction)

    @ui.button(emoji="❌", style=ButtonStyle.danger, row=2, custom_id="close")
    async def close(self, button, interaction: Interaction):
        if self.game_message:
            await self.game_message.delete()
        if self.cog.active_games.get(self.thread.id) is self:
            del self.cog.active_games[self.thread.id]
        if self.bet_message:
            try:
                await self.bet_message.edit(view=None)
            except Exception:
                pass
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Game ended and thread closed.",
                    ephemeral=True)
        except Exception as e:
            print(f"[Gambling] Error sending game ended message: {e}")
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

class GameView(ui.View):
    def __init__(self, cog, user, bet, thread, betting_view, game_type, extra=None):
        super().__init__(timeout=60)
        self.cog = cog
        self.user = user
        self.bet = bet
        self.thread = thread
        self.betting_view = betting_view
        self.game_type = game_type
        self.extra = extra
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

class Gambling(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        from modules.economy import Economy
        from modules.helpers import DEFAULT_BET
        self.economy = Economy()
        self.active_games = {}  # {thread_id: BettingView}
        self.default_bet = DEFAULT_BET
    async def end_game_by_thread(self, thread_id):
        view = self.active_games.pop(thread_id, None)
        if view:
            try:
                if view.game_message:
                    await view.game_message.delete()
            except Exception:
                pass
            try:
                if view.bet_message:
                    await view.bet_message.edit(view=None)
            except Exception:
                pass
            try:
                await view.thread.send("Game ended due to inactivity.")
            except Exception:
                pass
            try:
                await view.thread.edit(archived=True, locked=True)
            except Exception:
                pass

    TEST_GUILD_ID = 629027778347532298
    USE_TEST_GUILD = False  # Set to True for fast test registration

    @discord.slash_command(
        name="coinflip",
        description="Flip a coin. Bet must be greater than $0.",
        **({"guild_ids": [TEST_GUILD_ID]} if USE_TEST_GUILD else {})
    )
    async def coinflip(self, interaction: discord.Interaction, bet: int = None):
        if interaction.response.is_done():
            print("[Gambling] Coinflip interaction already responded to, aborting.")
            return
        try:
            await interaction.response.send_message("Game started! ✅", ephemeral=True)
        except Exception as e:
            print(f"[Gambling] Error sending game started: {e}")
            return
        thread = await interaction.channel.create_thread(
            name=f"Coin Flip - {interaction.user.display_name}",
            type=discord.ChannelType.public_thread
        )
        balance = self.economy.get_entry(interaction.user.id)[1]
        bet = bet if bet is not None else min(self.default_bet, balance) if balance > 0 else 1
        view = BettingView(self, interaction.user, bet, thread, game_type="flip")
        self.active_games[thread.id] = view
        embed = make_embed(
            title="Set your bet ($)",
            description=f"Current bet: ${bet}\nWallet: ${balance}"
        )
        msg = await thread.send(embed=embed, view=view)
        view.bet_message = msg

    @discord.slash_command(
        description="Roll a die. Bet must be greater than $0.",
        **({"guild_ids": [TEST_GUILD_ID]} if USE_TEST_GUILD else {})
    )
    async def roll(self, interaction: discord.Interaction, guess: int, bet: int = None):
        if interaction.response.is_done():
            print("[Gambling] Roll interaction already responded to, aborting.")
            return
        try:
            await interaction.response.send_message("Game started! ✅", ephemeral=True)
        except Exception as e:
            print(f"[Gambling] Error sending game started: {e}")
            return
        thread = await interaction.channel.create_thread(
            name=f"Dice Roll - {interaction.user.display_name}",
            type=discord.ChannelType.public_thread
        )
        balance = self.economy.get_entry(interaction.user.id)[1]
        bet = bet if bet is not None else min(self.default_bet, balance) if balance > 0 else 1
        view = BettingView(self, interaction.user, bet, thread, game_type="roll")
        self.active_games[thread.id] = view
        embed = make_embed(
            title="Set your bet ($)",
            description=f"Current bet: ${bet}\nWallet: ${balance}"
        )
        msg = await thread.send(embed=embed, view=view)
        view.bet_message = msg

    async def start_game(self, betting_view: BettingView, interaction: Interaction):
        # Check for sufficient funds before starting
        balance = self.economy.get_entry(betting_view.user.id)[1]
        if betting_view.bet > balance:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        f"You do not have enough money to place this bet! (You have ${balance}, bet is ${betting_view.bet})",
                        ephemeral=True
                    )
            except Exception as e:
                print(f"[Gambling] Error sending not enough money message: {e}")
            return
        # Subtract bet at game start
        self.economy.add_money(betting_view.user.id, -betting_view.bet)
        # Update betting message to show new balance after bet is subtracted
        if betting_view.bet_message:
            balance = self.economy.get_entry(betting_view.user.id)[1]
            bet_embed = make_embed(
                title="Set your bet ($)",
                description=f"Current bet: ${betting_view.bet}\nWallet: ${balance}"
            )
            await betting_view.bet_message.edit(embed=bet_embed, view=betting_view)
        # Delete old game message if it exists
        if betting_view.game_message:
            try:
                await betting_view.game_message.delete()
            except Exception:
                pass
        # Play game
        if betting_view.game_type == "flip":
            msg = await self.send_flip_message(betting_view)
        elif betting_view.game_type == "roll":
            msg = await self.send_roll_message(betting_view)
        betting_view.game_message = msg

    async def send_flip_message(self, betting_view):
        # Coin flip logic
        result = random.choice(["heads", "tails"])
        user_choice = random.choice(["heads", "tails"])
        win = result == user_choice
        if win:
            self.economy.add_money(betting_view.user.id, betting_view.bet * 2)
        # --- Game result logging ---
        print(f"[CoinFlip] User: {betting_view.user} (ID: {betting_view.user.id}), Bet: ${betting_view.bet}, Result: {'win' if win else 'loss'}, Amount: {betting_view.bet*2 if win else -betting_view.bet}, Coin: {result}, User choice: {user_choice}")
        embed = make_embed(
            title=f"Coin Flip: {result.capitalize()}",
            description=(
                f"You {'won' if win else 'lost'} ${betting_view.bet if not win else betting_view.bet*2}!\n"
                f"Result: {result.capitalize()}\nYour choice: {user_choice.capitalize()}\n"
                f"Wallet: ${self.economy.get_entry(betting_view.user.id)[1]}"
            ),
            color=(discord.Color.green() if win else discord.Color.red())
        )
        view = GameView(self, betting_view.user, betting_view.bet, betting_view.thread, betting_view, "flip", extra=user_choice)
        msg = await betting_view.thread.send(embed=embed, view=view)
        view.game_message = msg
        return msg

    async def send_roll_message(self, betting_view):
        # Dice roll logic
        guess = random.randint(1, 6)
        result = random.randint(1, 6)
        win = guess == result
        if win:
            self.economy.add_money(betting_view.user.id, betting_view.bet * 6)
        # --- Game result logging ---
        print(f"[DiceRoll] User: {betting_view.user} (ID: {betting_view.user.id}), Bet: ${betting_view.bet}, Result: {'win' if win else 'loss'}, Amount: {betting_view.bet*6 if win else -betting_view.bet}, Roll: {result}, User guess: {guess}")
        embed = make_embed(
            title=f"Dice Roll: {result}",
            description=(
                f"You {'won' if win else 'lost'} ${betting_view.bet if not win else betting_view.bet*6}!\n"
                f"Result: {result}\nYour guess: {guess}\n"
                f"Wallet: ${self.economy.get_entry(betting_view.user.id)[1]}"
            ),
            color=(discord.Color.green() if win else discord.Color.red())
        )
        view = GameView(self, betting_view.user, betting_view.bet, betting_view.thread, betting_view, "roll", extra=guess)
        msg = await betting_view.thread.send(embed=embed, view=view)
        view.game_message = msg
        return msg

def setup(client: commands.Bot):
    client.add_cog(Gambling(client))
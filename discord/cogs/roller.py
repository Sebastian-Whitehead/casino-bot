import random
import nextcord as discord
from nextcord.ext import commands
from nextcord import ui, Interaction, ButtonStyle
from modules.economy import Economy

from modules.helpers import make_embed, DEFAULT_BET

# --- TEST GUILD CONFIG FOR SLASH COMMANDS (local, like blackjack/slots) ---
TEST_GUILD_ID = 629027778347532298
USE_TEST_GUILD = True

class RollerBettingView(ui.View):
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


    @ui.button(label="Start", style=ButtonStyle.success, row=2, custom_id="start_game")
    async def start_game(self, button, interaction: Interaction):
        # Do not disable betting window, just show guessing embed
        await self.cog.show_guessing_embed(self, interaction)

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
        except Exception as e:
            print(f"[Roller] Error sending game ended message: {e}")
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

class RollerGameView(ui.View):
    def __init__(self, cog, user, bet, thread, betting_view, guess):
        super().__init__(timeout=60)
        self.cog = cog
        self.user = user
        self.bet = bet
        self.thread = thread
        self.betting_view = betting_view
        self.guess = guess
        self.game_message = None

    @ui.button(label="Play Again", style=ButtonStyle.success, custom_id="play_again")
    async def play_again(self, button, interaction: Interaction):
        await self.cog.start_roll_game(self.betting_view, interaction, guess=self.guess)

class Roller(commands.Cog):

    async def show_guessing_embed(self, betting_view, interaction):
        # Show embed with guess buttons 1-6
        class GuessView(ui.View):
            def __init__(self, parent_cog, betting_view):
                super().__init__(timeout=60)
                self.parent_cog = parent_cog
                self.betting_view = betting_view
            @ui.button(label="1", style=ButtonStyle.primary, row=0, custom_id="guess_1")
            async def guess_1(self, button, interaction: Interaction):
                await self.parent_cog.start_roll_game(self.betting_view, interaction, guess=1)
            @ui.button(label="2", style=ButtonStyle.primary, row=0, custom_id="guess_2")
            async def guess_2(self, button, interaction: Interaction):
                await self.parent_cog.start_roll_game(self.betting_view, interaction, guess=2)
            @ui.button(label="3", style=ButtonStyle.primary, row=0, custom_id="guess_3")
            async def guess_3(self, button, interaction: Interaction):
                await self.parent_cog.start_roll_game(self.betting_view, interaction, guess=3)
            @ui.button(label="4", style=ButtonStyle.primary, row=1, custom_id="guess_4")
            async def guess_4(self, button, interaction: Interaction):
                await self.parent_cog.start_roll_game(self.betting_view, interaction, guess=4)
            @ui.button(label="5", style=ButtonStyle.primary, row=1, custom_id="guess_5")
            async def guess_5(self, button, interaction: Interaction):
                await self.parent_cog.start_roll_game(self.betting_view, interaction, guess=5)
            @ui.button(label="6", style=ButtonStyle.primary, row=1, custom_id="guess_6")
            async def guess_6(self, button, interaction: Interaction):
                await self.parent_cog.start_roll_game(self.betting_view, interaction, guess=6)
            @ui.button(label="Cancel", style=ButtonStyle.danger, row=2, custom_id="cancel_guess")
            async def cancel_guess(self, button, interaction: Interaction):
                # Remove the guessing embed and go back to betting adjustment window
                if self.betting_view.game_message:
                    try:
                        await self.betting_view.game_message.delete()
                    except Exception:
                        pass
                # Optionally, send a message or just do nothing (betting window remains active)
                if not interaction.response.is_done():
                    await interaction.response.send_message("Returned to bet adjustment window.", ephemeral=True)
        embed = make_embed(
            title="Guess the Dice Roll (1-6)",
            description=f"Choose your guess for the dice outcome. Bet: ${betting_view.bet}"
        )
        msg = await betting_view.thread.send(embed=embed, view=GuessView(self, betting_view))
        betting_view.game_message = msg
    def __init__(self, client: commands.Bot):
        self.client = client
        self.economy = Economy()
        self.active_games = {}  # {thread_id: BettingView}
        self.default_bet = DEFAULT_BET

    @discord.slash_command(
        name="diceroll",
        description="Roll a die. Bet must be greater than $0.",
        **({"guild_ids": [TEST_GUILD_ID]} if USE_TEST_GUILD else {})
    )
    async def diceroll(self, interaction: discord.Interaction):
        if interaction.response.is_done():
            print("[Roller] Diceroll interaction already responded to, aborting.")
            return
        try:
            await interaction.response.send_message("Game started! ✅", ephemeral=True)
        except Exception as e:
            print(f"[Roller] Error sending game started: {e}")
            return
        thread = await interaction.channel.create_thread(
            name=f"Dice Roll - {interaction.user.display_name}",
            type=discord.ChannelType.public_thread
        )
        balance = self.economy.get_entry(interaction.user.id)[1]
        bet = min(self.default_bet, balance) if balance > 0 else 1
        view = RollerBettingView(self, interaction.user, bet, thread)
        self.active_games[thread.id] = view
        embed = make_embed(
            title="Set your bet ($)",
            description=f"Current bet: ${bet}\nWallet: ${balance}"
        )
        msg = await thread.send(embed=embed, view=view)
        view.bet_message = msg

    async def start_roll_game(self, betting_view: RollerBettingView, interaction: Interaction, guess: int):
        balance = self.economy.get_entry(betting_view.user.id)[1]
        if betting_view.bet > balance:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        f"You do not have enough money to place this bet! (You have ${balance}, bet is ${betting_view.bet})",
                        ephemeral=True
                    )
            except Exception as e:
                print(f"[Roller] Error sending not enough money message: {e}")
            return
        # Withdraw money only when a guess is made
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
        msg = await self.send_roll_message(betting_view, guess=guess)
        betting_view.game_message = msg

    async def send_roll_message(self, betting_view, guess):
        result = random.randint(1, 6)
        win = guess == result
        from modules.helpers import DICE_MULT
        if win:
            self.economy.add_money(betting_view.user.id, betting_view.bet * DICE_MULT)
        print(f"[DiceRoll] User: {betting_view.user} (ID: {betting_view.user.id}), Bet: ${betting_view.bet}, Result: {'win' if win else 'loss'}, Amount: {betting_view.bet*6 if win else -betting_view.bet}, Roll: {result}, User guess: {guess}")
        embed = make_embed(
            title=f"Dice Roll: {result}",
            description=(
                f"You {'won' if win else 'lost'} ${betting_view.bet if not win else betting_view.bet*6}!\n"
                f"Your guess: {guess}\n"
                f"Wallet: ${self.economy.get_entry(betting_view.user.id)[1]}"
            ),
            color=(discord.Color.green() if win else discord.Color.red())
        )
        view = RollerGameView(self, betting_view.user, betting_view.bet, betting_view.thread, betting_view, guess)
        msg = await betting_view.thread.send(embed=embed, view=view)
        view.game_message = msg
        return msg

def setup(client):
    client.add_cog(Roller(client))

import random
import nextcord as discord
from nextcord.ext import commands
from nextcord import ui, Interaction, ButtonStyle
from modules.economy import Economy

from modules.helpers import make_embed, DEFAULT_BET
from modules.base_betting_view import BaseBettingView
from modules.challenge import ChallengeGameCog

# --- TEST GUILD CONFIG FOR SLASH COMMANDS (local, like blackjack/slots) ---
from modules.helpers import TEST_GUILD_ID
USE_TEST_GUILD = True


class RollerBettingView(BaseBettingView):
    bet_title = "Set your bet ($)"

    def __init__(self, cog, user, bet, thread):
        super().__init__(cog, user, bet, thread)
        inherited_close = next(
            (item for item in self.children if item.custom_id == "close"),
            None
        )
        if inherited_close:
            self.remove_item(inherited_close)

    @ui.button(label="Start", style=ButtonStyle.success, row=2, custom_id="start_game")
    async def start_game(self, button, interaction: Interaction):
        # Do not disable betting window, just show guessing embed
        await self.cog.show_guessing_embed(self, interaction)

    @ui.button(emoji="❌", style=ButtonStyle.danger, row=2, custom_id="roller_close")
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

class RollerGameView(ui.View):
    async def interaction_check(self, interaction: Interaction) -> bool:
        return interaction.user.id == self.user.id
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

class Roller(ChallengeGameCog, commands.Cog):

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
        description="Roll a die or challenge another user.",
        **({"guild_ids": [TEST_GUILD_ID]} if USE_TEST_GUILD else {})
    )
    async def diceroll(
        self,
        interaction: discord.Interaction,
        opponent: discord.Member = None,
        bet: int = None
    ):
        from modules.helpers import CASINO_CHANNEL_ID, RESTRICT_TO_CASINO_CHANNEL
        if RESTRICT_TO_CASINO_CHANNEL and interaction.channel.id != CASINO_CHANNEL_ID:
            await interaction.response.send_message("This command can only be used in the designated casino channel.", ephemeral=True)
            return
        if opponent is not None or bet is not None:
            if opponent is None or bet is None:
                await interaction.response.send_message(
                    "Provide both an opponent and a bet to create a challenge.",
                    ephemeral=True
                )
                return
            await self.open_challenge(interaction, opponent, bet, "Dice Roll")
            return
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
        embed = view.bet_embed()
        msg = await thread.send(embed=embed, view=view)
        view.bet_message = msg

    async def start_roll_game(self, betting_view: RollerBettingView, interaction: Interaction, guess: int):
        ready = await self.prepare_bet_round(
            betting_view,
            interaction,
            "You do not have enough money to place this bet! (You have ${balance}, bet is ${bet})"
        )
        if not ready:
            return
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
        await betting_view.refresh_bet_message()
        return msg

    async def resolve_challenge(self, challenge):
        challenger_roll = random.randint(1, 6)
        opponent_roll = random.randint(1, 6)
        if challenger_roll == opponent_roll:
            self.refund_challenge(challenge)
            embed = make_embed(
                title="Dice Roll: Tie",
                description=(
                    f"Both players rolled **{challenger_roll}**.\n"
                    f"Both ${challenge.bet} bets were refunded."
                ),
                color=discord.Color.blue()
            )
        else:
            winner = (
                challenge.challenger
                if challenger_roll > opponent_roll
                else challenge.opponent
            )
            loser = (
                challenge.opponent
                if winner.id == challenge.challenger.id
                else challenge.challenger
            )
            winner_roll = (
                challenger_roll
                if winner.id == challenge.challenger.id
                else opponent_roll
            )
            loser_roll = (
                opponent_roll
                if winner.id == challenge.challenger.id
                else challenger_roll
            )
            payout, fee = self.settle_challenge(winner.id, challenge.bet)
            fee_text = f"\nCasino fee: ${fee}" if fee else ""
            embed = make_embed(
                title="Dice Roll Challenge",
                description=(
                    f"{winner.mention} wins against {loser.mention}!\n"
                    f"Winner rolled **{winner_roll}**; loser rolled **{loser_roll}**.\n"
                    f"Payout: ${payout}{fee_text}"
                ),
                color=discord.Color.green()
            )
        await challenge.thread.send(embed=embed)

def setup(client):
    client.add_cog(Roller(client))

import random
import nextcord as discord
from nextcord.ext import commands
from nextcord import ui, Interaction, ButtonStyle
from modules.economy import Economy

from modules.helpers import make_embed, DEFAULT_BET, DICE_MULT, payout
from modules.base_betting_view import BaseBettingView
from modules.base_game_cog import Outcome
from modules.challenge import ChallengeGameCog
from modules.game_ui import format_chips, safe_send

# --- TEST GUILD CONFIG FOR SLASH COMMANDS (local, like blackjack/slots) ---
from modules.helpers import TEST_GUILD_ID
USE_TEST_GUILD = True


class RollerBettingView(BaseBettingView):
    """Bet buttons plus the 1-6 guess buttons (rows 3-4); the inherited close button cancels."""

    def __init__(self, cog, user, bet, thread):
        super().__init__(cog, user, bet, thread)
        for n in range(1, 7):
            button = ui.Button(label=str(n), style=ButtonStyle.primary,
                               row=3 if n <= 5 else 4, custom_id=f"dice_guess_{n}")
            button.callback = self._guess_callback(n)
            self.add_item(button)

    def _guess_callback(self, n):
        async def callback(interaction: Interaction):
            await self.cog.start_round(self, interaction, guess=n)
        return callback


class Roller(ChallengeGameCog, commands.Cog):
    game_name = "Dice Roll"

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
        if opponent is not None or bet is not None:
            if opponent is None or bet is None:
                await interaction.response.send_message(
                    "Provide both an opponent and a bet to create a challenge.",
                    ephemeral=True
                )
                return
            await self.open_challenge(interaction, opponent, bet, self.game_name)
            return
        await self.open_game(interaction, RollerBettingView)

    async def play(self, betting_view, interaction, guess):
        result = random.randint(1, 6)
        win = guess == result
        return Outcome(
            won=win,
            payout=payout(betting_view.bet, DICE_MULT) if win else 0,
            title=f"Dice Roll: {result}",
            description=f"Your guess: {guess}",
        )

    async def resolve_challenge(self, challenge):
        challenger_roll = random.randint(1, 6)
        opponent_roll = random.randint(1, 6)
        if challenger_roll == opponent_roll:
            self.refund_challenge(challenge)
            embed = make_embed(
                title="Dice Roll: Tie",
                description=(
                    f"Both players rolled **{challenger_roll}**.\n"
                    f"Both {format_chips(challenge.bet)} bets were refunded."
                ),
                color=discord.Color.blue()
            )
        else:
            challenger_wins = challenger_roll > opponent_roll
            winner, loser = ((challenge.challenger, challenge.opponent) if challenger_wins
                             else (challenge.opponent, challenge.challenger))
            winner_roll, loser_roll = ((challenger_roll, opponent_roll) if challenger_wins
                                       else (opponent_roll, challenger_roll))
            won, fee = self.settle_challenge(winner.id, challenge.bet)
            fee_text = f"\nCasino fee: {format_chips(fee)}" if fee else ""
            embed = make_embed(
                title="Dice Roll Challenge",
                description=(
                    f"{winner.mention} wins against {loser.mention}!\n"
                    f"Winner rolled **{winner_roll}**; loser rolled **{loser_roll}**.\n"
                    f"Payout: {format_chips(won)}{fee_text}"
                ),
                color=discord.Color.green()
            )
        await safe_send(challenge.thread, embed=embed)


def setup(client):
    client.add_cog(Roller(client))

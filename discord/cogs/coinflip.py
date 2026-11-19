import random
import nextcord as discord
from nextcord.ext import commands
from nextcord import ui, Interaction, ButtonStyle
from modules.economy import Economy
from modules.helpers import (DEFAULT_BET, COINFLIP_MULT,
                             COINFLIP_MIN_BET, payout)
from modules.base_betting_view import BaseBettingView
from modules.base_game_cog import Outcome
from modules.challenge import ChallengeGameCog
from modules.embed_processor import member_replacements, render_embed
from modules.game_ui import format_chips, safe_send


class CoinFlipBettingView(BaseBettingView):
    min_bet = COINFLIP_MIN_BET

    @ui.button(label="Heads", style=ButtonStyle.primary, row=3, custom_id="coinflip_heads")
    async def choose_heads(self, button, interaction: Interaction):
        await self.cog.start_round(self, interaction, user_choice="heads")

    @ui.button(label="Tails", style=ButtonStyle.primary, row=3, custom_id="coinflip_tails")
    async def choose_tails(self, button, interaction: Interaction):
        await self.cog.start_round(self, interaction, user_choice="tails")


class CoinFlip(ChallengeGameCog, commands.Cog):
    game_name = "Coin Flip"
    challenge_min_bet = COINFLIP_MIN_BET

    def __init__(self, client: commands.Bot):
        self.client = client
        self.economy = Economy()
        self.active_games = {}  # {thread_id: BettingView}
        self.default_bet = DEFAULT_BET

    @discord.slash_command(
        name="coinflip",
        description="Flip a coin or challenge another user."
    )
    async def coinflip(
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
        await self.open_game(interaction, CoinFlipBettingView)

    @discord.slash_command(
        name="cf-challenge",
        description="Challenge another user to a coin flip for chips."
    )
    async def cf_challenge(
        self,
        interaction: discord.Interaction,
        opponent: discord.Member = discord.SlashOption(description="Who to challenge"),
        bet: int = discord.SlashOption(description="Chips each player bets"),
    ):
        await self.open_challenge(interaction, opponent, bet, self.game_name)

    async def play(self, betting_view, interaction, user_choice):
        result = random.choice(["heads", "tails"])
        win = result == user_choice
        file = discord.File(f"modules/cf-{result}.gif", filename=f"cf-{result}.gif")
        return Outcome(
            won=win,
            payout=payout(betting_view.bet, COINFLIP_MULT) if win else 0,
            title=f"Coin Flip: {result.capitalize()}",
            description=f"Your choice: {user_choice.capitalize()}",
            file=file,
        )

    async def resolve_challenge(self, challenge):
        result = random.choice(["heads", "tails"])
        winner = challenge.challenger if result == "heads" else challenge.opponent
        loser = challenge.opponent if winner.id == challenge.challenger.id else challenge.challenger
        won, fee = self.settle_challenge(challenge, winner, loser)
        fee_text = f"\nCasino fee: {format_chips(fee)}" if fee else ""
        replacements = challenge.replacements(
            **{"{result}": result.capitalize(), "{payout}": format_chips(won), "{fee_line}": fee_text},
            **member_replacements(winner, "winner"), **member_replacements(loser, "loser"))
        await safe_send(challenge.thread, **render_embed("coinflip_challenge_result", replacements))


def setup(client):
    client.add_cog(CoinFlip(client))

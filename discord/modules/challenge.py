import math
import nextcord as discord
from nextcord import ui, ButtonStyle
from modules.helpers import (
    CHALLENGE_FEE_ENABLED,
    CHALLENGE_FEE_PERCENT,
    InsufficientFundsException,
    make_embed,
)
from modules.base_game_cog import BaseGameCog
from modules.game_ui import format_chips, safe_send


class ChallengeView(ui.View):
    def __init__(self, cog, challenger, opponent, bet, thread, game_name):
        super().__init__(timeout=120)
        self.cog = cog
        self.challenger = challenger
        self.opponent = opponent
        self.bet = bet
        self.thread = thread
        self.game_name = game_name
        self.challenge_message = None
        self.resolved = False

    async def interaction_check(self, interaction):
        if interaction.user.id not in (self.challenger.id, self.opponent.id):
            await interaction.response.send_message(
                "Only the challenged players can respond to this challenge.",
                ephemeral=True
            )
            return False
        return True

    @ui.button(
        label="Accept",
        style=ButtonStyle.success,
        custom_id="challenge_accept",
    )
    async def accept(self, button, interaction):
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message(
                "Only the challenged user can accept this challenge.",
                ephemeral=True
            )
            return
        await self.cog.accept_challenge(self, interaction)

    @ui.button(
        label="Decline",
        style=ButtonStyle.danger,
        custom_id="challenge_decline",
    )
    async def decline(self, button, interaction):
        if self.resolved:
            return
        self.resolved = True
        await interaction.response.edit_message(
            content="Challenge declined.",
            embed=None,
            view=None
        )


class ChallengeGameCog(BaseGameCog):
    challenge_min_bet = 1  # per-game override

    async def open_challenge(self, interaction, opponent, bet, game_name):
        async def reject(message):
            await interaction.response.send_message(message, ephemeral=True)
            return None

        if opponent.id == interaction.user.id:
            return await reject("You cannot challenge yourself.")
        if opponent.bot:
            return await reject("You cannot challenge a bot.")
        if type(bet) is not int or bet < self.challenge_min_bet:
            return await reject(
                f"The bet must be at least {format_chips(self.challenge_min_bet)}.")
        if self.economy.get_chips(interaction.user.id) < bet:
            return await reject(
                f"You need {format_chips(bet)} to create this challenge. "
                "Use /cashier or /buy to get more.")

        await interaction.response.send_message(
            f"{game_name} challenge created!", ephemeral=True
        )
        thread = await interaction.channel.create_thread(
            name=(
                f"{game_name} - {interaction.user.display_name} "
                f"vs {opponent.display_name}"
            ),
            type=discord.ChannelType.public_thread
        )
        challenge = ChallengeView(
            self, interaction.user, opponent, bet, thread, game_name
        )
        embed = make_embed(
            title=f"{game_name} Challenge",
            description=(
                f"{interaction.user.mention} challenged {opponent.mention}.\n"
                f"Each player bets **{format_chips(bet)}**.\n"
                "The challenged player must accept or decline."
            )
        )
        challenge.challenge_message = await safe_send(thread, embed=embed, view=challenge)
        return challenge

    async def accept_challenge(self, challenge, interaction):
        if challenge.resolved:
            return
        challenge.resolved = True
        staked = []
        try:
            for player in (challenge.challenger, challenge.opponent):
                self.economy.place_bet(player.id, challenge.bet)
                staked.append(player)
        except InsufficientFundsException:
            for player in staked:  # undo the first stake
                self.economy.pay_out(player.id, challenge.bet)
            await interaction.response.edit_message(
                content="Challenge cancelled because a player no longer has enough chips.",
                embed=None,
                view=None
            )
            return
        await interaction.response.edit_message(
            content="Challenge accepted. Rolling now...",
            embed=None,
            view=None
        )
        await self.resolve_challenge(challenge)

    def settle_challenge(self, winner_id, bet):
        """Pay the winner the pot minus a floored fee; the fee stays with the casino."""
        pot = bet * 2
        fee = (
            math.floor(pot * CHALLENGE_FEE_PERCENT / 100)
            if CHALLENGE_FEE_ENABLED
            else 0
        )
        payout = pot - fee
        if payout > 0:
            self.economy.pay_out(winner_id, payout)
        return payout, fee

    def refund_challenge(self, challenge):
        self.economy.pay_out(challenge.challenger.id, challenge.bet)
        self.economy.pay_out(challenge.opponent.id, challenge.bet)

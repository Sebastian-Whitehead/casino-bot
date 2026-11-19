import nextcord as discord
from nextcord import ui, ButtonStyle
from modules.helpers import (
    CHALLENGE_FEE_ENABLED,
    CHALLENGE_FEE_PERCENT,
    make_embed,
)
from modules.base_game_cog import BettingGameCog


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


class ChallengeGameCog(BettingGameCog):
    async def open_challenge(self, interaction, opponent, bet, game_name):
        if opponent.id == interaction.user.id:
            await interaction.response.send_message(
                "You cannot challenge yourself.", ephemeral=True
            )
            return None
        if opponent.bot:
            await interaction.response.send_message(
                "You cannot challenge a bot.", ephemeral=True
            )
            return None
        if bet <= 0:
            await interaction.response.send_message(
                "The bet must be greater than $0.", ephemeral=True
            )
            return None
        if self.economy.get_entry(interaction.user.id)[1] < bet:
            await interaction.response.send_message(
                f"You need ${bet} to create this challenge.", ephemeral=True
            )
            return None

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
                f"Each player bets **${bet}**.\n"
                "The challenged player must accept or decline."
            )
        )
        challenge.challenge_message = await thread.send(embed=embed, view=challenge)
        return challenge

    async def accept_challenge(self, challenge, interaction):
        if challenge.resolved:
            return
        challenger_balance = self.economy.get_entry(challenge.challenger.id)[1]
        opponent_balance = self.economy.get_entry(challenge.opponent.id)[1]
        if min(challenger_balance, opponent_balance) < challenge.bet:
            challenge.resolved = True
            await interaction.response.edit_message(
                content="Challenge cancelled because a player no longer has enough money.",
                embed=None,
                view=None
            )
            return

        challenge.resolved = True
        self.economy.add_money(challenge.challenger.id, -challenge.bet)
        self.economy.add_money(challenge.opponent.id, -challenge.bet)
        await interaction.response.edit_message(
            content="Challenge accepted. Rolling now...",
            embed=None,
            view=None
        )
        await self.resolve_challenge(challenge)

    def settle_challenge(self, winner_id, bet):
        pot = bet * 2
        fee = (
            int(pot * CHALLENGE_FEE_PERCENT / 100)
            if CHALLENGE_FEE_ENABLED
            else 0
        )
        payout = pot - fee
        self.economy.add_money(winner_id, payout)
        return payout, fee

    def refund_challenge(self, challenge):
        self.economy.add_money(challenge.challenger.id, challenge.bet)
        self.economy.add_money(challenge.opponent.id, challenge.bet)

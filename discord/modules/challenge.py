import math
import nextcord as discord
from nextcord import ui, ButtonStyle
from modules.helpers import (
    CHALLENGE_FEE_ENABLED,
    CHALLENGE_FEE_PERCENT,
    InsufficientFundsException,
)
from modules.base_game_cog import BaseGameCog, new_game_id
from modules.embed_processor import member_replacements, render_embed
from modules.game_ui import ensure_casino_channel, format_chips, safe_edit, safe_send


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
        self.game_id = None  # shared by both players' wagers once accepted

    def replacements(self, **extra):
        """Placeholders shared by every challenge embed ({game} {bet} {challenger} {opponent} + names/ids)."""
        return {
            "{game}": self.game_name,
            "{bet}": format_chips(self.bet),
            **member_replacements(self.challenger, "challenger"),
            **member_replacements(self.opponent, "opponent"),
            **extra,
        }

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
            **render_embed("challenge_declined", self.replacements(**member_replacements(interaction.user))),
            view=None
        )
        self.stop()

    async def on_timeout(self):
        if self.resolved or not self.challenge_message:
            return
        self.resolved = True
        await safe_edit(self.challenge_message, view=None,
                        **render_embed("challenge_expired", self.replacements()))


class RematchView(ui.View):
    """Under a finished challenge: either player starts a new one, presser as challenger, same bet."""

    def __init__(self, cog, challenge):
        super().__init__(timeout=600)
        self.cog = cog
        self.challenge = challenge

    async def interaction_check(self, interaction):
        return interaction.user.id in (self.challenge.challenger.id, self.challenge.opponent.id)

    @ui.button(label="Rematch", style=ButtonStyle.primary, custom_id="challenge_rematch")
    async def rematch(self, button, interaction):
        c = self.challenge
        other = c.opponent if interaction.user.id == c.challenger.id else c.challenger
        started = await self.cog.open_challenge(interaction, other, c.bet, c.game_name,
                                                channel=c.thread.parent)
        if started:  # one rematch per result
            await safe_edit(interaction.message, view=None)
            self.stop()


class ChallengeGameCog(BaseGameCog):
    challenge_min_bet = 1  # per-game override

    async def open_challenge(self, interaction, opponent, bet, game_name, channel=None):
        """`channel`: where to create the thread (a rematch runs inside the old thread, so it passes the parent)."""
        async def reject(message):
            await interaction.response.send_message(message, ephemeral=True)
            return None

        if channel is None and not await ensure_casino_channel(interaction):
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
        thread = await (channel or interaction.channel).create_thread(
            name=(
                f"{game_name} - {interaction.user.display_name} "
                f"vs {opponent.display_name}"
            ),
            type=discord.ChannelType.public_thread
        )
        challenge = ChallengeView(
            self, interaction.user, opponent, bet, thread, game_name
        )
        # the file's "content" pings the opponent; mentions inside an embed do not notify
        challenge.challenge_message = await safe_send(
            thread, view=challenge, **render_embed("challenge", challenge.replacements()))
        return challenge

    async def challenge_or_play(self, interaction, opponent, bet, view_cls):
        """Shared /coinflip and /diceroll entry: both opponent and bet -> challenge, neither -> solo game."""
        if opponent is None and bet is None:
            return await self.open_game(interaction, view_cls)
        if opponent is None or bet is None:
            return await interaction.response.send_message(
                "Provide both an opponent and a bet to create a challenge.", ephemeral=True)
        return await self.open_challenge(interaction, opponent, bet, self.game_name)

    async def finish_challenge(self, challenge, winner, loser, embed_name, **extra):
        """Settle with the fee and post the result embed ({payout} {fee_line} winner_/loser_ names added)."""
        won, fee = self.settle_challenge(challenge, winner, loser)
        fee_line = f"\nCasino fee: {format_chips(fee)}" if fee else ""
        replacements = challenge.replacements(
            **{"{payout}": format_chips(won), "{fee_line}": fee_line}, **extra,
            **member_replacements(winner, "winner"), **member_replacements(loser, "loser"))
        await self.post_result(challenge, render_embed(embed_name, replacements))

    async def post_result(self, challenge, message):
        """Result embed with a Rematch button."""
        await safe_send(challenge.thread, view=RematchView(self, challenge), **message)

    async def accept_challenge(self, challenge, interaction):
        if challenge.resolved:
            return
        challenge.resolved = True
        challenge.game_id = game_id = new_game_id()
        staked = []
        try:
            for player in (challenge.challenger, challenge.opponent):
                self.economy.open_wager(game_id, player.id, challenge.game_name, challenge.bet)
                staked.append(player)
        except InsufficientFundsException:
            for player in staked:  # undo the first stake
                self.economy.refund_wager(game_id, player.id)
            await interaction.response.edit_message(
                **render_embed("challenge_cancelled", challenge.replacements()), view=None
            )
            return
        await interaction.response.edit_message(
            **render_embed("challenge_accepted", challenge.replacements()), view=None
        )
        try:
            await self.resolve_challenge(challenge)
        except BaseException:  # never leave either stake with the casino
            self.refund_challenge(challenge)
            raise

    def settle_challenge(self, challenge, winner, loser):
        """Winner gets the pot minus a floored fee (the fee stays with the casino); the loser's wager closes at 0."""
        pot = challenge.bet * 2
        fee = (
            math.floor(pot * CHALLENGE_FEE_PERCENT / 100)
            if CHALLENGE_FEE_ENABLED
            else 0
        )
        payout = pot - fee
        self.economy.settle_game(challenge.game_id, {winner.id: payout, loser.id: 0})
        return payout, fee

    def tie_challenge(self, challenge):
        """A tie is a resolution (logged as a push): both stakes go back."""
        self.economy.settle_game(challenge.game_id,
                                 {challenge.challenger.id: challenge.bet, challenge.opponent.id: challenge.bet})

    def refund_challenge(self, challenge):
        """Cancel after a failure: stakes go back and nothing is logged as a game."""
        for player in (challenge.challenger, challenge.opponent):
            self.economy.refund_wager(challenge.game_id, player.id)

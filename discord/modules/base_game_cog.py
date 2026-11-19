from dataclasses import dataclass
from typing import Any, Optional

import uuid

import nextcord
from nextcord import ButtonStyle, ui
from modules.game_ui import (GameResultView, build_result_embed, ensure_casino_channel,
                             format_chips, safe_edit, safe_send)

DEFAULT_INSUFFICIENT = ("You don't have enough chips for this bet "
                        "(you have {balance}, bet is {bet}). Use /cashier or /buy to get more.")


@dataclass
class Outcome:
    won: bool
    payout: int  # chips returned including the stake; 0 on a loss
    title: str
    description: Optional[str] = None
    file: Any = None
    view_cls: Any = None  # defaults to GameResultView; called as view_cls(cog, betting_view, replay_kwargs)


class ConfirmWagerView(ui.View):
    """Step 2: ephemeral Confirm / Cancel. `result` is True only after Confirm; `interaction` is the button press."""

    def __init__(self, user, timeout=30):
        super().__init__(timeout=timeout)
        self.user = user
        self.result = False
        self.interaction = None
        self.prompt = None  # the interaction that opened the prompt, to edit it on timeout

    async def interaction_check(self, interaction) -> bool:
        return interaction.user.id == self.user.id

    async def _close(self, interaction, text, result):
        self.result = result
        self.interaction = interaction
        await interaction.response.edit_message(content=text, embeds=[], view=None)
        self.stop()

    @ui.button(label="Confirm", style=ButtonStyle.success, custom_id="wager_confirm")
    async def confirm(self, button, interaction):
        await self._close(interaction, "Bet confirmed.", True)

    @ui.button(label="Cancel", style=ButtonStyle.secondary, custom_id="wager_cancel")
    async def cancel(self, button, interaction):
        await self._close(interaction, "Bet cancelled. No chips were taken.", False)

    async def on_timeout(self):
        try:
            await self.prompt.edit_original_message(content="Bet timed out. No chips were taken.", embeds=[], view=None)
        except Exception:
            pass


def new_game_id() -> str:
    return uuid.uuid4().hex[:8]


class BettingGameCog:
    """The one wager lifecycle every game uses:
    1 validate_wager  - enough chips / minimum bet
    2 confirm_wager   - player confirms (skipped for Play Again and auto-spin)
    3 open_wager      - chips withdrawn under a game id (Economy.open_wager)
    4 the game decides win or lose (play() or the game's own flow)
    5 settle          - payout into the player's chips (Economy.settle_wager, once per game id)
    A game that fails or is abandoned between 3 and 5 gets its stake back via Economy.refund_wager."""

    def describe_choice(self, choice) -> str:
        """Text for the confirmation prompt, e.g. 'Heads'. Games may override."""
        return ", ".join(str(v).capitalize() for v in choice.values())

    async def _tell(self, interaction, text):
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(text, ephemeral=True)
            else:
                await interaction.followup.send(text, ephemeral=True)
        except Exception as e:
            print(f"[{self.__class__.__name__}] Error sending bet message: {e}")

    async def validate_wager(self, betting_view, interaction, insufficient_message=DEFAULT_INSUFFICIENT) -> bool:
        """Step 1."""
        balance = betting_view.get_balance()
        error = None
        if betting_view.bet < betting_view.min_bet:
            error = f"The minimum bet is {format_chips(betting_view.min_bet)}."
        elif betting_view.bet > balance:
            error = insufficient_message.format(balance=format_chips(balance), bet=format_chips(betting_view.bet))
        if error:
            if not interaction.response.is_done():  # an auto-spin stub is already "done": stay silent
                await self._tell(interaction, error)
            return False
        return True

    async def confirm_wager(self, betting_view, interaction, choice):
        """Step 2. Returns the interaction to carry on with (the Confirm press), or None if cancelled / timed out."""
        from modules.embed_processor import member_replacements, render_embed
        choice_text = self.describe_choice(choice)
        message = render_embed("bet_confirm", {
            "{game}": self.game_name, "{bet}": format_chips(betting_view.bet),
            "{choice_line}": f" on {choice_text}" if choice_text else "",
            "{wallet}": format_chips(betting_view.get_balance()),
            **member_replacements(betting_view.user)})
        view = ConfirmWagerView(betting_view.user)
        view.prompt = interaction
        await interaction.response.send_message(**message, view=view, ephemeral=True)
        await view.wait()
        return view.interaction if view.result else None

    async def begin_wager(self, betting_view, interaction, choice=None, confirmed=False):
        """Steps 1-3. Returns (game_id, interaction) with the stake already withdrawn, or None."""
        from modules.helpers import CONFIRM_BETS, InsufficientFundsException
        if not await self.validate_wager(betting_view, interaction):
            return None
        if CONFIRM_BETS and not confirmed:
            bet = betting_view.bet  # the bet buttons stay live while the prompt is open
            interaction = await self.confirm_wager(betting_view, interaction, choice or {})
            if interaction is None:
                return None
            betting_view.bet = bet  # withdraw exactly what the player confirmed
        game_id = new_game_id()
        try:
            self.economy.open_wager(game_id, betting_view.user.id, self.game_name, betting_view.bet)
        except InsufficientFundsException:  # balance changed since step 1
            await self._tell(interaction, DEFAULT_INSUFFICIENT.format(
                balance=format_chips(betting_view.get_balance()), bet=format_chips(betting_view.bet)))
            return None
        betting_view.game_id = game_id
        await betting_view.refresh_bet_message()
        if betting_view.game_message:
            try:
                await betting_view.game_message.delete()
            except Exception:
                pass
        return game_id, interaction


class BaseGameCog(BettingGameCog):
    """Subclass sets `economy`, `active_games`, `default_bet`, `game_name` and implements `play`."""
    game_name = "Game"
    default_bet = 1

    async def open_game(self, interaction, view_cls, thread_name=None, default_bet=None):
        if not await ensure_casino_channel(interaction):
            return None
        try:
            await interaction.response.send_message("Game started!", ephemeral=True)
        except Exception as e:
            print(f"[{self.game_name}] Error sending game started: {e}")
            return None
        thread = await interaction.channel.create_thread(
            name=thread_name or f"{self.game_name} - {interaction.user.display_name}",
            type=nextcord.ChannelType.public_thread)
        chips = self.economy.get_chips(interaction.user.id)
        start = self.default_bet if default_bet is None else default_bet
        bet = max(view_cls.min_bet, min(start, chips))
        view = view_cls(self, interaction.user, bet, thread)
        self.active_games[thread.id] = view
        view.bet_message = await safe_send(thread, embed=view.bet_embed(), view=view)
        return view

    async def play(self, betting_view, interaction, **choice) -> Outcome:
        raise NotImplementedError

    async def start_round(self, betting_view, interaction, confirmed=False, **choice):
        """Steps 1-5 for single-step games. Choice buttons call this; Play Again passes confirmed=True."""
        started = await self.begin_wager(betting_view, interaction, choice, confirmed)
        if started is None:
            return
        game_id, interaction = started
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
            outcome = await self.play(betting_view, interaction, **choice)  # step 4
        except BaseException:  # includes cancellation: the stake must never stay with the casino
            self.economy.refund_wager(game_id, betting_view.user.id)
            raise
        await self.settle(betting_view, outcome, choice, game_id)

    async def settle(self, view, outcome: Outcome, replay_kwargs=None, game_id=None):
        """Step 5. Pays once per game id; a repeated settle for the same game does nothing."""
        game_id = game_id or view.game_id
        user_id = view.user.id
        if not self.economy.settle_game(game_id, {user_id: outcome.payout}):  # also writes game_log
            return
        net = outcome.payout - view.bet
        wallet = self.economy.get_chips(user_id)
        print(f"[{self.game_name}] Game: {game_id}, User: {view.user} (ID: {user_id}), Bet: {view.bet}, "
              f"Result: {'win' if outcome.won else 'loss/push'}, Payout: {outcome.payout}, "
              f"Net: {net}, Wallet: {wallet}")
        embed = build_result_embed(outcome.title, outcome.won, net, wallet, outcome.description)
        embed.set_footer(text=f"Game {game_id}")
        kw = {"embed": embed, "view": (outcome.view_cls or GameResultView)(self, view, replay_kwargs)}
        if outcome.file is not None:
            kw["file"] = outcome.file
            embed.set_image(url=f"attachment://{outcome.file.filename}")
        view.game_message = await safe_send(view.thread, **kw)
        await view.refresh_bet_message()

    async def end_game_by_thread(self, thread_id):
        view = self.active_games.pop(thread_id, None)
        if not view:
            return
        for step in (lambda: view.game_message.delete() if view.game_message else None,
                     lambda: safe_edit(view.bet_message, view=None) if view.bet_message else None,
                     lambda: view.thread.send("Game ended due to inactivity."),
                     lambda: view.thread.edit(archived=True, locked=True)):
            try:
                r = step()
                if r is not None:
                    await r
            except Exception:
                pass

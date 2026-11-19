from dataclasses import dataclass
from typing import Any, Optional

import nextcord
from modules.game_ui import (GameResultView, build_result_embed, format_chips,
                             safe_edit, safe_send)

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


class BettingGameCog:
    async def prepare_bet_round(self, betting_view, interaction, insufficient_message=DEFAULT_INSUFFICIENT):
        from modules.helpers import InsufficientFundsException
        balance = betting_view.get_balance()
        error = None
        if betting_view.bet < betting_view.min_bet:
            error = f"The minimum bet is {format_chips(betting_view.min_bet)}."
        elif betting_view.bet > balance:
            error = insufficient_message.format(balance=format_chips(balance), bet=format_chips(betting_view.bet))
        else:
            try:
                self.economy.place_bet(betting_view.user.id, betting_view.bet)
            except InsufficientFundsException:  # balance changed since the check
                error = insufficient_message.format(balance=format_chips(betting_view.get_balance()),
                                                    bet=format_chips(betting_view.bet))
        if error:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(error, ephemeral=True)
            except Exception as e:
                print(f"[{self.__class__.__name__}] Error sending bet error message: {e}")
            return False

        await betting_view.refresh_bet_message()
        if betting_view.game_message:
            try:
                await betting_view.game_message.delete()
            except Exception:
                pass
        return True


class BaseGameCog(BettingGameCog):
    """Subclass sets `economy`, `active_games`, `default_bet`, `game_name` and implements `play`."""
    game_name = "Game"
    default_bet = 1

    async def open_game(self, interaction, view_cls, thread_name=None, default_bet=None):
        from modules.helpers import CASINO_CHANNEL_ID, RESTRICT_TO_CASINO_CHANNEL
        if RESTRICT_TO_CASINO_CHANNEL and interaction.channel.id != CASINO_CHANNEL_ID:
            await interaction.response.send_message(
                "This command can only be used in the designated casino channel.", ephemeral=True)
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

    async def start_round(self, betting_view, interaction, **choice):
        """Bet -> play -> settle. Choice buttons and Play Again both call this."""
        if not await self.prepare_bet_round(betting_view, interaction):
            return
        if not interaction.response.is_done():
            await interaction.response.defer()
        outcome = await self.play(betting_view, interaction, **choice)
        await self.settle(betting_view, outcome, choice)

    async def settle(self, view, outcome: Outcome, replay_kwargs=None):
        user_id = view.user.id
        if outcome.payout > 0:
            self.economy.pay_out(user_id, outcome.payout)
        net = outcome.payout - view.bet
        wallet = self.economy.get_chips(user_id)
        print(f"[{self.game_name}] User: {view.user} (ID: {user_id}), Bet: {view.bet}, "
              f"Result: {'win' if outcome.won else 'loss/push'}, Payout: {outcome.payout}, "
              f"Net: {net}, Wallet: {wallet}")
        embed = build_result_embed(outcome.title, outcome.won, net, wallet, outcome.description)
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

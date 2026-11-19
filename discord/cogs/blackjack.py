import io
import os
import random

import nextcord
from nextcord import ui, Interaction, ButtonStyle
from nextcord.ext import commands

from modules.card import Card
from modules.helpers import GUILD_KW, make_embed, payout, BLACKJACK_MULT, BLACKJACK_BJ_MULT, DEFAULT_BET
from modules.base_betting_view import BaseBettingView
from modules.base_game_cog import BaseGameCog, Outcome
import logging

from modules.game_ui import format_chips, safe_delete, safe_edit, safe_send


log = logging.getLogger(__name__)

class BettingView(BaseBettingView):
    def __init__(self, cog, user, bet, thread):
        super().__init__(cog, user, bet, thread)
        self.bet_in_play = 0
        self.in_round = False  # True from Start until the hand is settled

    @ui.button(label="Start", style=ButtonStyle.success, row=2, custom_id="bet_start")
    async def bet_start(self, button, interaction: Interaction):
        await self.cog.start_round(self, interaction)


class GameView(ui.View):
    def __init__(self, cog, user, bet, thread, deck, player_hand, dealer_hand, betting_view):
        super().__init__(timeout=180)
        self.cog = cog
        self.user = user
        self.bet = bet
        self.thread = thread
        self.deck = deck
        self.player_hand = player_hand
        self.dealer_hand = dealer_hand
        self.betting_view = betting_view
        self.game_message = None
        self.finished = False

    async def interaction_check(self, interaction: Interaction) -> bool:
        return interaction.user.id == self.user.id

    async def _ack(self, interaction):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
        except Exception as e:
            log.warning("[Blackjack] Error deferring interaction: %s", e)

    @ui.button(label="Hit", style=ButtonStyle.success, custom_id="hit")
    async def hit(self, button, interaction: Interaction):
        if self.finished:
            return
        self.player_hand.append(self.deck.pop())  # no await before this: double click is safe
        await self._ack(interaction)
        await self.cog.continue_game(self)

    @ui.button(label="Stand", style=ButtonStyle.primary, custom_id="stand")
    async def stand(self, button, interaction: Interaction):
        if self.finished:
            return
        await self._ack(interaction)
        await self.cog.dealer_play(self)

    async def on_timeout(self):
        await self.cog.dealer_play(self)  # auto-stand so the round never stays stuck


class Blackjack(BaseGameCog, commands.Cog):
    game_name = "Blackjack"

    def __init__(self, client: commands.Bot):
        self.client = client
        from modules.economy import Economy
        self.economy = Economy()
        self.active_games = {}  # {thread_id: BettingView}
        self.default_bet = DEFAULT_BET

    @nextcord.slash_command(description="Play a simple game of blackjack with chips.", **GUILD_KW)
    async def blackjack(self, interaction: nextcord.Interaction):
        await self.open_game(interaction, BettingView)

    def refund_open_round(self, view):
        if view is not None and view.in_round:
            view.in_round = False
            try:
                self.economy.refund_wager(view.game_id, view.user.id)  # hand abandoned: refund the stake
            except Exception as e:
                log.error("[Blackjack] Refund failed: %s", e)

    async def end_game_by_thread(self, thread_id):
        self.refund_open_round(self.active_games.get(thread_id))
        await super().end_game_by_thread(thread_id)

    async def start_round(self, betting_view, interaction, confirmed=False, **choice):
        """Start button and Play Again: deduct the bet, deal, show Hit/Stand."""
        if betting_view.in_round:  # double click or a round already running
            try:
                if not interaction.response.is_done():
                    await interaction.response.defer()
            except Exception:
                pass
            return
        betting_view.in_round = True
        try:
            started = await self.begin_wager(betting_view, interaction, choice, confirmed)
            if started is None:
                betting_view.in_round = False
                return
        except Exception:
            betting_view.in_round = False
            raise
        _, interaction = started
        betting_view.bet_in_play = betting_view.bet
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
            deck = [Card(suit, value, down=False) for value in range(2, 15) for suit in Card.suits]
            random.shuffle(deck)
            player_hand = [deck.pop(), deck.pop()]
            dealer_hand = [deck.pop(), deck.pop().flip()]
            game_view = GameView(self, betting_view.user, betting_view.bet, betting_view.thread,
                                 deck, player_hand, dealer_hand, betting_view)
            if len(player_hand) == 2 and self.calc_hand(player_hand) == 21:
                dealer_hand[1].flip()
                natural = self.calc_hand(dealer_hand) != 21
                game_view.finished = True
                await self.finish(game_view, "Blackjack!" if natural else "Push",
                                  natural, payout(game_view.bet, BLACKJACK_BJ_MULT) if natural else game_view.bet)
                return
            await self.replace_game_message(game_view, "Your Turn")
        except Exception:
            self.refund_open_round(betting_view)  # the wager is still open: give the stake back
            raise

    async def continue_game(self, game_view: GameView):
        score = self.calc_hand(game_view.player_hand)
        if score > 21:
            game_view.finished = True
            game_view.dealer_hand[1].down = False
            await self.finish(game_view, "Player busts", False, 0)
        elif score == 21:
            await self.dealer_play(game_view)
        else:
            await self.replace_game_message(game_view, "Your Turn")

    async def dealer_play(self, game_view: GameView):
        if game_view.finished:
            return
        game_view.finished = True
        dealer = game_view.dealer_hand
        dealer[1].down = False
        player_score = self.calc_hand(game_view.player_hand)
        dealer_score = self.calc_hand(dealer)
        while dealer_score < 17:
            dealer.append(game_view.deck.pop())
            dealer_score = self.calc_hand(dealer)
        bet = game_view.bet
        if dealer_score > 21:
            result = ("Dealer busts", True, payout(bet, BLACKJACK_MULT))
        elif dealer_score == player_score:
            result = ("Push", False, bet)
        elif dealer_score > player_score:
            result = ("Dealer blackjack" if dealer_score == 21 and len(dealer) == 2 else "You lose!", False, 0)
        else:
            result = ("You win!", True, payout(bet, BLACKJACK_MULT))
        await self.finish(game_view, *result)

    async def finish(self, game_view: GameView, title, won, amount):
        game_view.stop()
        bv = game_view.betting_view
        bv.bet = game_view.bet  # the bet buttons may have moved it mid-hand
        await safe_delete(game_view.game_message)
        description = (f"Your hand: {self.calc_hand(game_view.player_hand)}\n"
                       f"Dealer's hand: {self.calc_hand(game_view.dealer_hand)}")
        try:
            file = self.render_file(game_view.user.id, game_view.dealer_hand, game_view.player_hand)
            await self.settle(bv, Outcome(won, amount, title, description, file), {}, bv.game_id)
        finally:
            bv.in_round = False

    async def replace_game_message(self, game_view, title):
        await safe_delete(game_view.game_message)
        embed = make_embed(
            title=title,
            description=(f"Bet: {format_chips(game_view.bet)}\n"
                         f"Your hand: {self.calc_hand(game_view.player_hand)}\n"
                         f"Dealer's hand: {self.calc_hand(game_view.dealer_hand)}"))
        file = self.render_file(game_view.user.id, game_view.dealer_hand, game_view.player_hand)
        embed.set_image(url=f"attachment://{file.filename}")
        msg = await safe_send(game_view.thread, embed=embed, file=file, view=game_view)
        game_view.game_message = msg
        game_view.betting_view.game_message = msg

    def hand_to_images(self, hand):
        # Loads card images using card.image property (handles face down)
        from PIL import Image
        images = []
        card_dir = os.path.join(os.path.dirname(__file__), '..', 'modules', 'cards')
        for card in hand:
            filename = getattr(card, 'image', None)
            if not filename:
                images.append(Image.new('RGBA', (100, 150), (0, 128, 0, 255)))
                continue
            path = os.path.join(card_dir, filename)
            try:
                images.append(Image.open(path).convert('RGBA'))
            except Exception:
                images.append(Image.new('RGBA', (100, 150), (0, 128, 0, 255)))
        return images

    def center(self, *hands):
        # Creates blackjack table with cards placed
        from PIL import Image
        table_path = os.path.join(os.path.dirname(__file__), '..', 'modules', 'table.png')
        bg = Image.open(table_path).convert('RGBA')
        bg_center_x = bg.size[0] // 2
        bg_center_y = bg.size[1] // 2
        if not hands or not hands[0]:
            return bg
        img_w, img_h = hands[0][0].size
        start_y = bg_center_y - (((len(hands)*img_h) + ((len(hands) - 1) * 15)) // 2)
        for hand in hands:
            start_x = bg_center_x - (((len(hand)*img_w) + ((len(hand) - 1) * 10)) // 2)
            for card in hand:
                bg.alpha_composite(card, (start_x, start_y))
                start_x += img_w + 10
            start_y += img_h + 15
        return bg

    def output(self, name, *hands):
        self.center(*map(self.hand_to_images, hands)).save(f'{name}.png')

    def render_file(self, user_id, dealer_hand, player_hand):
        """Render the table to a temp PNG, load it into memory and always delete the temp file."""
        path = f'{user_id}.png'
        try:
            self.output(user_id, dealer_hand, player_hand)
            with open(path, 'rb') as f:
                data = io.BytesIO(f.read())
        finally:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError as e:
                log.warning("[Blackjack] Error deleting image file: %s", e)
        return nextcord.File(data, filename=f"{user_id}.png")

    @staticmethod
    def calc_hand(hand: list) -> int:
        cards = [c for c in hand if not c.down]
        total = sum(1 if c.symbol == 'A' else 10 if c.symbol in 'JQK' else c.value for c in cards)
        if any(c.symbol == 'A' for c in cards) and total + 10 <= 21:
            total += 10  # one ace may count 11
        return total


def setup(client: commands.Bot):
    client.add_cog(Blackjack(client))

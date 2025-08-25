from nextcord import ui, Interaction, ButtonStyle
from nextcord.ext import commands
import nextcord
import random
from modules.card import Card
from modules.economy import Economy
from modules.helpers import *
from modules.base_betting_view import BaseBettingView

class BettingView(BaseBettingView):
    def __init__(self, cog, user, bet, thread):
        super().__init__(cog, user, bet, thread)

    @ui.button(label="Start", style=ButtonStyle.success, row=2, custom_id="bet_start")
    async def bet_start(self, button, interaction: Interaction):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
        except Exception as e:
            print(f"[Blackjack] Error deferring interaction: {e}")
        await self.cog.start_game(self, interaction)

    async def update_bet_message(self, interaction):
        balance = self.cog.economy.get_entry(self.user.id)[1]
        embed = make_embed(
            title="Set your bet",
            description=f"Current bet: ${self.bet}\nWallet: ${balance}"
        )
        await interaction.response.edit_message(embed=embed, view=self)

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

    async def interaction_check(self, interaction: Interaction) -> bool:
        return interaction.user.id == self.user.id

    @ui.button(label="Hit", style=ButtonStyle.success, custom_id="hit")
    async def hit(self, button, interaction: Interaction):
        self.player_hand.append(self.deck.pop())
        await self.cog.continue_game(self, interaction)

    @ui.button(label="Stand", style=ButtonStyle.primary, custom_id="stand")
    async def stand(self, button, interaction: Interaction):
        await self.cog.dealer_play(self, interaction)

class Blackjack(commands.Cog):

    def hand_to_images(self, hand):
        # Loads card images using card.image property (handles face down)
        from PIL import Image
        import os
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
        import os
        table_path = os.path.join(os.path.dirname(__file__), '..', 'modules', 'table.png')
        bg = Image.open(table_path).convert('RGBA')
        bg_center_x = bg.size[0] // 2
        bg_center_y = bg.size[1] // 2
        if not hands or not hands[0]:
            return bg
        img_w, img_h = hands[0][0].size
        start_y = bg_center_y - (((len(hands)*img_h) + ((len(hands) - 1) * 15) ) // 2)
        for hand in hands:
            start_x = bg_center_x - (((len(hand)*img_w) + ((len(hand) - 1) * 10)) // 2)
            for card in hand:
                bg.alpha_composite(card, (start_x, start_y))
                start_x += img_w + 10
            start_y += img_h + 15
        return bg
    def __init__(self, client: commands.Bot):
        self.client = client
        from modules.economy import Economy
        from modules.helpers import DEFAULT_BET
        self.economy = Economy()
        self.active_games = {}  # {thread_id: BettingView}
        self.default_bet = DEFAULT_BET
    async def end_game_by_thread(self, thread_id):
        view = self.active_games.pop(thread_id, None)
        if view:
            try:
                if view.game_message:
                    await view.game_message.delete()
            except Exception:
                pass
            try:
                if view.bet_message:
                    await view.bet_message.edit(view=None)
            except Exception:
                pass
            try:
                await view.thread.send("Game ended due to inactivity.")
            except Exception:
                pass
            try:
                await view.thread.edit(archived=True, locked=True)
            except Exception:
                pass

    from modules.helpers import TEST_GUILD_ID
    USE_TEST_GUILD = False  # Set to True for fast test registration

    def __init__(self, client: commands.Bot):
        self.client = client
        from modules.economy import Economy
        from modules.helpers import DEFAULT_BET
        self.economy = Economy()
        self.active_games = {}  # {thread_id: BettingView}
        self.default_bet = DEFAULT_BET

    @nextcord.slash_command(
        description="Play a simple game of blackjack. Bet must be greater than $0",
        **({"guild_ids": [TEST_GUILD_ID]} if USE_TEST_GUILD else {})
    )
    async def blackjack(self, interaction: nextcord.Interaction):
        from modules.helpers import CASINO_CHANNEL_ID
        if interaction.channel.id != CASINO_CHANNEL_ID:
            await interaction.response.send_message("This command can only be used in the designated casino channel.", ephemeral=True)
            return
        if interaction.response.is_done():
            print("[Blackjack] Interaction already responded to, aborting.")
            return
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception as e:
            print(f"[Blackjack] Error deferring interaction: {e}")
            return
        try:
            await interaction.followup.send("Game started! ✅", ephemeral=True)
        except Exception as e:
            print(f"[Blackjack] Error sending followup: {e}")
        thread = await interaction.channel.create_thread(
            name=f"Blackjack - {interaction.user.display_name}",
            type=nextcord.ChannelType.public_thread
        )
        balance = self.economy.get_entry(interaction.user.id)[1]
        bet = min(self.default_bet, balance) if balance > 0 else 1
        view = BettingView(self, interaction.user, bet, thread)
        embed = make_embed(
            title="Set your bet",
            description=f"Current bet: ${bet}\nWallet: ${balance}"
        )
        msg = await thread.send(embed=embed, view=view)
        view.bet_message = msg

    async def start_game(self, betting_view: BettingView, interaction: Interaction):
        # Check for sufficient funds before starting
        balance = self.economy.get_entry(betting_view.user.id)[1]
        if betting_view.bet > balance:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        f"You do not have enough money to place this bet! (You have ${balance}, bet is ${betting_view.bet})",
                        ephemeral=True
                    )
            except Exception as e:
                print(f"[Blackjack] Error sending not enough money message: {e}")
            return
        # Subtract bet at game start
        self.economy.add_money(betting_view.user.id, -betting_view.bet)
        # Update betting message to show new balance after bet is subtracted
        if betting_view.bet_message:
            balance = self.economy.get_entry(betting_view.user.id)[1]
            bet_embed = make_embed(
                title="Set your bet",
                description=f"Current bet: ${betting_view.bet}\nWallet: ${balance}"
            )
            await betting_view.bet_message.edit(embed=bet_embed, view=betting_view)
        # Delete old game message if it exists
        if betting_view.game_message:
            try:
                await betting_view.game_message.delete()
            except Exception:
                pass
        # Deal new game
        deck = [Card(suit, num, down=False) for num in range(2,15) for suit in Card.suits]
        random.shuffle(deck)
        player_hand = [deck.pop(), deck.pop()]
        dealer_hand = [deck.pop(), deck.pop().flip()]
        game_view = GameView(self, betting_view.user, betting_view.bet, betting_view.thread, deck, player_hand, dealer_hand, betting_view)
        msg = await self.send_game_message(game_view, "Your Turn", player_hand, dealer_hand)
        betting_view.game_message = msg
        game_view.game_message = msg

    async def continue_game(self, game_view: GameView, interaction: Interaction):
        player_score = self.calc_hand(game_view.player_hand)
        dealer_score = self.calc_hand(game_view.dealer_hand)
        from modules.helpers import BLACKJACK_BJ_MULT
        if player_score == 21:
            win_amt = int(game_view.bet * BLACKJACK_BJ_MULT)
            self.economy.add_money(game_view.user.id, win_amt)
            await self.show_result(game_view, interaction, ("Blackjack!", 'won', win_amt))
            return
        elif player_score > 21:
            # Already lost bet
            await self.show_result(game_view, interaction, ("Player busts", 'lost', 0))
            return
        await self.replace_game_message(game_view, "Your Turn", game_view.player_hand, game_view.dealer_hand)

    async def dealer_play(self, game_view: GameView, interaction: Interaction):
        game_view.dealer_hand[1].flip()
        player_score = self.calc_hand(game_view.player_hand)
        dealer_score = self.calc_hand(game_view.dealer_hand)
        while dealer_score < 17:
            game_view.dealer_hand.append(game_view.deck.pop())
            dealer_score = self.calc_hand(game_view.dealer_hand)
        from modules.helpers import BLACKJACK_MULT
        if dealer_score == 21:
            # Already lost bet
            result = ('Dealer blackjack', 'lost', 0)
        elif dealer_score > 21:
            win_amt = int(game_view.bet * BLACKJACK_MULT)
            self.economy.add_money(game_view.user.id, win_amt)
            result = ("Dealer busts", 'won', win_amt)
        elif dealer_score == player_score:
            self.economy.add_money(game_view.user.id, game_view.bet)
            result = ("Tie!", 'kept', game_view.bet)
        elif dealer_score > player_score:
            # Already lost bet
            result = ("You lose!", 'lost', 0)
        elif dealer_score < player_score:
            win_amt = int(game_view.bet * BLACKJACK_MULT)
            self.economy.add_money(game_view.user.id, win_amt)
            result = ("You win!", 'won', win_amt)
        await self.show_result(game_view, interaction, result)

    async def show_result(self, game_view: GameView, interaction: Interaction, result):
        player_score = self.calc_hand(game_view.player_hand)
        dealer_score = self.calc_hand(game_view.dealer_hand)
        color = (
            nextcord.Color.red() if result[1] == 'lost'
            else nextcord.Color.green() if result[1] == 'won'
            else nextcord.Color.blue()
        )
        embed = make_embed(
            title=result[0],
            color=color,
            description=(
                f"**You {result[1]} ${abs(result[2])}**\nYour hand: {player_score}\n" +
                f"Dealer's hand: {dealer_score}"
            )
        )
        # --- Game result logging ---
        print(f"[Blackjack] User: {game_view.user} (ID: {game_view.user.id}), Bet: ${game_view.bet}, Result: {result[1]}, Amount: {abs(result[2])}, Player hand: {player_score}, Dealer hand: {dealer_score}")
        self.output(game_view.user.id, game_view.dealer_hand, game_view.player_hand)
        file = nextcord.File(f"{game_view.user.id}.png", filename=f"{game_view.user.id}.png")
        embed.set_image(url=f"attachment://{game_view.user.id}.png")
        try:
            await game_view.game_message.delete()
        except nextcord.errors.NotFound:
            pass
        except Exception as e:
            print(f"[Blackjack] Error deleting game message: {e}")
        view = ui.View()  # No buttons
        msg = await game_view.thread.send(embed=embed, file=file, view=view)
        game_view.betting_view.game_message = msg
        # Update wallet in betting window
        balance = self.economy.get_entry(game_view.user.id)[1]
        game_view.betting_view.bet = game_view.bet
        bet_embed = make_embed(
            title="Set your bet",
            description=f"Current bet: ${game_view.bet}\nWallet: ${balance}\nAdjust your bet with 5/6, then press Start."
        )
        await game_view.betting_view.bet_message.edit(embed=bet_embed, view=game_view.betting_view)
        import time
        for _ in range(5):
            try:
                os.remove(f'./{game_view.user.id}.png')
                break
            except PermissionError:
                time.sleep(0.1)
            except Exception as e:
                print(f"[Blackjack] Error deleting image file: {e}")
                break

    async def send_game_message(self, game_view, title, player_hand, dealer_hand):
        player_score = self.calc_hand(player_hand)
        dealer_score = self.calc_hand(dealer_hand)
        # Commented out hand debugging (card details)
        embed = make_embed(
            title=title,
            description=f"Bet: ${game_view.bet}\nYour hand: {player_score}\nDealer's hand: {dealer_score}"
        )
        self.output(game_view.user.id, dealer_hand, player_hand)
        file = nextcord.File(f"{game_view.user.id}.png", filename=f"{game_view.user.id}.png")
        embed.set_image(url=f"attachment://{game_view.user.id}.png")
        msg = await game_view.thread.send(embed=embed, file=file, view=game_view)
        os.remove(f'./{game_view.user.id}.png')
        return msg

    async def replace_game_message(self, game_view, title, player_hand, dealer_hand):
        try:
            await game_view.game_message.delete()
        except Exception:
            pass
        msg = await self.send_game_message(game_view, title, player_hand, dealer_hand)
        game_view.betting_view.game_message = msg
        game_view.game_message = msg

    @staticmethod
    def calc_hand(hand: list) -> int:
        non_aces = [c for c in hand if c.symbol != 'A']
        aces = [c for c in hand if c.symbol == 'A']
        total = 0
        for card in non_aces:
            if not card.down:
                if card.symbol in 'JQK': total += 10
                else: total += card.value
        for card in aces:
            if not card.down:
                if total <= 10: total += 11
                else: total += 1
        return total

    def output(self, name, *hands):
        # ...existing code for image output...
        self.center(*map(self.hand_to_images, hands)).save(f'{name}.png')

def setup(client: commands.Bot):
    client.add_cog(Blackjack(client))
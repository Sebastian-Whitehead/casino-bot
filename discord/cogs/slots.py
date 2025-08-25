import bisect
import random
import nextcord as discord
from nextcord.ext import commands
from nextcord import ui, Interaction, ButtonStyle
from modules.helpers import *
from PIL import Image


class BettingView(ui.View):
    @ui.button(label="Auto", style=ButtonStyle.secondary, row=2, custom_id="auto_spin")
    async def auto_spin_btn(self, button, interaction: Interaction):
        import asyncio
        if not self.auto_spin:
            self.auto_spin = True
            button.style = ButtonStyle.primary  # Blue when on
            self._auto_stop_event.clear()
            self.auto_task = self.cog.client.loop.create_task(self.auto_spin_loop(interaction))
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("Auto-spin started!", ephemeral=True)
        else:
            self.auto_spin = False
            button.style = ButtonStyle.secondary  # Black when off
            self._auto_stop_event.set()
            if self.auto_task:
                try:
                    self.auto_task.cancel()
                    await asyncio.sleep(0)
                except Exception:
                    pass
                self.auto_task = None
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("Auto-spin stopped.", ephemeral=True)

    async def auto_spin_loop(self, interaction):
        import asyncio
        try:
            while self.auto_spin:
                try:
                    await asyncio.wait_for(self._auto_stop_event.wait(), timeout=5)
                    break
                except asyncio.TimeoutError:
                    pass
                if not self.auto_spin:
                    break
                await self.cog.start_game(self, interaction)
        except asyncio.CancelledError:
            pass
    def __init__(self, cog, user, bet, thread):
        super().__init__(timeout=None)
        self.cog = cog
        self.user = user
        self.bet = bet
        self.thread = thread
        self.bet_message = None
        self.game_message = None
        self.auto_spin = False
        self.auto_task = None
        import asyncio
        self._auto_stop_event = asyncio.Event()

    def cap_bet(self, new_bet):
        """Cap the bet to the user's balance, minimum 1."""
        balance = self.cog.economy.get_entry(self.user.id)[2]
        return max(1, min(new_bet, balance))


    @ui.button(label="x10", style=ButtonStyle.secondary, row=0, custom_id="bet_mul_10")
    async def bet_mul_10(self, button, interaction: Interaction):
        self.bet = self.cap_bet(self.bet * 10)
        await self.update_bet_message(interaction)

    @ui.button(label="+10", style=ButtonStyle.secondary, row=0, custom_id="bet_plus_10")
    async def bet_plus_10(self, button, interaction: Interaction):
        self.bet = self.cap_bet(self.bet + 10)
        await self.update_bet_message(interaction)

    @ui.button(label="+1", style=ButtonStyle.secondary, row=0, custom_id="bet_plus_1")
    async def bet_plus_1(self, button, interaction: Interaction):
        self.bet = self.cap_bet(self.bet + 1)
        await self.update_bet_message(interaction)

    @ui.button(label="/10", style=ButtonStyle.secondary, row=1, custom_id="bet_div_10")
    async def bet_div_10(self, button, interaction: Interaction):
        self.bet = self.cap_bet(self.bet // 10)
        await self.update_bet_message(interaction)

    @ui.button(label="-10", style=ButtonStyle.secondary, row=1, custom_id="bet_minus_10")
    async def bet_minus_10(self, button, interaction: Interaction):
        self.bet = self.cap_bet(self.bet - 10)
        await self.update_bet_message(interaction)

    @ui.button(label="-1", style=ButtonStyle.secondary, row=1, custom_id="bet_minus_1")
    async def bet_minus_1(self, button, interaction: Interaction):
        self.bet = self.cap_bet(self.bet - 1)
        await self.update_bet_message(interaction)

    @ui.button(label="Start", style=ButtonStyle.success, row=2, custom_id="bet_start")
    async def bet_start(self, button, interaction: Interaction):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
        except Exception as e:
            print(f"[Slots] Error deferring interaction: {e}")
        await self.cog.start_game(self, interaction)

    @ui.button(emoji="❌", style=ButtonStyle.danger, row=2, custom_id="close")
    async def close(self, button, interaction: Interaction):
        if self.game_message:
            await self.game_message.delete()
        if self.cog.active_games.get(self.user.id) is self:
            del self.cog.active_games[self.user.id]
        if self.bet_message:
            try:
                await self.bet_message.edit(view=None)
            except Exception:
                pass
        await interaction.response.send_message(
            "Game ended and thread closed.",
            ephemeral=True)
        try:
            await self.thread.edit(archived=True, locked=True)
        except Exception:
            pass

    async def update_bet_message(self, interaction):
        balance = self.cog.economy.get_entry(self.user.id)[2]
        embed = make_embed(
            title="Set your bet (credits)",
            description=(
                f"Current bet: {self.bet} credits\nWallet: {balance} credits"
            )
        )
        await interaction.response.edit_message(embed=embed, view=self)


class GameView(ui.View):
    def __init__(self, cog, user, bet, thread, betting_view):
        super().__init__(timeout=60)
        self.cog = cog
        self.user = user
        self.bet = bet
        self.thread = thread
        self.betting_view = betting_view
        self.game_message = None

    async def interaction_check(self, interaction: Interaction) -> bool:
        return interaction.user.id == self.user.id

    @ui.button(label="Play Again", style=ButtonStyle.success, custom_id="play_again")
    async def play_again(self, button, interaction: Interaction):
        self.auto_spin = False
        await self.cog.start_game(self.betting_view, interaction)


    @ui.button(label="Back to Bet", style=ButtonStyle.secondary, custom_id="back_to_bet")
    async def back_to_bet(self, button, interaction: Interaction):
        # If auto-spin is running, stop it and wait for the task to finish
        bv = self.betting_view
        stopped = False
        if bv.auto_spin:
            bv.auto_spin = False
            stopped = True
            bv._auto_stop_event.set()
            if bv.auto_task:
                try:
                    bv.auto_task.cancel()
                    import asyncio
                    await asyncio.sleep(0)  # Let the cancellation propagate
                except Exception:
                    pass
                bv.auto_task = None
        if self.game_message:
            await self.game_message.delete()
        if stopped:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("Auto-spin stopped.", ephemeral=True)
            except Exception as e:
                print(f"[Slots] Error sending auto-spin stopped: {e}")
        else:
            try:
                if not interaction.response.is_done():
                    await interaction.response.defer()
            except Exception as e:
                print(f"[Slots] Error deferring interaction: {e}")


class Slots(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        from modules.economy import Economy
        from modules.helpers import SLOTS_DEFAULT_BET, TOKEN_PRICE, DEFAULT_BET
        self.economy = Economy()
        self.active_games = {}  # {thread_id: BettingView}
        self.slots_default_bet = SLOTS_DEFAULT_BET
        self.token_price = TOKEN_PRICE
        self.default_bet = DEFAULT_BET

    from modules.helpers import TEST_GUILD_ID
    USE_TEST_GUILD = False  # Set to True for fast test registration

    @discord.slash_command(
        description="Play the slot machine. Bet must be 1-3 credits.",
        **({"guild_ids": [TEST_GUILD_ID]} if USE_TEST_GUILD else {})
    )
    async def slots(self, interaction: discord.Interaction):
        from modules.helpers import CASINO_CHANNEL_ID
        if interaction.channel.id != CASINO_CHANNEL_ID:
            await interaction.response.send_message("This command can only be used in the designated casino channel.", ephemeral=True)
            return
        if interaction.response.is_done():
            print("[Slots] Interaction already responded to, aborting.")
            return
        try:
            await interaction.response.send_message("Game started! \u2705", ephemeral=True)
        except Exception as e:
            print(f"[Slots] Error sending game started: {e}")
            return
        thread = await interaction.channel.create_thread(
            name=f"Slots - {interaction.user.display_name}",
            type=discord.ChannelType.public_thread
        )
        balance = self.economy.get_entry(interaction.user.id)[2]
        # Cap bet to user's balance (minimum 1 if balance is 0)
        bet = min(self.slots_default_bet, balance) if balance > 0 else 1
        view = BettingView(self, interaction.user, bet, thread)
        self.active_games[thread.id] = view
        # Send a static instructions embed (buy/sell credits) as the FIRST message
        instructions_embed = make_embed(
            title="How to Buy/Sell Credits",
            description=(
                f"Each credit costs ${self.token_price}.\n"
                f"To buy credits: `/buyc amount_to_buy:<number>`\n"
                f"To sell credits: `/sellc amount_to_sell:<number>`"
            )
        )
        await thread.send(embed=instructions_embed)
        # Now send the betting window embed, WITHOUT buy/sell instructions
        embed = make_embed(
            title="Set your bet (credits)",
            description=(
                f"Current bet: {bet} credits\nWallet: {balance} credits"
            )
        )
        msg = await thread.send(embed=embed, view=view)
        view.bet_message = msg
    async def end_game_by_thread(self, thread_id):
        # End/cleanup the game in this thread if it exists
        view = self.active_games.pop(thread_id, None)
        if view:
            # Clean up messages/UI if needed
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
            # Optionally, send a message to the thread (if not deleted yet)
            try:
                await view.thread.send("Game ended due to inactivity.")
            except Exception:
                pass
            # Archive and lock the thread (if not already)
            try:
                await view.thread.edit(archived=True, locked=True)
            except Exception:
                pass

    async def start_game(self, betting_view: BettingView, interaction: Interaction):
        # Check for sufficient credits before starting
        balance = self.economy.get_entry(betting_view.user.id)[2]
        if betting_view.bet > balance:
            await interaction.response.send_message(
                f"You do not have enough credits to place this bet! (You have {balance}, bet is {betting_view.bet})",
                ephemeral=True
            )
            return
        # Subtract bet at game start
        self.economy.add_credits(betting_view.user.id, -betting_view.bet)
        # Update betting message to show new balance after bet is subtracted
        if betting_view.bet_message:
            balance = self.economy.get_entry(betting_view.user.id)[2]
            bet_embed = make_embed(
                title="Set your bet (credits)",
                description=f"Current bet: {betting_view.bet} credits\nWallet: {balance} credits"
            )
            await betting_view.bet_message.edit(embed=bet_embed, view=betting_view)
        # Delete old game message if it exists
        if betting_view.game_message:
            try:
                await betting_view.game_message.delete()
            except Exception:
                pass
        # Play slot game
        msg = await self.send_game_message(betting_view, betting_view.bet)
        betting_view.game_message = msg

    async def send_game_message(self, betting_view, bet):
        # Slot logic and image generation
        path = os.path.join(os.path.dirname(__file__), '..', 'modules')
        facade = Image.open(f'{path}/slot-face.png').convert('RGBA')
        reel = Image.open(f'{path}/slot-reel.png').convert('RGBA')
        rw, rh = reel.size
        item = 180
        items = rh // item
        s1 = random.randint(1, items-1)
        s2 = random.randint(1, items-1)
        s3 = random.randint(1, items-1)
        win_rate = 12/100
        if random.random() < win_rate:
            symbols_weights = [3.5, 7, 15, 25, 55]
            x = round(random.random()*100, 1)
            pos = bisect.bisect(symbols_weights, x)
            s1 = pos + (random.randint(1, int((items/6)-1)) * 6)
            s2 = pos + (random.randint(1, int((items/6)-1)) * 6)
            s3 = pos + (random.randint(1, int((items/6)-1)) * 6)
            s1 = s1 - 6 if s1 == items else s1
            s2 = s2 - 6 if s2 == items else s2
            s3 = s3 - 6 if s3 == items else s3
        images = []
        speed = 6
        for i in range(1, (item//speed)+1):
            bg = Image.new('RGBA', facade.size, color=(255,255,255))
            bg.paste(reel, (25 + rw*0, 100-(speed * i * s1)))
            bg.paste(reel, (25 + rw*1, 100-(speed * i * s2)))
            bg.paste(reel, (25 + rw*2, 100-(speed * i * s3)))
            bg.alpha_composite(facade)
            images.append(bg)
        fp = f'{betting_view.user.id}_slots.gif'
        images[0].save(
            fp,
            save_all=True,
            append_images=images[1:],
            duration=50
        )
        # win logic
        result = ('lost', bet)
        # (1+s1)%6 gets the symbol 0-5 inclusive
        from modules.helpers import SLOTS_MULTS
        if (1+s1)%6 == (1+s2)%6 == (1+s3)%6:
            symbol = (1+s1)%6
            reward = SLOTS_MULTS[symbol] * bet
            result = ('won', reward)
            self.economy.add_credits(betting_view.user.id, reward)
        # --- Game result logging ---
        print(f"[Slots] User: {betting_view.user} (ID: {betting_view.user.id}), Bet: {bet}, Result: {result[0]}, Amount: {result[1]}, Symbols: {((1+s1)%6, (1+s2)%6, (1+s3)%6)}")
        embed = make_embed(
            title=(
                f'You {result[0]} {result[1]} credits'+
                ('.' if result[0] == 'lost' else '!')
            ),
            description=(
                'You now have ' +
                f'**{self.economy.get_entry(betting_view.user.id)[2]}** ' +
                'credits.'
            ),
            color=(
                discord.Color.red() if result[0] == "lost"
                else discord.Color.green()
            )
        )
        file = discord.File(fp, filename=fp)
        embed.set_image(url=f"attachment://{fp}")
        view = GameView(self, betting_view.user, bet, betting_view.thread, betting_view)
        msg = await betting_view.thread.send(file=file, embed=embed, view=view)
        view.game_message = msg
        os.remove(fp)
        return msg

    @discord.slash_command(
        description=lambda self: f"Purchase credits. Each credit is worth ${self.token_price}.",
        **({"guild_ids": [TEST_GUILD_ID]} if USE_TEST_GUILD else {})
    )
    async def buyc(self, interaction: discord.Interaction, amount_to_buy: int):
        user_id = interaction.user.id
        profile = self.economy.get_entry(user_id)
        cost = amount_to_buy * self.token_price
        if profile[1] >= cost:
            self.economy.add_money(user_id, cost*-1)
            self.economy.add_credits(user_id, amount_to_buy)
        await interaction.response.send_message(f"Purchased {amount_to_buy} credits.", ephemeral=True)

    @discord.slash_command(
        description=lambda self: f'Sell credits. Each credit is worth ${self.token_price}.' ,
        **({"guild_ids": [TEST_GUILD_ID]} if USE_TEST_GUILD else {})
    )
    async def sellc(self, interaction: discord.Interaction, amount_to_sell: int):
        user_id = interaction.user.id
        profile = self.economy.get_entry(user_id)
        if profile[2] >= amount_to_sell:
            self.economy.add_credits(user_id, amount_to_sell*-1)
            self.economy.add_money(user_id, amount_to_sell*self.token_price)
        await interaction.response.send_message(f"Sold {amount_to_sell} credits.", ephemeral=True)

def setup(client: commands.Bot):
    client.add_cog(Slots(client))
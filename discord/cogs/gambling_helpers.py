import time

import nextcord as discord
from nextcord.ext import commands
from modules.economy import Economy
from modules.helpers import B_COOLDOWN, B_MULT, CHIP_VALUE, DEFAULT_BET, make_embed


def claim_bonus(economy, user_id: int, now: float = None):
    """Grant the bonus unless on cooldown. Returns (granted, seconds_remaining, amount)."""
    now = time.time() if now is None else now
    amount = DEFAULT_BET * B_MULT * CHIP_VALUE
    row = economy.cur.execute("SELECT ts FROM bonus_claims WHERE user_id=?", (user_id,)).fetchone()
    if row and now - row[0] < B_COOLDOWN * 3600:
        return False, int(B_COOLDOWN * 3600 - (now - row[0])), amount
    if not economy.bank.deposit(user_id, amount):  # casino cannot pay: no claim recorded
        return False, 0, amount
    economy.cur.execute("INSERT OR REPLACE INTO bonus_claims(user_id, ts) VALUES(?,?)", (user_id, now))
    economy.conn.commit()
    return True, 0, amount


class GamblingHelpers(commands.Cog, name='General'):
    def __init__(self, client: commands.Bot) -> None:
        self.client = client
        self.economy = Economy()

    @commands.command(hidden=True)
    @commands.is_owner()
    async def set(
        self,
        ctx: commands.Context,
        user_id: int=None,
        money: int=None,
        chips: int=None
    ):
        if user_id is None:
            return
        if money is not None:
            self.economy.bank.set_balance(user_id, money)  # bank money lives in the bank, not the economy table
        if chips is not None:
            self.economy.set_chips(user_id, chips)

    @commands.command(
        brief="Gives you your bonus once every set cooldown hours.",
        usage="add"
    )
    async def add(self, ctx: commands.Context):
        granted, remaining, amount = claim_bonus(self.economy, ctx.author.id)
        if granted:
            await ctx.send(f"Added ${amount:,} to your bank. Come back in {B_COOLDOWN}hrs.")
        elif remaining:
            h, m = divmod(remaining // 60, 60)
            await ctx.send(f"Bonus on cooldown: {h}h {m}m left.")
        else:
            await ctx.send("The casino cannot pay the bonus right now.")

    @commands.command(
        brief="Shows the players with the most chips plus bank money",
        usage="leaderboard",
        aliases=["top"]
    )
    async def leaderboard(self, ctx):
        rows = [(uid, self.economy.bank.balance(uid), chips)
                for uid, chips in self.economy.get_all_entries() if uid != self.economy.casino_user_id]
        entries = sorted(rows, key=lambda r: r[1] + r[2] * CHIP_VALUE, reverse=True)[:5]
        embed = make_embed(title='Leaderboard (chips + bank money):', color=discord.Color.gold())
        for i, (uid, money, chips) in enumerate(entries):
            user = self.client.get_user(uid)
            embed.add_field(
                name=f"{i+1}. {user.name if user else uid}",
                value=f"{chips:,} chips + {self.economy.bank.display(uid)}",
                inline=False
            )
        await ctx.send(embed=embed)

def setup(client: commands.Bot):
    client.add_cog(GamblingHelpers(client))

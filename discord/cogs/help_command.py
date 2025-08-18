import os
import nextcord as discord
from modules.helpers import ABS_PATH, make_embed
from nextcord.ext import commands
import os


class Help(commands.Cog, name='help'):
    def __init__(self, client: commands.Bot):
        self.client = client

    @commands.command(
        brief="Lists commands and gives info.",
        usage="help *command",
        hidden=True
    )
    async def help(self, ctx, request=None):
        if not request:
            embed = make_embed(title="Commands")
            print('Cog names and types:')
            for name, cog in self.client.cogs.items():
                print(f'  {name!r} ({type(name)})')
            for name, cog in self.client.cogs.items():
                # Only add cogs with a valid string name
                if not isinstance(name, str):
                    continue
                cog_commands = [command for command in cog.get_commands() if not command.hidden]
                if len(cog_commands) != 0:
                    value_lines = []
                    for command in cog_commands:
                        try:
                            value_lines.append(f'{self.client.command_prefix}{command.name}')
                        except Exception as e:
                            print(f'Error with command in cog {name}: {command}, error: {e}')
                            value_lines.append(str(command))
                    print(f'Adding field: name={name!r}, value={value_lines}')
                    embed.add_field(
                        name=name,
                        value='\n'.join(value_lines),
                        inline=False
                    )
            fp = os.path.join(ABS_PATH, 'modules/cards/aces.png')
            file = discord.File(fp, filename='aces.png')
            embed.set_thumbnail(url=f"attachment://aces.png")
        else:
            com = self.client.get_command(request)
            if not com:
                await ctx.invoke(self.client.get_command('help'))
                return
            embed = make_embed(
                title=com.name, description=com.brief, footer="* optional"
            )                       
            embed.add_field(
                name='Usage:',
                value='`'+self.client.command_prefix+com.usage+'`'
            )
            file = None
        await ctx.send(file=file, embed=embed)


    @commands.command(hidden=True)
    @commands.is_owner()
    async def kill(self, ctx: commands.Context):
        self.client.remove_cog('handlers')
        await self.client.logout()


def setup(client):
    client.add_cog(Help(client))

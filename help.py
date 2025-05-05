import discord
from discord.ext import commands, tasks
import asyncio

intents = discord.Intents.default()
intents.members = True
intents.voice_states = True
intents.guilds = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="/", intents=intents, help_command=None)  # Disable default help command

# ✅ Custom /help command
@bot.command(name="help")
async def custom_help(ctx):
    embed = discord.Embed(title="🤖 COM BOT Command Menu", color=discord.Color.blue())
    embed.add_field(name="/join", value="Join the player queue (up to 10 players).", inline=False)
    embed.add_field(name="/resetqueue", value="Reset the queue and teams. (Admin only)", inline=False)
    embed.add_field(name="/queue", value="Display the current list of players in the queue.", inline=False)
    embed.add_field(name="/purge <number>", value="Delete the last <number> messages in the current channel. (Admin only)", inline=False)
    embed.set_footer(text="Use the commands as per your requirements and have fun! 🎮")
    await ctx.send(embed=embed)

# ✅ Manual Purge Command
@bot.command()
@commands.has_permissions(manage_messages=True)
async def purge(ctx, amount: int):
    if amount < 1:
        await ctx.send("❌ Please specify a number greater than 0.")
        return
    await ctx.channel.purge(limit=amount + 1)
    confirmation = await ctx.send(f"✅ Deleted {amount} messages.")
    await confirmation.delete(delay=3)

# ✅ Auto-purge messages every 10 seconds in "com-register" channel
@tasks.loop(seconds=10)
async def auto_purge_com_register():
    await bot.wait_until_ready()
    for guild in bot.guilds:
        com_channel = discord.utils.get(guild.text_channels, name="com-register")
        if com_channel:
            try:
                await com_channel.purge(limit=100)
            except discord.Forbidden:
                print(f"Missing permissions to purge messages in #{com_channel.name}")
            except Exception as e:
                print(f"Error purging #{com_channel.name}: {e}")

# ✅ Start the purge task when bot is ready
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    auto_purge_com_register.start()

# 🔒 Replace with your real bot token
bot.run("MTM2ODQ2ODI5OTc3OTkzNjM3Ng.Gpyr0o.Hqwa8c6sjm0EPqm2mqKVMlALQIH08J9RT7ttdQ")

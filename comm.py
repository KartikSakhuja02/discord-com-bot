import discord
from discord.ext import commands, tasks
import random
from discord.ui import Button, View, Select
from collections import Counter

intents = discord.Intents.default()
intents.members = True
intents.voice_states = True
intents.guilds = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents) 

player_queue = []
captains = []
team1 = []
team2 = []
map_pool = ["A", "B", "C", "D", "E", "F"]

# Remove default help
bot.remove_command("help")

@bot.event
async def on_ready():
    print(f"✅ Bot is ready. Logged in as {bot.user}")
    purge_com_register.start()

@tasks.loop(seconds=10)
async def purge_com_register():
    await bot.wait_until_ready()
    for guild in bot.guilds:
        channel = discord.utils.get(guild.text_channels, name="com-register")
        if channel:
            try:
                await channel.purge(limit=100)
            except discord.Forbidden:
                print(f"⚠️ Missing permissions to purge in {channel.name}")
            except discord.HTTPException as e:
                print(f"❌ Failed to purge messages in {channel.name}: {e}")

@bot.event
async def on_voice_state_update(member, before, after):
    guild = member.guild
    queue_vc = discord.utils.get(guild.voice_channels, name="Queue 1")
    text_channel = discord.utils.get(guild.text_channels, name="queue-1-chat")

    if not queue_vc or not text_channel:
        return

    if after.channel == queue_vc:
        overwrite = discord.PermissionOverwrite()
        overwrite.read_messages = True
        overwrite.send_messages = True
        await text_channel.set_permissions(member, overwrite=overwrite)
    elif before.channel == queue_vc and after.channel != queue_vc:
        await text_channel.set_permissions(member, overwrite=None)

@bot.command()
async def register(ctx):
    if ctx.channel.name != "com-register":
        await ctx.send("❌ You can only register in the #com-register channel.", delete_after=5)
        return

    unranked_role = discord.utils.get(ctx.guild.roles, name="UNRANKED")
    if not unranked_role:
        await ctx.send("❌ 'UNRANKED' role not found. Please ask an admin to create it.", delete_after=5)
        return

    if unranked_role in ctx.author.roles:
        await ctx.send("✅ You are already registered!", delete_after=5)
    else:
        await ctx.author.add_roles(unranked_role)
        await ctx.send(f"✅ {ctx.author.mention}, you have been registered and given the UNRANKED role!", delete_after=5)

@bot.command()
async def join(ctx):
    if ctx.channel.name != "queue-1-chat":
        await ctx.send("❌ You can only use this command in the #queue-1-chat channel.", delete_after=5)
        return

    voice_state = ctx.author.voice
    if not voice_state or not voice_state.channel or voice_state.channel.name != "Queue 1":
        await ctx.send("❌ You must be in the **Queue 1** voice channel to join the queue.", delete_after=5)
        return

    if ctx.author in player_queue:
        await ctx.send("You are already in the queue.")
    elif len(player_queue) >= 10:
        await ctx.send("Queue is full.")
    else:
        player_queue.append(ctx.author)
        await ctx.send(f"{ctx.author.display_name} joined the queue! ({len(player_queue)}/10)")

    if len(player_queue) == 10:
        await ctx.send("🎮 Queue full! Voting for captains is starting...")
        await start_captain_voting(ctx)


async def start_captain_voting(ctx):
    vote_counts = Counter()

    class VoteButton(Button):
        def __init__(self, player):
            super().__init__(label=player.display_name, style=discord.ButtonStyle.primary)
            self.player = player

        async def callback(self, interaction: discord.Interaction):
            if interaction.user not in player_queue:
                await interaction.response.send_message("❌ You are not in the queue.", ephemeral=True)
                return

            vote_counts[self.player] += 1
            await interaction.response.send_message(f"✅ You voted for {self.player.display_name}", ephemeral=True)

    class VotingView(View):
        def __init__(self, timeout=20):
            super().__init__(timeout=timeout)
            for p in player_queue:
                self.add_item(VoteButton(p))

        async def on_timeout(self):
            await finalize_captains(ctx, vote_counts)

    await ctx.send("🗳️ Click a button to vote for captains (you can only vote once):", view=VotingView())


async def finalize_captains(ctx, vote_counts):
    # Get top two players
    if len(vote_counts) < 2:
        await ctx.send("⚠️ Not enough votes. Picking captains randomly.")
        chosen = random.sample(player_queue, 2)
    else:
        chosen = [player for player, _ in vote_counts.most_common(2)]

    captains.clear()
    captains.extend(chosen)

    await ctx.send(f"🏆 Captains selected:\n1️⃣ {captains[0].mention}\n2️⃣ {captains[1].mention}")

    await pick_players(ctx)

async def pick_players(ctx):
    remaining = [p for p in player_queue if p not in captains]
    turn_order = [captains[0], captains[1], captains[1], captains[0], captains[0], captains[1], captains[0]]
    pick_index = 0

    async def prompt_next_pick():
        nonlocal pick_index
        if pick_index >= len(turn_order):
            # One player left, assign to team2
            team2.append(remaining[0])
            chosen_map = random.choice(map_pool)
            await ctx.send(f"🗺️ Match setup complete! Map: **{chosen_map}**")

            guild = ctx.guild
            team1_vc = discord.utils.get(guild.voice_channels, name="Team 1")
            team2_vc = discord.utils.get(guild.voice_channels, name="Team 2")

            for vc in [team1_vc, team2_vc]:
                await vc.set_permissions(guild.default_role, connect=False)

            for p in team1:
                await team1_vc.set_permissions(p, connect=True)
            for p in team2:
                await team2_vc.set_permissions(p, connect=True)
            return

        current_captain = turn_order[pick_index]
        await ctx.send(f"🎯 {current_captain.mention}, it's your turn to pick a player.")

        class PlayerSelect(Select):
            def __init__(self):
                options = [
                    discord.SelectOption(label=p.display_name, value=str(i))
                    for i, p in enumerate(remaining)
                ]
                super().__init__(placeholder="Select a player...", options=options)

            async def callback(self, interaction: discord.Interaction):
                if interaction.user != current_captain:
                    await interaction.response.send_message("❌ It's not your turn.", ephemeral=True)
                    return
                self.view.selected_index = int(self.values[0])
                await interaction.response.send_message("✅ Player selected. Click the button to confirm.", ephemeral=True)

        class ConfirmButton(Button):
            def __init__(self):
                super().__init__(label="Select", style=discord.ButtonStyle.success)

            async def callback(self, interaction: discord.Interaction):
                if interaction.user != current_captain:
                    await interaction.response.send_message("❌ You can't confirm this pick.", ephemeral=True)
                    return
                index = self.view.selected_index
                pick = remaining.pop(index)
                if current_captain == captains[0]:
                    team1.append(pick)
                else:
                    team2.append(pick)
                await ctx.send(f"✅ {pick.display_name} picked by {current_captain.display_name}")
                self.view.stop()

        class PickView(View):
            def __init__(self):
                super().__init__(timeout=30)
                self.selected_index = None
                self.add_item(PlayerSelect())
                self.add_item(ConfirmButton())

        view = PickView()
        await ctx.send("Select a player from the dropdown and confirm your pick:", view=view)
        await view.wait()
        pick_index += 1
        await prompt_next_pick()

    await prompt_next_pick()

@bot.command()
async def resetqueue(ctx):
    allowed_roles = ["Owner", "COM MODERATOR", "COM ADMIN", "COM CAPTAIN"]
    user_roles = [role.name for role in ctx.author.roles]

    if not any(role in user_roles for role in allowed_roles):
        await ctx.send("❌ You do not have the required role to use this command.", delete_after=5)
        return

    reset()
    await ctx.send("✅ Queue has been reset! You can now join again.")

def reset():
    player_queue.clear()
    captains.clear()
    team1.clear()
    team2.clear()

@bot.command()
async def queue(ctx):
    if not player_queue:
        await ctx.send("❌ The queue is currently empty.")
    else:
        queue_list = "\n".join([f"{i+1}. {member.display_name}" for i, member in enumerate(player_queue)])
        await ctx.send(f"📋 Current Queue:\n{queue_list}")

@bot.command()
async def help(ctx):
    help_message = """
**Available Commands (use ! instead of /):**

🔹 !register – Register yourself for the game.
🔹 !join – Join the game queue (must be in Queue 1 VC).
🔹 !resetqueue – Reset the game queue. (Admins only)
🔹 !queue – View the current queue.
"""
    await ctx.send(help_message)

bot.run("Token here")
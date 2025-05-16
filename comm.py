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
captain_votes = {}

# Bot color scheme
PRIMARY_COLOR = 0x3498db  # Blue
SUCCESS_COLOR = 0x2ecc71  # Green
WARNING_COLOR = 0xe74c3c  # Red
INFO_COLOR = 0xf1c40f     # Yellow

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
    queue_vc = discord.utils.get(guild.voice_channels, name="VC1")
    text_channel = discord.utils.get(guild.text_channels, name="queue-1-chat")

    if not queue_vc or not text_channel:
        return

    if after.channel == queue_vc:
        overwrite = discord.PermissionOverwrite()
        overwrite.read_messages = True
        overwrite.send_messages = True
        await text_channel.set_permissions(member, overwrite=overwrite)
        
        # Notify when someone joins VC1
        embed = discord.Embed(
            title="Voice Channel Joined",
            description=f"{member.mention} has joined the VC1 channel. Use `/join` to join the queue!",
            color=INFO_COLOR
        )
        embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
        await text_channel.send(embed=embed)
        
    elif before.channel == queue_vc and after.channel != queue_vc:
        await text_channel.set_permissions(member, overwrite=None)
        
        # Remove player from queue if they leave VC1
        if member in player_queue:
            player_queue.remove(member)
            embed = discord.Embed(
                title="Queue Update",
                description=f"{member.mention} has left VC1 and was removed from the queue.",
                color=WARNING_COLOR
            )
            await text_channel.send(embed=embed)

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
        embed = discord.Embed(
            title="Wrong Channel",
            description="❌ You can only use this command in the #queue-1-chat channel.",
            color=WARNING_COLOR
        )
        await ctx.send(embed=embed, delete_after=5)
        return

    voice_state = ctx.author.voice
    if not voice_state or not voice_state.channel or voice_state.channel.name != "VC1":
        embed = discord.Embed(
            title="Not in Voice Channel",
            description="❌ You must be in the **VC1** voice channel to join the queue.",
            color=WARNING_COLOR
        )
        await ctx.send(embed=embed, delete_after=5)
        return

    if ctx.author in player_queue:
        embed = discord.Embed(
            title="Already in Queue",
            description="You are already in the queue.",
            color=INFO_COLOR
        )
        await ctx.send(embed=embed)
    elif len(player_queue) >= 10:
        embed = discord.Embed(
            title="Queue Full",
            description="The queue is currently full (10/10).",
            color=WARNING_COLOR
        )
        await ctx.send(embed=embed)
    else:
        player_queue.append(ctx.author)
        
        # Display fancy queue status with progress bar
        progress = len(player_queue)
        progress_bar = "▰" * progress + "▱" * (10 - progress)
        
        embed = discord.Embed(
            title="Queue Update",
            description=f"{ctx.author.mention} joined the queue!\n\n**Queue Status:** {progress_bar} ({progress}/10)",
            color=PRIMARY_COLOR
        )
        embed.set_thumbnail(url=ctx.author.avatar.url if ctx.author.avatar else ctx.author.default_avatar.url)
        await ctx.send(embed=embed)

    if len(player_queue) == 10:
        embed = discord.Embed(
            title="Queue Full!",
            description="🎮 Queue is now full! Voting for captains is starting...",
            color=SUCCESS_COLOR
        )
        await ctx.send(embed=embed)
        await start_captain_voting(ctx)

async def start_captain_voting(ctx):
    global captain_votes
    captain_votes = Counter()

    # Create an embed for voting
    embed = discord.Embed(
        title="Captain Voting",
        description="Vote for players you want as team captains.\nThe top 2 players with the most votes will be selected as captains.",
        color=PRIMARY_COLOR
    )
    embed.add_field(name="How to Vote", value="Click on a player's button below to cast your vote.", inline=False)
    embed.add_field(name="Time Remaining", value="You have 20 seconds to vote!", inline=False)
    embed.set_footer(text="You can only vote once")

    class VoteButton(Button):
        def __init__(self, player):
            super().__init__(
                label=player.display_name, 
                style=discord.ButtonStyle.primary,
                custom_id=f"vote_{player.id}"
            )
            self.player = player

        async def callback(self, interaction: discord.Interaction):
            if interaction.user not in player_queue:
                await interaction.response.send_message("❌ You are not in the queue.", ephemeral=True)
                return
                
            # Check if user already voted
            for voter, candidate in list(getattr(self.view, 'votes', {}).items()):
                if voter == interaction.user:
                    await interaction.response.send_message(f"❌ You already voted for {candidate.display_name}", ephemeral=True)
                    return

            # Record vote
            captain_votes[self.player] += 1
            if not hasattr(self.view, 'votes'):
                self.view.votes = {}
            self.view.votes[interaction.user] = self.player
            
            await interaction.response.send_message(
                f"✅ You voted for {self.player.display_name}", 
                ephemeral=True
            )

    class VotingView(View):
        def __init__(self, timeout=20):
            super().__init__(timeout=timeout)
            self.votes = {}
            
            # Create a row of buttons, 5 per row maximum
            for i, p in enumerate(player_queue):
                self.add_item(VoteButton(p))

        async def on_timeout(self):
            await finalize_captains(ctx, captain_votes)

    await ctx.send(embed=embed, view=VotingView())

async def finalize_captains(ctx, vote_counts):
    if len(vote_counts) < 2:
        chosen = random.sample(player_queue, 2)
        
        embed = discord.Embed(
            title="Random Captain Selection",
            description="⚠️ Not enough votes received. Captains have been selected randomly.",
            color=WARNING_COLOR
        )
    else:
        chosen = [player for player, _ in vote_counts.most_common(2)]
        
        # Create vote results display
        vote_results = "\n".join([f"{player.display_name}: {count} votes" for player, count in vote_counts.most_common()])
        
        embed = discord.Embed(
            title="Captain Selection Results",
            description="The following captains have been selected based on votes:",
            color=SUCCESS_COLOR
        )
        embed.add_field(name="Vote Results", value=vote_results, inline=False)

    captains.clear()
    captains.extend(chosen)
    
    # Create embeds for captains
    captain_embed = discord.Embed(
        title="🏆 Team Captains Selected",
        description="The following players have been selected as team captains:",
        color=SUCCESS_COLOR
    )
    
    captain_embed.add_field(
        name="Team A Captain",
        value=f"{captains[0].mention} ({captains[0].display_name})",
        inline=True
    )
    
    captain_embed.add_field(
        name="Team B Captain",
        value=f"{captains[1].mention} ({captains[1].display_name})",
        inline=True
    )
    
    captain_embed.set_footer(text="Player selection will begin shortly")
    
    # Add the existing embed fields if present
    if len(vote_counts) >= 2:
        for field in embed.fields:
            if field.name != "Team A Captain" and field.name != "Team B Captain":
                captain_embed.add_field(name=field.name, value=field.value, inline=field.inline)
    
    # Create buttons for captain swap
    class CaptainSwapView(View):
        def __init__(self, timeout=30):
            super().__init__(timeout=timeout)
            
        @discord.ui.button(label="Swap Captains", style=discord.ButtonStyle.secondary, custom_id="swap_captains")
        async def swap_captains(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user not in captains:
                await interaction.response.send_message("❌ Only captains can request a swap.", ephemeral=True)
                return
            
            # Create confirmation buttons
            class ConfirmSwapView(View):
                def __init__(self, timeout=30):
                    super().__init__(timeout=timeout)
                    self.value = None
                    
                @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
                async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
                    if interaction.user != captains[0] and interaction.user != captains[1]:
                        await interaction.response.send_message("❌ Only captains can confirm.", ephemeral=True)
                        return
                        
                    self.value = True
                    self.stop()
                    await interaction.response.send_message("✅ Swap confirmed!", ephemeral=True)
                    
                @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
                async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
                    if interaction.user != captains[0] and interaction.user != captains[1]:
                        await interaction.response.send_message("❌ Only captains can cancel.", ephemeral=True)
                        return
                        
                    self.value = False
                    self.stop()
                    await interaction.response.send_message("❌ Swap canceled.", ephemeral=True)
            
            # Notify the other captain
            other_captain = captains[1] if interaction.user == captains[0] else captains[0]
            
            confirm_embed = discord.Embed(
                title="Captain Swap Request",
                description=f"{interaction.user.mention} has requested to swap with a random player instead of being captain. {other_captain.mention}, do you agree?",
                color=WARNING_COLOR
            )
            
            view = ConfirmSwapView()
            message = await ctx.send(embed=confirm_embed, view=view)
            await view.wait()
            
            if view.value:
                # Perform the swap - replace the captain with a random player
                remaining_players = [p for p in player_queue if p not in captains]
                if not remaining_players:
                    await ctx.send("❌ No players available for swap.")
                    return
                
                new_captain = random.choice(remaining_players)
                old_captain_index = 0 if interaction.user == captains[0] else 1
                
                # Remove new captain from remaining players and add old captain
                player_queue.remove(new_captain)
                player_queue.append(captains[old_captain_index])
                
                # Update captains list
                captains[old_captain_index] = new_captain
                
                swap_complete_embed = discord.Embed(
                    title="Captain Swap Complete",
                    description=f"{interaction.user.mention} has been replaced with {new_captain.mention} as captain!",
                    color=SUCCESS_COLOR
                )
                
                # Update captain display
                captain_display_embed = discord.Embed(
                    title="🏆 Updated Team Captains",
                    description="The team captains are now:",
                    color=SUCCESS_COLOR
                )
                
                captain_display_embed.add_field(
                    name="Team A Captain",
                    value=f"{captains[0].mention} ({captains[0].display_name})",
                    inline=True
                )
                
                captain_display_embed.add_field(
                    name="Team B Captain",
                    value=f"{captains[1].mention} ({captains[1].display_name})",
                    inline=True
                )
                
                await ctx.send(embed=swap_complete_embed)
                await ctx.send(embed=captain_display_embed)
                
                # Delete the confirmation message
                await message.delete()
            else:
                await message.edit(content="Swap request declined.", embed=None, view=None)
                
        @discord.ui.button(label="Continue", style=discord.ButtonStyle.primary, custom_id="continue_picking")
        async def continue_to_picks(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user not in captains:
                await interaction.response.send_message("❌ Only captains can continue to picks.", ephemeral=True)
                return
                
            self.stop()
            await interaction.response.send_message("✅ Continuing to player selection!", ephemeral=True)
            
            # Start player picks
            await pick_players(ctx)
    
    # Send the captain selection message with swap option
    await ctx.send(embed=captain_embed, view=CaptainSwapView())

async def pick_players(ctx):
    remaining = [p for p in player_queue if p not in captains]
    turn_order = [captains[0], captains[1], captains[1], captains[0], captains[0], captains[1], captains[0]]
    pick_index = 0
    
    # Initialize teams with captains
    team1.clear()
    team2.clear()
    team1.append(captains[0])
    team2.append(captains[1])

    async def prompt_next_pick():
        nonlocal pick_index
        if pick_index >= len(turn_order):
            # Handle last player
            last_player = remaining[0]
            if len(team1) < len(team2):
                team1.append(last_player)
            else:
                team2.append(last_player)
                
            # Display final team rosters before map voting
            await display_teams(ctx)
            await start_map_voting(ctx)
            return

        current_captain = turn_order[pick_index]
        
        # Create modern embed for player selection
        pick_embed = discord.Embed(
            title="Player Selection",
            description=f"🎯 {current_captain.mention}, it's your turn to pick a player.",
            color=PRIMARY_COLOR
        )
        
        # Show current team compositions
        team1_players = ", ".join([p.display_name for p in team1]) or "None"
        team2_players = ", ".join([p.display_name for p in team2]) or "None"
        
        pick_embed.add_field(
            name=f"Team A ({len(team1)}/5)",
            value=team1_players,
            inline=True
        )
        
        pick_embed.add_field(
            name=f"Team B ({len(team2)}/5)",
            value=team2_players,
            inline=True
        )
        
        # Show remaining players
        remaining_players = ", ".join([p.display_name for p in remaining])
        pick_embed.add_field(
            name="Remaining Players",
            value=remaining_players,
            inline=False
        )
        
        await ctx.send(embed=pick_embed)

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
                    
                # Create a nice embed for the pick
                pick_embed = discord.Embed(
                    title="Player Picked",
                    description=f"✅ **{pick.display_name}** was picked by {current_captain.display_name}",
                    color=SUCCESS_COLOR
                )
                
                # Add player avatar if available
                if pick.avatar:
                    pick_embed.set_thumbnail(url=pick.avatar.url)
                
                await ctx.send(embed=pick_embed)
                self.view.stop()

        class PickView(View):
            def __init__(self):
                super().__init__(timeout=30)
                self.selected_index = None
                self.add_item(PlayerSelect())
                self.add_item(ConfirmButton())

        view = PickView()
        
        select_embed = discord.Embed(
            title="Select Player",
            description="Use the dropdown menu to select a player and confirm your pick.",
            color=PRIMARY_COLOR
        )
        await ctx.send(embed=select_embed, view=view)
        await view.wait()
        pick_index += 1
        await prompt_next_pick()

    await prompt_next_pick()

async def display_teams(ctx):
    """Display the final team compositions with a modern UI"""
    team_embed = discord.Embed(
        title="🎮 Final Team Compositions",
        description="The teams have been formed! Good luck and have fun!",
        color=SUCCESS_COLOR
    )
    
    # Format team A with captain first
    team_a_captain = team1[0]
    team_a_members = "\n".join([
        f"👑 **{team_a_captain.display_name}** (Captain)" if p == team_a_captain else f"• {p.display_name}"
        for p in team1
    ])
    
    # Format team B with captain first
    team_b_captain = team2[0]
    team_b_members = "\n".join([
        f"👑 **{team_b_captain.display_name}** (Captain)" if p == team_b_captain else f"• {p.display_name}"
        for p in team2
    ])
    
    team_embed.add_field(
        name="🔵 Team A",
        value=team_a_members,
        inline=True
    )
    
    team_embed.add_field(
        name="🔴 Team B",
        value=team_b_members,
        inline=True
    )
    
    # Add a versus section in the middle
    team_embed.add_field(
        name="Match Details",
        value="**Best of 3**\nMap will be selected by vote",
        inline=False
    )
    
    await ctx.send(embed=team_embed)

async def start_map_voting(ctx):
    vote_counts = Counter()

    # Create map voting embed
    map_embed = discord.Embed(
        title="🗺️ Map Voting",
        description="Vote for the map you want to play on.\nThe map with the most votes will be selected.",
        color=PRIMARY_COLOR
    )
    
    map_embed.add_field(
        name="Available Maps",
        value="\n".join([f"• {m}" for m in map_pool]),
        inline=False
    )
    
    map_embed.add_field(
        name="How to Vote",
        value="Click on a map button below to cast your vote.",
        inline=False
    )
    
    map_embed.set_footer(text="You can only vote once")

    class MapVoteButton(Button):
        def __init__(self, map_name):
            super().__init__(label=map_name, style=discord.ButtonStyle.secondary)
            self.map_name = map_name

        async def callback(self, interaction: discord.Interaction):
            if interaction.user not in player_queue:
                await interaction.response.send_message("❌ You are not in the queue.", ephemeral=True)
                return

            if hasattr(interaction.user, 'voted'):
                await interaction.response.send_message("❌ You have already voted.", ephemeral=True)
                return

            vote_counts[self.map_name] += 1
            setattr(interaction.user, 'voted', True)
            await interaction.response.send_message(f"✅ You voted for map **{self.map_name}**.", ephemeral=True)

    class MapVotingView(View):
        def __init__(self, timeout=20):
            super().__init__(timeout=timeout)
            for m in map_pool:
                self.add_item(MapVoteButton(m))

        async def on_timeout(self):
            await finalize_map_vote(ctx, vote_counts)

    await ctx.send(embed=map_embed, view=MapVotingView())

async def finalize_map_vote(ctx, vote_counts):
    if not vote_counts:
        chosen_map = random.choice(map_pool)
        
        result_embed = discord.Embed(
            title="Random Map Selection",
            description=f"⚠️ No votes were cast. A map has been randomly selected.",
            color=WARNING_COLOR
        )
        result_embed.add_field(
            name="Selected Map",
            value=f"**{chosen_map}**",
            inline=False
        )
        
        await ctx.send(embed=result_embed)
    else:
        top_votes = vote_counts.most_common()
        highest = top_votes[0][1]
        top_maps = [m for m, v in top_votes if v == highest]
        chosen_map = random.choice(top_maps)
        
        # Create vote results display
        vote_results = "\n".join([f"**{map_name}**: {count} votes" for map_name, count in top_votes])
        
        result_embed = discord.Embed(
            title="Map Selection Results",
            description=f"The following map has been selected based on votes:",
            color=SUCCESS_COLOR
        )
        
        result_embed.add_field(
            name="Selected Map",
            value=f"**{chosen_map}**",
            inline=False
        )
        
        result_embed.add_field(
            name="Vote Results", 
            value=vote_results, 
            inline=False
        )
        
        await ctx.send(embed=result_embed)

    guild = ctx.guild
    team1_vc = discord.utils.get(guild.voice_channels, name="Team 1")
    team2_vc = discord.utils.get(guild.voice_channels, name="Team 2")

    # Check if the voice channels exist
    if not team1_vc or not team2_vc:
        error_embed = discord.Embed(
            title="Voice Channel Error",
            description="❌ Could not find Team 1 or Team 2 voice channels. Please ask an admin to create them.",
            color=WARNING_COLOR
        )
        await ctx.send(embed=error_embed)
        return

    # Set permissions for voice channels
    for vc in [team1_vc, team2_vc]:
        await vc.set_permissions(guild.default_role, connect=False)

    # Move players to their team voice channels
    for p in team1:
        await team1_vc.set_permissions(p, connect=True)
        if p.voice and p.voice.channel:
            try:
                await p.move_to(team1_vc)
            except discord.HTTPException:
                pass
                
    for p in team2:
        await team2_vc.set_permissions(p, connect=True)
        if p.voice and p.voice.channel:
            try:
                await p.move_to(team2_vc)
            except discord.HTTPException:
                pass
                
    # Final message
    final_embed = discord.Embed(
        title="Match Ready!",
        description=f"Teams have been formed and map **{chosen_map}** has been selected.\nPlayers have been moved to their team voice channels.",
        color=SUCCESS_COLOR
    )
    final_embed.set_footer(text="Good luck and have fun!")
    
    await ctx.send(embed=final_embed)

@bot.command()
async def resetqueue(ctx):
    allowed_roles = ["Owner", "COM MODERATOR", "COM ADMIN", "COM CAPTAIN"]
    user_roles = [role.name for role in ctx.author.roles]

    if not any(role in user_roles for role in allowed_roles):
        embed = discord.Embed(
            title="Permission Error",
            description="❌ You do not have the required role to use this command.",
            color=WARNING_COLOR
        )
        await ctx.send(embed=embed, delete_after=5)
        return

    reset()
    
    embed = discord.Embed(
        title="Queue Reset",
        description="✅ The queue has been reset successfully. Players can now join again.",
        color=SUCCESS_COLOR
    )
    await ctx.send(embed=embed)

def reset():
    """Reset all game state variables"""
    player_queue.clear()
    captains.clear()
    team1.clear()
    team2.clear()
    if 'captain_votes' in globals():
        captain_votes.clear()

@bot.command()
async def queue(ctx):
    if not player_queue:
        embed = discord.Embed(
            title="Queue Status",
            description="❌ The queue is currently empty.",
            color=WARNING_COLOR
        )
        await ctx.send(embed=embed)
    else:
        # Create a progress bar
        progress = len(player_queue)
        progress_bar = "▰" * progress + "▱" * (10 - progress)
        
        queue_list = "\n".join([f"{i+1}. {member.display_name}" for i, member in enumerate(player_queue)])
        
        embed = discord.Embed(
            title="Current Queue",
            description=f"**Queue Status:** {progress_bar} ({progress}/10)",
            color=PRIMARY_COLOR
        )
        
        embed.add_field(
            name="Players in Queue",
            value=queue_list,
            inline=False
        )
        
        await ctx.send(embed=embed)

@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="Tournament Bot Commands",
        description="These are the available commands for the tournament bot:",
        color=PRIMARY_COLOR
    )
    
    embed.add_field(
        name="Player Commands",
        value="""
🔹 `!register` – Register yourself for the game.
🔹 `!join` – Join the game queue (must be in VC1).
🔹 `!queue` – View the current queue status.
🔹 `!help` – Show this help message.
""",
        inline=False
    )
    
    embed.add_field(
        name="Admin Commands",
        value="🔹 `!resetqueue` – Reset the game queue (Admins only).",
        inline=False
    )
    
    embed.set_footer(text="Made for tournament management")
    
    await ctx.send(embed=embed)

# Make sure to replace with your actual bot token
bot.run("YOUR_BOT_TOKEN_HERE")

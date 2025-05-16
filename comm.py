"""
Discord Tournament Bot

SETUP REQUIREMENTS:
------------------

1. Database Configuration:
   - MySQL database is required
   - Update DB_CONFIG (around line 85) with your database credentials
   - No need to create tables manually, they will be created automatically

2. Required Discord Roles:
   - "UNRANKED" - Given to players when they register
   - Admin roles that can manage queues: "Owner", "COM MODERATOR", "COM ADMIN", "COM CAPTAIN"

3. Required Channels:
   - Text channel: "com-register" - For user registration
   - Voice channels: "Queue 1", "Queue 2", etc. - For players to join queues
   - Text channels: "queue-1-chat", "queue-2-chat", etc. - For queue communication
   - Team voice channels will be created automatically: "Team 1A", "Team 1B", "Team 2A", "Team 2B", etc.

4. Required Bot Permissions:
   - Manage Channels - To create team voice channels
   - Manage Roles - To assign roles during registration
   - Move Members - To move players to team channels
   - Send Messages - To communicate in text channels
   - Manage Messages - To delete registration messages
   - Read Message History - To delete registration messages
   - Add Reactions - For interactive buttons

5. Bot Token:
   - Replace "YOUR_BOT_TOKEN_HERE" at the end of this file with your actual bot token

6. Commands:
   - !register - Register for tournaments
   - !join [queue_number] - Join a queue
   - !queue [queue_number] - View queue status
   - !resetqueue [queue_number] - Reset a queue (admin only)
   - !win team1/team2 - Report match results (admin only)
   - !score [@user] - View player stats
   - !leaderboard - View top players
   - !stats [queue_number] - View queue stats
   - !queues - View all active queues
   - !help - Show commands
"""

import discord
from discord.ext import tasks
from discord import Option, SlashCommandGroup
from discord.commands import slash_command, permissions
import random
from discord.ui import Button, View, Select
from collections import Counter
import datetime
import logging
import os
import db  # Import the database module

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("discord_bot")

intents = discord.Intents.default()
intents.members = True
intents.voice_states = True
intents.guilds = True
intents.messages = True
intents.message_content = True

# Initialize bot with slash commands
bot = discord.Bot(intents=intents, debug_guilds=None)  # Set debug_guilds to specific IDs for faster command registration during development

# Bot color scheme
PRIMARY_COLOR = 0x3498db  # Blue
SUCCESS_COLOR = 0x2ecc71  # Green
WARNING_COLOR = 0xe74c3c  # Red
INFO_COLOR = 0xf1c40f     # Yellow

# List of maps for voting
map_pool = ["Plaza", "Castello", "Village", "Canals", "Legacy", "Raid", "Grounded", "Bureau"]

# Queue class to manage individual queue state
class Queue:
    def __init__(self, queue_number):
        self.queue_number = queue_number
        self.players = []
        self.captains = []
        self.team1 = []
        self.team2 = []
        self.captain_votes = Counter()
        self.map_votes = Counter()
        self.voted_players = set()  # Track players who have voted for maps
        self.is_active = False
        self.current_pick_index = 0
        self.chosen_map = None
        
        # Channel names
        self.vc_name = f"Queue {queue_number}"
        self.chat_name = f"queue-{queue_number}-chat"
        self.team1_vc_name = f"Team {queue_number}A"
        self.team2_vc_name = f"Team {queue_number}B"
        
    def reset(self):
        """Reset all game state variables for this queue"""
        self.players.clear()
        self.captains.clear()
        self.team1.clear()
        self.team2.clear()
        self.captain_votes.clear()
        self.map_votes.clear()
        self.voted_players.clear()
        self.is_active = False
        self.current_pick_index = 0
        self.chosen_map = None
        self.match_id = None
        self.match_reported = False
        
    def is_full(self):
        """Check if queue has 10 players"""
        return len(self.players) >= 10

# Dictionary to store all queue instances
queues = {}

@tasks.loop(seconds=10)
async def purge_com_register():
    await bot.wait_until_ready()
    for guild in bot.guilds:
        channel = discord.utils.get(guild.text_channels, name="com-register")
        if channel:
            try:
                await channel.purge(limit=100)
            except discord.Forbidden:
                logger.warning(f"⚠️ Missing permissions to purge in {channel.name}")
            except discord.HTTPException as e:
                logger.error(f"❌ Failed to purge messages in {channel.name}: {e}")

# Initialize queues on startup
@bot.event
async def on_ready():
    logger.info(f"✅ Bot is ready. Logged in as {bot.user}")
    
    # Initialize database
    try:
        db_init_success = await db.initialize_database()
        if db_init_success:
            logger.info("✅ Database initialized successfully")
        else:
            logger.error("❌ Failed to initialize database")
            logger.info("Check your database configuration in DB_CONFIG. Set environment variables (DB_HOST, DB_USER, DB_PASSWORD, DB_DATABASE) for secure configuration.")
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}")
        logger.info("The bot will continue to run, but database functionality may not work correctly.")
    
    # Find all queue voice channels across all guilds and initialize queue objects
    try:
        queue_count = 0
        for guild in bot.guilds:
            for vc in guild.voice_channels:
                if vc.name.startswith("Queue "):
                    try:
                        queue_num = int(vc.name.split(" ")[1])
                        if queue_num not in queues:
                            queues[queue_num] = Queue(queue_num)
                            queue_count += 1
                            logger.info(f"✅ Initialized Queue {queue_num}")
                    except ValueError:
                        logger.warning(f"Found voice channel with invalid queue number format: {vc.name}")
        
        if queue_count == 0:
            logger.warning("No queue voice channels found. Create voice channels named 'Queue 1', 'Queue 2', etc.")
    except Exception as e:
        logger.error(f"Error initializing queues: {e}")
    
    # Create team voice channels if they don't exist
    for guild in bot.guilds:
        for queue_num in queues:
            team1_vc_name = queues[queue_num].team1_vc_name
            team2_vc_name = queues[queue_num].team2_vc_name
            
            team1_vc = discord.utils.get(guild.voice_channels, name=team1_vc_name)
            team2_vc = discord.utils.get(guild.voice_channels, name=team2_vc_name)
            
            try:
                if not team1_vc:
                    await guild.create_voice_channel(team1_vc_name)
                    print(f"✅ Created voice channel: {team1_vc_name}")
                if not team2_vc:
                    await guild.create_voice_channel(team2_vc_name)
                    print(f"✅ Created voice channel: {team2_vc_name}")
            except discord.Forbidden:
                print(f"❌ Missing permissions to create voice channels in {guild.name}")
            except Exception as e:
                print(f"❌ Error creating voice channels: {e}")
    
    purge_com_register.start()

@bot.event
async def on_voice_state_update(member, before, after):
    guild = member.guild
    
    # Handle joining a queue channel
    if after.channel and after.channel.name.startswith("Queue "):
        try:
            queue_num = int(after.channel.name.split(" ")[1])
            text_channel = discord.utils.get(guild.text_channels, name=f"queue-{queue_num}-chat")
            
            if not text_channel:
                return
                
            # Initialize queue if not already done
            if queue_num not in queues:
                queues[queue_num] = Queue(queue_num)
                
            # Grant chat permissions
            overwrite = discord.PermissionOverwrite()
            overwrite.read_messages = True
            overwrite.send_messages = True
            await text_channel.set_permissions(member, overwrite=overwrite)
            
            # Notify when someone joins the queue voice channel
            embed = discord.Embed(
                title="Voice Channel Joined",
                description=f"{member.mention} has joined the {after.channel.name} channel. Use `/join {queue_num}` to join the queue!",
                color=INFO_COLOR
            )
            embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
            await text_channel.send(embed=embed)
        except ValueError:
            pass
    
    # Handle leaving a queue channel
    if before.channel and before.channel.name.startswith("Queue "):
        try:
            queue_num = int(before.channel.name.split(" ")[1])
            text_channel = discord.utils.get(guild.text_channels, name=f"queue-{queue_num}-chat")
            
            if not text_channel:
                return
                
            # Remove chat permissions
            await text_channel.set_permissions(member, overwrite=None)
            
            # Remove player from queue if they leave the voice channel
            if queue_num in queues and member in queues[queue_num].players:
                queues[queue_num].players.remove(member)
                embed = discord.Embed(
                    title="Queue Update",
                    description=f"{member.mention} has left {before.channel.name} and was removed from the queue.",
                    color=WARNING_COLOR
                )
                await text_channel.send(embed=embed)
        except ValueError:
            pass

@bot.slash_command(
    name="register",
    description="Register yourself for the tournament system"
)
async def register(ctx):
    if ctx.channel.name != "com-register":
        embed = discord.Embed(
            title="Wrong Channel",
            description="❌ You can only register in the #com-register channel.",
            color=WARNING_COLOR
        )
        await ctx.respond(embed=embed, ephemeral=True)
        return

    unranked_role = discord.utils.get(ctx.guild.roles, name="UNRANKED")
    if not unranked_role:
        embed = discord.Embed(
            title="Role Missing",
            description="❌ 'UNRANKED' role not found. Please ask an admin to create it.",
            color=WARNING_COLOR
        )
        await ctx.respond(embed=embed, ephemeral=True)
        return

    if unranked_role in ctx.author.roles:
        embed = discord.Embed(
            title="Already Registered",
            description="✅ You are already registered!",
            color=INFO_COLOR
        )
        await ctx.respond(embed=embed, ephemeral=True)
    else:
        await ctx.author.add_roles(unranked_role)
        embed = discord.Embed(
            title="Registration Successful",
            description=f"✅ {ctx.author.mention}, you have been registered and given the UNRANKED role!",
            color=SUCCESS_COLOR
        )
        await ctx.respond(embed=embed, ephemeral=True)

@bot.slash_command(
    name="join",
    description="Join a queue for a tournament match"
)
async def join(
    ctx, 
    queue_num: Option(int, "Queue number to join", required=False, default=None)
):
    # Get queue number from channel name if not provided
    if queue_num is None:
        if ctx.channel.name.startswith("queue-") and "-chat" in ctx.channel.name:
            try:
                queue_num = int(ctx.channel.name.split("-")[1])
            except ValueError:
                embed = discord.Embed(
                    title="Invalid Queue",
                    description="❌ Could not determine queue number from channel name.",
                    color=WARNING_COLOR
                )
                await ctx.respond(embed=embed, ephemeral=True)
                return
        else:
            embed = discord.Embed(
                title="Queue Number Required",
                description="❌ Please specify a queue number (e.g., `/join 1`).",
                color=WARNING_COLOR
            )
            await ctx.respond(embed=embed, ephemeral=True)
            return
    
    # Check if we're in the correct channel
    expected_channel = f"queue-{queue_num}-chat"
    if ctx.channel.name != expected_channel:
        embed = discord.Embed(
            title="Wrong Channel",
            description=f"❌ You can only use this command in the #{expected_channel} channel.",
            color=WARNING_COLOR
        )
        await ctx.respond(embed=embed, ephemeral=True)
        return

    # Check if user is in the correct voice channel
    voice_state = ctx.author.voice
    expected_vc = f"Queue {queue_num}"
    if not voice_state or not voice_state.channel or voice_state.channel.name != expected_vc:
        embed = discord.Embed(
            title="Not in Voice Channel",
            description=f"❌ You must be in the **{expected_vc}** voice channel to join this queue.",
            color=WARNING_COLOR
        )
        await ctx.respond(embed=embed, ephemeral=True)
        return
    
    # Initialize queue if it doesn't exist
    if queue_num not in queues:
        queues[queue_num] = Queue(queue_num)
    
    queue = queues[queue_num]

    if ctx.author in queue.players:
        embed = discord.Embed(
            title="Already in Queue",
            description=f"You are already in Queue {queue_num}.",
            color=INFO_COLOR
        )
        await ctx.respond(embed=embed)
    elif len(queue.players) >= 10:
        embed = discord.Embed(
            title="Queue Full",
            description=f"Queue {queue_num} is currently full (10/10).",
            color=WARNING_COLOR
        )
        await ctx.respond(embed=embed)
    else:
        queue.players.append(ctx.author)
        
        # Display fancy queue status with progress bar
        progress = len(queue.players)
        progress_bar = "▰" * progress + "▱" * (10 - progress)
        
        embed = discord.Embed(
            title=f"Queue {queue_num} Update",
            description=f"{ctx.author.mention} joined the queue!\n\n**Queue Status:** {progress_bar} ({progress}/10)",
            color=PRIMARY_COLOR
        )
        embed.set_thumbnail(url=ctx.author.avatar.url if ctx.author.avatar else ctx.author.default_avatar.url)
        await ctx.respond(embed=embed)

    if queue.is_full():
        embed = discord.Embed(
            title=f"Queue {queue_num} Full!",
            description="🎮 Queue is now full! Voting for captains is starting...",
            color=SUCCESS_COLOR
        )
        await ctx.respond(embed=embed)
        await start_captain_voting(ctx, queue_num)

async def start_captain_voting(ctx, queue_num):
    # Get the queue
    if queue_num not in queues:
        await ctx.send(f"❌ Queue {queue_num} does not exist.")
        return
        
    queue = queues[queue_num]
    queue.captain_votes.clear()

    # Create an embed for voting
    embed = discord.Embed(
        title=f"Queue {queue_num} - Captain Voting",
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
            if interaction.user not in queue.players:
                await interaction.response.send_message("❌ You are not in the queue.", ephemeral=True)
                return
                
            # Check if user already voted
            for voter, candidate in list(getattr(self.view, 'votes', {}).items()):
                if voter == interaction.user:
                    await interaction.response.send_message(f"❌ You already voted for {candidate.display_name}", ephemeral=True)
                    return

            # Record vote
            queue.captain_votes[self.player] += 1
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
            for i, p in enumerate(queue.players):
                self.add_item(VoteButton(p))

        async def on_timeout(self):
            await finalize_captains(ctx, queue_num)

    await ctx.send(embed=embed, view=VotingView())

async def finalize_captains(ctx, queue_num):
    # Get the queue
    if queue_num not in queues:
        await ctx.send(f"❌ Queue {queue_num} does not exist.")
        return
        
    queue = queues[queue_num]
    vote_counts = queue.captain_votes
    
    if len(vote_counts) < 2:
        chosen = random.sample(queue.players, 2)
        
        embed = discord.Embed(
            title=f"Queue {queue_num} - Random Captain Selection",
            description="⚠️ Not enough votes received. Captains have been selected randomly.",
            color=WARNING_COLOR
        )
    else:
        chosen = [player for player, _ in vote_counts.most_common(2)]
        
        # Create vote results display
        vote_results = "\n".join([f"{player.display_name}: {count} votes" for player, count in vote_counts.most_common()])
        
        embed = discord.Embed(
            title=f"Queue {queue_num} - Captain Selection Results",
            description="The following captains have been selected based on votes:",
            color=SUCCESS_COLOR
        )
        embed.add_field(name="Vote Results", value=vote_results, inline=False)

    queue.captains.clear()
    queue.captains.extend(chosen)
    
    # Create embeds for captains
    captain_embed = discord.Embed(
        title=f"Queue {queue_num} - 🏆 Team Captains Selected",
        description="The following players have been selected as team captains:",
        color=SUCCESS_COLOR
    )
    
    captain_embed.add_field(
        name="Team A Captain",
        value=f"{queue.captains[0].mention} ({queue.captains[0].display_name})",
        inline=True
    )
    
    captain_embed.add_field(
        name="Team B Captain",
        value=f"{queue.captains[1].mention} ({queue.captains[1].display_name})",
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
            if interaction.user not in queue.captains:
                await interaction.response.send_message("❌ Only captains can request a swap.", ephemeral=True)
                return
            
            # Create confirmation buttons
            class ConfirmSwapView(View):
                def __init__(self, timeout=30):
                    super().__init__(timeout=timeout)
                    self.value = None
                    
                @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
                async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
                    if interaction.user != queue.captains[0] and interaction.user != queue.captains[1]:
                        await interaction.response.send_message("❌ Only captains can confirm.", ephemeral=True)
                        return
                        
                    self.value = True
                    self.stop()
                    await interaction.response.send_message("✅ Swap confirmed!", ephemeral=True)
                    
                @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
                async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
                    if interaction.user != queue.captains[0] and interaction.user != queue.captains[1]:
                        await interaction.response.send_message("❌ Only captains can cancel.", ephemeral=True)
                        return
                        
                    self.value = False
                    self.stop()
                    await interaction.response.send_message("❌ Swap canceled.", ephemeral=True)
            
            # Notify the other captain
            other_captain = queue.captains[1] if interaction.user == queue.captains[0] else queue.captains[0]
            
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
                remaining_players = [p for p in queue.players if p not in queue.captains]
                if not remaining_players:
                    await ctx.send("❌ No players available for swap.")
                    return
                
                new_captain = random.choice(remaining_players)
                old_captain_index = 0 if interaction.user == queue.captains[0] else 1
                
                # Remove new captain from remaining players and add old captain
                queue.players.remove(new_captain)
                queue.players.append(queue.captains[old_captain_index])
                
                # Update captains list
                queue.captains[old_captain_index] = new_captain
                
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
                    value=f"{queue.captains[0].mention} ({queue.captains[0].display_name})",
                    inline=True
                )
                
                captain_display_embed.add_field(
                    name="Team B Captain",
                    value=f"{queue.captains[1].mention} ({queue.captains[1].display_name})",
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
            if interaction.user not in queue.captains:
                await interaction.response.send_message("❌ Only captains can continue to picks.", ephemeral=True)
                return
                
            self.stop()
            await interaction.response.send_message("✅ Continuing to player selection!", ephemeral=True)
            
            # Start player picks
            await pick_players(ctx, queue_num)
    
    # Send the captain selection message with swap option
    await ctx.send(embed=captain_embed, view=CaptainSwapView())

async def pick_players(ctx, queue_num):
    # Get the queue
    if queue_num not in queues:
        await ctx.send(f"❌ Queue {queue_num} does not exist.")
        return
    
    queue = queues[queue_num]
    remaining = [p for p in queue.players if p not in queue.captains]
    turn_order = [queue.captains[0], queue.captains[1], queue.captains[1], queue.captains[0], queue.captains[0], queue.captains[1], queue.captains[0]]
    queue.current_pick_index = 0
    
    # Initialize teams with captains
    queue.team1.clear()
    queue.team2.clear()
    queue.team1.append(queue.captains[0])
    queue.team2.append(queue.captains[1])

    async def prompt_next_pick():
        if queue.current_pick_index >= len(turn_order):
            # Handle last player
            last_player = remaining[0]
            if len(queue.team1) < len(queue.team2):
                queue.team1.append(last_player)
            else:
                queue.team2.append(last_player)
                
            # Display final team rosters before map voting
            await display_teams(ctx, queue_num)
            await start_map_voting(ctx, queue_num)
            return

        current_captain = turn_order[queue.current_pick_index]
        
        # Create modern embed for player selection
        pick_embed = discord.Embed(
            title=f"Queue {queue_num} - Player Selection",
            description=f"🎯 {current_captain.mention}, it's your turn to pick a player.",
            color=PRIMARY_COLOR
        )
        
        # Show current team compositions
        team1_players = ", ".join([p.display_name for p in queue.team1]) or "None"
        team2_players = ", ".join([p.display_name for p in queue.team2]) or "None"
        
        pick_embed.add_field(
            name=f"Team A ({len(queue.team1)}/5)",
            value=team1_players,
            inline=True
        )
        
        pick_embed.add_field(
            name=f"Team B ({len(queue.team2)}/5)",
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
                if current_captain == queue.captains[0]:
                    queue.team1.append(pick)
                else:
                    queue.team2.append(pick)
                    
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
        queue.current_pick_index += 1
        await prompt_next_pick()

    await prompt_next_pick()

async def display_teams(ctx, queue_num):
    """Display the final team compositions with a modern UI"""
    # Get the queue
    if queue_num not in queues:
        await ctx.send(f"❌ Queue {queue_num} does not exist.")
        return
        
    queue = queues[queue_num]
    
    team_embed = discord.Embed(
        title=f"Queue {queue_num} - 🎮 Final Team Compositions",
        description="The teams have been formed! Good luck and have fun!",
        color=SUCCESS_COLOR
    )
    
    # Get points for all players
    team1_points = {}
    team2_points = {}
    
    # Fetch player points in parallel for better performance
    for player in queue.team1:
        points = await db.get_player_points(player.id)
        team1_points[player.id] = points
        
    for player in queue.team2:
        points = await db.get_player_points(player.id)
        team2_points[player.id] = points
        
    # Format team A with captain first and show points
    team_a_captain = queue.team1[0]
    team_a_members = "\n".join([
        f"👑 **{p.display_name}** [{team1_points[p.id]}] (Captain)" if p == team_a_captain 
        else f"• **{p.display_name}** [{team1_points[p.id]}]"
        for p in queue.team1
    ])
    
    # Format team B with captain first and show points
    team_b_captain = queue.team2[0]
    team_b_members = "\n".join([
        f"👑 **{p.display_name}** [{team2_points[p.id]}] (Captain)" if p == team_b_captain 
        else f"• **{p.display_name}** [{team2_points[p.id]}]"
        for p in queue.team2
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

async def start_map_voting(ctx, queue_num):
    # Get the queue
    if queue_num not in queues:
        await ctx.send(f"❌ Queue {queue_num} does not exist.")
        return
        
    queue = queues[queue_num]
    queue.map_votes.clear()
    queue.voted_players.clear()

    # Create map voting embed
    map_embed = discord.Embed(
        title=f"Queue {queue_num} - 🗺️ Map Voting",
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
            if interaction.user not in queue.players:
                await interaction.response.send_message("❌ You are not in the queue.", ephemeral=True)
                return

            if interaction.user in queue.voted_players:
                await interaction.response.send_message("❌ You have already voted.", ephemeral=True)
                return

            queue.map_votes[self.map_name] += 1
            queue.voted_players.add(interaction.user)
            await interaction.response.send_message(f"✅ You voted for map **{self.map_name}**.", ephemeral=True)

    class MapVotingView(View):
        def __init__(self, timeout=20):
            super().__init__(timeout=timeout)
            for m in map_pool:
                self.add_item(MapVoteButton(m))

        async def on_timeout(self):
            await finalize_map_vote(ctx, queue_num)

    await ctx.send(embed=map_embed, view=MapVotingView())

async def finalize_map_vote(ctx, queue_num):
    # Get the queue
    if queue_num not in queues:
        await ctx.send(f"❌ Queue {queue_num} does not exist.")
        return
        
    queue = queues[queue_num]
    vote_counts = queue.map_votes
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
        queue.chosen_map = chosen_map
        
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
    team1_vc = discord.utils.get(guild.voice_channels, name=queue.team1_vc_name)
    team2_vc = discord.utils.get(guild.voice_channels, name=queue.team2_vc_name)

    # Check if the voice channels exist
    if not team1_vc or not team2_vc:
        error_embed = discord.Embed(
            title="Voice Channel Error",
            description=f"❌ Could not find {queue.team1_vc_name} or {queue.team2_vc_name} voice channels. Please ask an admin to create them.",
            color=WARNING_COLOR
        )
        await ctx.send(embed=error_embed)
        return

    # Set permissions for voice channels
    for vc in [team1_vc, team2_vc]:
        await vc.set_permissions(guild.default_role, connect=False)

    # Move players to their team voice channels
    for p in queue.team1:
        await team1_vc.set_permissions(p, connect=True)
        if p.voice and p.voice.channel:
            try:
                await p.move_to(team1_vc)
            except discord.HTTPException:
                pass
                
    for p in queue.team2:
        await team2_vc.set_permissions(p, connect=True)
        if p.voice and p.voice.channel:
            try:
                await p.move_to(team2_vc)
            except discord.HTTPException:
                pass
                
    # Final message
    final_embed = discord.Embed(
        title=f"Queue {queue_num} - Match Ready!",
        description=f"Teams have been formed and map **{chosen_map}** has been selected.\nPlayers have been moved to their team voice channels.",
        color=SUCCESS_COLOR
    )
    final_embed.set_footer(text="Good luck and have fun!")
    
    # Create match entry in database
    match_id = await db.create_match(queue_num, queue.captains[0], queue.captains[1], chosen_map)
    if match_id:
        queue.match_id = match_id
        # Register players in match
        await db.register_players_in_match(match_id, queue.team1, queue.team2)
        
        match_info_embed = discord.Embed(
            title="Match Tracking",
            description=f"This match has been registered with ID: **{match_id}**\n\nTo report results, use:\n`/win team1` or `/win team2`",
            color=INFO_COLOR
        )
        await ctx.send(embed=match_info_embed)
    
    await ctx.send(embed=final_embed)

@bot.slash_command(
    name="resetqueue",
    description="Reset a specific queue (Admin only)"
)
@permissions.has_any_role("Owner", "COM MODERATOR", "COM ADMIN", "COM CAPTAIN")
async def resetqueue(
    ctx,
    queue_num: Option(int, "Queue number to reset", required=False, default=None)
):
    # Permission check is handled by the decorator, but we'll keep it for extra safety
    allowed_roles = ["Owner", "COM MODERATOR", "COM ADMIN", "COM CAPTAIN"]
    user_roles = [role.name for role in ctx.author.roles]

    if not any(role in user_roles for role in allowed_roles):
        embed = discord.Embed(
            title="Permission Error",
            description="❌ You do not have the required role to use this command.",
            color=WARNING_COLOR
        )
        await ctx.respond(embed=embed, ephemeral=True)
        return
    
    # If no queue number is provided, get it from the channel name
    if queue_num is None:
        if ctx.channel.name.startswith("queue-") and "-chat" in ctx.channel.name:
            try:
                queue_num = int(ctx.channel.name.split("-")[1])
            except ValueError:
                embed = discord.Embed(
                    title="Invalid Queue",
                    description="❌ Could not determine queue number from channel name. Please specify a queue number.",
                    color=WARNING_COLOR
                )
                await ctx.send(embed=embed, delete_after=5)
                return
        else:
            embed = discord.Embed(
                title="Queue Number Required",
                description="❌ Please specify a queue number (e.g., `/resetqueue 1`).",
                color=WARNING_COLOR
            )
            await ctx.respond(embed=embed, ephemeral=True)
            return
    
    # Reset the specified queue
    if queue_num in queues:
        queues[queue_num].reset()
        embed = discord.Embed(
            title=f"Queue {queue_num} Reset",
            description=f"✅ Queue {queue_num} has been reset successfully. Players can now join again.",
            color=SUCCESS_COLOR
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="Queue Not Found",
            description=f"❌ Queue {queue_num} does not exist or is already empty.",
            color=WARNING_COLOR
        )
        await ctx.send(embed=embed)

@bot.slash_command(
    name="queue",
    description="View the status of a specific queue"
)
async def queue(
    ctx, 
    queue_num: Option(int, "Queue number to check", required=False, default=None)
):
    # If no queue number is provided, get it from the channel name
    if queue_num is None:
        if ctx.channel.name.startswith("queue-") and "-chat" in ctx.channel.name:
            try:
                queue_num = int(ctx.channel.name.split("-")[1])
            except ValueError:
                embed = discord.Embed(
                    title="Invalid Queue",
                    description="❌ Could not determine queue number from channel name. Please specify a queue number.",
                    color=WARNING_COLOR
                )
                await ctx.respond(embed=embed, ephemeral=True)
                return
        else:
            embed = discord.Embed(
                title="Queue Number Required",
                description="❌ Please specify a queue number (e.g., `/queue 1`).",
                color=WARNING_COLOR
            )
            await ctx.respond(embed=embed, ephemeral=True)
            return
    
    # Show queue status
    if queue_num not in queues or not queues[queue_num].players:
        embed = discord.Embed(
            title=f"Queue {queue_num} Status",
            description=f"❌ Queue {queue_num} is currently empty.",
            color=WARNING_COLOR
        )
        await ctx.respond(embed=embed)
    else:
        queue = queues[queue_num]
        # Create a progress bar
        progress = len(queue.players)
        progress_bar = "▰" * progress + "▱" * (10 - progress)
        
        queue_list = "\n".join([f"{i+1}. {member.display_name}" for i, member in enumerate(queue.players)])
        
        embed = discord.Embed(
            title=f"Queue {queue_num} Status",
            description=f"**Queue Status:** {progress_bar} ({progress}/10)",
            color=PRIMARY_COLOR
        )
        
        embed.add_field(
            name="Players in Queue",
            value=queue_list,
            inline=False
        )
        
        await ctx.respond(embed=embed)

@bot.slash_command(
    name="help",
    description="Show available bot commands and their usage"
)
async def help_command(ctx):
    embed = discord.Embed(
        title="Tournament Bot Commands",
        description="These are the available commands for the tournament bot:",
        color=PRIMARY_COLOR
    )
    
    embed.add_field(
        name="Player Commands",
        value="""
🔹 `/register` – Register yourself for the game.
🔹 `/join [queue_number]` – Join the queue (must be in the corresponding voice channel).
🔹 `/queue [queue_number]` – View the status of a specific queue.
🔹 `/queues` – Show all active queues and their status.
🔹 `/score [@user]` – View your own or another player's statistics.
🔹 `/leaderboard` – Show the top players by points.
🔹 `/stats [queue_number]` – View statistics for a specific queue.
🔹 `/help` – Show this help message.
""",
        inline=False
    )
    
    embed.add_field(
        name="Admin Commands",
        value="""
🔹 `/resetqueue [queue_number]` – Reset a specific queue (Admins only).
🔹 `/win [team]` – Report match results and update player points (Admins only).
""",
        inline=False
    )
    
    embed.add_field(
        name="Queue System",
        value="""
• Each queue has its own voice channel (named "Queue 1", "Queue 2", etc.)
• Each queue has its own text channel (named "queue-1-chat", "queue-2-chat", etc.)
• Team voice channels are created automatically as "Team 1A", "Team 1B", "Team 2A", "Team 2B", etc.
• You must be in the voice channel to join its queue
""",
        inline=False
    )
    
    embed.set_footer(text="Made for tournament management")
    
    await ctx.respond(embed=embed)

# Make sure to replace with your actual bot token
# Status command to show active queues
@bot.slash_command(
    name="queues",
    description="Show all active queues and their status"
)
async def queues_command(ctx):
    if not queues:
        embed = discord.Embed(
            title="No Active Queues",
            description="There are currently no active queues.",
            color=WARNING_COLOR
        )
        await ctx.respond(embed=embed)
        return
    
    embed = discord.Embed(
        title="Active Queues",
        description="Here are all the current queues and their status:",
        color=PRIMARY_COLOR
    )
    
    for queue_num, queue in sorted(queues.items()):
        player_count = len(queue.players)
        progress_bar = "▰" * player_count + "▱" * (10 - player_count)
        status = f"{progress_bar} ({player_count}/10)"
        
        if queue.captains:
            # Queue is in team selection or game phase
            if queue.team1 and queue.team2:
                state = "Match in progress"
            else:
                state = "Team selection"
        elif player_count == 0:
            state = "Empty"
        elif player_count == 10:
            state = "Full - Starting soon"
        else:
            state = "Waiting for players"
        
        embed.add_field(
            name=f"Queue {queue_num}",
            value=f"**Status:** {state}\n**Players:** {status}\n**Voice Channel:** {queue.vc_name}",
            inline=False
        )
    
    await ctx.respond(embed=embed)

@bot.slash_command(
    name="score",
    description="View player stats and points"
)
async def score_command(
    ctx, 
    member: Option(discord.Member, "Player to check stats for", required=False, default=None)
):
    if member is None:
        member = ctx.author
        
    # Get player stats from database
    stats = await db.get_player_stats(member.id)
    
    if not stats:
        embed = discord.Embed(
            title="Player Not Found",
            description=f"{member.display_name} has not played any matches yet.",
            color=WARNING_COLOR
        )
        await ctx.respond(embed=embed)
        return
        
    # Calculate win rate
    win_rate = 0
    if stats['matches_played'] > 0:
        win_rate = (stats['wins'] / stats['matches_played']) * 100
        
    embed = discord.Embed(
        title=f"Player Stats: {member.display_name}",
        description=f"Stats for {member.mention}",
        color=PRIMARY_COLOR
    )
    
    embed.add_field(name="Points", value=f"**{stats['points']}**", inline=True)
    embed.add_field(name="Matches Played", value=str(stats['matches_played']), inline=True)
    embed.add_field(name="Wins", value=str(stats['wins']), inline=True)
    embed.add_field(name="Win Rate", value=f"{win_rate:.1f}%", inline=True)
    
    if member.avatar:
        embed.set_thumbnail(url=member.avatar.url)
        
    embed.set_footer(text="Points are earned by winning matches")
    
    await ctx.respond(embed=embed)
    
@bot.slash_command(
    name="leaderboard",
    description="Show the top players by points"
)
async def leaderboard_command(ctx):
    try:
        top_players = await db.get_leaderboard(10)
        
        if not top_players:
            embed = discord.Embed(
                title="Leaderboard",
                description="No players have earned points yet.",
                color=WARNING_COLOR
            )
            await ctx.respond(embed=embed)
            return
        
        embed = discord.Embed(
            title="🏆 Tournament Leaderboard",
            description="Top players by points",
            color=PRIMARY_COLOR
        )
        
        leaderboard_text = ""
        for i, player in enumerate(top_players):
            discord_id = player['discord_id']
            points = player['points']
            matches = player['matches_played']
            wins = player['wins']
            
            # Try to get member from Discord
            member = ctx.guild.get_member(int(discord_id))
            name = member.display_name if member else f"Unknown Player ({discord_id})"
            
            # Add medal for top 3
            medal = ""
            if i == 0:
                medal = "🥇 "
            elif i == 1:
                medal = "🥈 "
            elif i == 2:
                medal = "🥉 "
                
            leaderboard_text += f"{medal}**{i+1}. {name}** - {points} points ({wins}/{matches} wins)\n"
        
        embed.add_field(name="Top Players", value=leaderboard_text, inline=False)
        embed.set_footer(text="Updated in real-time")
        
        await ctx.respond(embed=embed)
    except Exception as e:
        logger.error(f"Error getting leaderboard: {e}")
        embed = discord.Embed(
            title="Error",
            description="❌ There was an error retrieving the leaderboard.",
            color=WARNING_COLOR
        )
        await ctx.respond(embed=embed, ephemeral=True)

@bot.slash_command(
    name="win",
    description="Report match results and award points (Admin only)"
)
@permissions.has_any_role("Owner", "COM MODERATOR", "COM ADMIN", "COM CAPTAIN")
async def win_command(
    ctx, 
    team: Option(str, "Winning team (team1 or team2)", required=True, choices=["team1", "team2", "1", "2"])
):
    allowed_roles = ["Owner", "COM MODERATOR", "COM ADMIN", "COM CAPTAIN"]
    user_roles = [role.name for role in ctx.author.roles]

    if not any(role in user_roles for role in allowed_roles):
        embed = discord.Embed(
            title="Permission Error",
            description="❌ You do not have the required role to use this command.",
            color=WARNING_COLOR
        )
        await ctx.respond(embed=embed, ephemeral=True)
        return
        
    # Get queue number from channel name
    queue_num = None
    if ctx.channel.name.startswith("queue-") and "-chat" in ctx.channel.name:
        try:
            queue_num = int(ctx.channel.name.split("-")[1])
        except ValueError:
            embed = discord.Embed(
                title="Invalid Channel",
                description="❌ Could not determine queue number from channel name.",
                color=WARNING_COLOR
            )
            await ctx.respond(embed=embed, ephemeral=True)
            return
    else:
        embed = discord.Embed(
            title="Wrong Channel",
            description="❌ This command can only be used in a queue chat channel.",
            color=WARNING_COLOR
        )
        await ctx.respond(embed=embed, ephemeral=True)
        return
        
    # Check if queue exists
    if queue_num not in queues:
        embed = discord.Embed(
            title="Queue Not Found",
            description=f"❌ Queue {queue_num} does not exist.",
            color=WARNING_COLOR
        )
        await ctx.respond(embed=embed)
        return
        
    queue = queues[queue_num]
    
    # Check if match is active
    if not queue.match_id:
        embed = discord.Embed(
            title="No Active Match",
            description="❌ There is no active match to report results for.",
            color=WARNING_COLOR
        )
        await ctx.respond(embed=embed)
        return
        
    # Check if match already reported
    if queue.match_reported:
        embed = discord.Embed(
            title="Match Already Reported",
            description="❌ Results for this match have already been reported.",
            color=WARNING_COLOR
        )
        await ctx.respond(embed=embed)
        return
        
    # Validate team name
    if team.lower() not in ["team1", "team2", "1", "2"]:
        embed = discord.Embed(
            title="Invalid Team",
            description="❌ Please specify either 'team1' or 'team2' as the winner.",
            color=WARNING_COLOR
        )
        await ctx.respond(embed=embed)
        return
        
    # Determine winning team number
    winning_team = 1 if team.lower() in ["team1", "1"] else 2
    
    # Update match in database
    success = await db.update_match_winner(queue.match_id, winning_team)
    if not success:
        embed = discord.Embed(
            title="Database Error",
            description="❌ Failed to update match result in database.",
            color=WARNING_COLOR
        )
        await ctx.respond(embed=embed)
        return
        
    # Update player points
    winners = queue.team1 if winning_team == 1 else queue.team2
    losers = queue.team2 if winning_team == 1 else queue.team1
    
    # Award points (winners get 20 points)
    WIN_POINTS = 20  # Points awarded for winning a match
    LOSS_POINTS = 0  # Points awarded for losing a match
    
    # Update database for winners
    winner_points_updates = []
    for player in winners:
        winner_points_updates.append(db.update_player_points(player.id, WIN_POINTS, win=True, username=player.display_name))
    
    # Update database for losers
    loser_points_updates = []
    for player in losers:
        loser_points_updates.append(db.update_player_points(player.id, LOSS_POINTS, win=False, username=player.display_name))
    
    # Mark match as reported
    queue.match_reported = True
    
    # Generate results embed
    result_embed = discord.Embed(
        title=f"Queue {queue_num} - Match Results",
        description=f"Team {winning_team} has won the match on map **{queue.chosen_map}**!",
        color=SUCCESS_COLOR
    )
    
    # Show winners
    winners_team = "Team A" if winning_team == 1 else "Team B"
    winners_list = ""
    for player in winners:
        points = await db.get_player_points(player.id)
        winners_list += f"**{player.display_name}** [**{points}** pts] (+{WIN_POINTS})\n"
    
    # Show losers
    losers_team = "Team B" if winning_team == 1 else "Team A"
    losers_list = ""
    for player in losers:
        points = await db.get_player_points(player.id)
        losers_list += f"**{player.display_name}** [{points} pts]\n"
    
    result_embed.add_field(
        name=f"🏆 {winners_team} (Winner)",
        value=winners_list,
        inline=True
    )
    
    result_embed.add_field(
        name=f"💔 {losers_team}",
        value=losers_list,
        inline=True
    )
    
    result_embed.add_field(
        name="Match Details",
        value=f"**Map:** {queue.chosen_map}\n**Match ID:** {queue.match_id}",
        inline=False
    )
    
    # Reset voice channel permissions after match
    guild = ctx.guild
    team1_vc = discord.utils.get(guild.voice_channels, name=queue.team1_vc_name)
    team2_vc = discord.utils.get(guild.voice_channels, name=queue.team2_vc_name)
    
    if team1_vc and team2_vc:
        try:
            # Reset permissions on team voice channels
            for vc in [team1_vc, team2_vc]:
                await vc.set_permissions(guild.default_role, connect=False)
                for player in queue.team1 + queue.team2:
                    await vc.set_permissions(player, overwrite=None)
        except discord.Forbidden:
            logger.error("Missing permissions to reset voice channel permissions")
        except Exception as e:
            logger.error(f"Error resetting voice channel permissions: {e}")
    
    # Clean up the queue but preserve the match ID
    match_id = queue.match_id
    chosen_map = queue.chosen_map
    queue.reset()
    queue.match_id = match_id  # Keep match ID for history
    queue.chosen_map = chosen_map  # Keep chosen map
    queue.match_reported = True  # Mark as reported
    
    # Show match results
    await ctx.respond(embed=result_embed)
    
    # Notify that queue has been reset
    reset_embed = discord.Embed(
        title=f"Queue {queue_num} Reset",
        description=f"Queue {queue_num} has been reset and is ready for new players.\nUse `/join {queue_num}` to join the queue!",
        color=INFO_COLOR
    )
    await ctx.send(embed=reset_embed)

@bot.slash_command(
    name="stats",
    description="View statistics for a specific queue"
)
async def stats_command(
    ctx,
    queue_num: Option(int, "Queue number to view stats for", required=False, default=None)
):
    # If no queue number is provided, get it from the channel name
    if queue_num is None:
        if ctx.channel.name.startswith("queue-") and "-chat" in ctx.channel.name:
            try:
                queue_num = int(ctx.channel.name.split("-")[1])
            except ValueError:
                embed = discord.Embed(
                    title="Invalid Queue",
                    description="❌ Could not determine queue number from channel name. Please specify a queue number.",
                    color=WARNING_COLOR
                )
                await ctx.respond(embed=embed, ephemeral=True)
                return
            return
        else:
            embed = discord.Embed(
                title="Queue Number Required",
                description="❌ Please specify a queue number (e.g., `/stats 1`).",
                color=WARNING_COLOR
            )
            await ctx.respond(embed=embed, ephemeral=True)
            return
            
    try:
        stats = await db.get_queue_stats(queue_num, 5)
        if stats:
            recent_matches = stats['recent_matches']
            team1_wins = stats['team1_wins']
            team2_wins = stats['team2_wins']
            most_common_maps = stats['most_common_maps']
            
            if not recent_matches:
                embed = discord.Embed(
                    title=f"Queue {queue_num} Stats",
                    description=f"No match history found for Queue {queue_num}.",
                    color=WARNING_COLOR
                )
                await ctx.respond(embed=embed)
                return
            
            embed = discord.Embed(
                title=f"Queue {queue_num} - Match Statistics",
                description=f"Statistics for Queue {queue_num}",
                color=PRIMARY_COLOR
            )
            
            # Add match history
            match_history = ""
            for i, match in enumerate(recent_matches):
                winner = "Team A" if match['winner_team'] == 1 else "Team B"
                map_played = match['map_played']
                date = match['timestamp'].strftime("%m/%d/%Y")
                match_history += f"{i+1}. **{winner}** won on **{map_played}** ({date})\n"
                
            embed.add_field(
                name="Recent Matches",
                value=match_history or "No recent matches",
                inline=False
            )
            
            # Add team stats
            team_stats = f"**Team A Wins:** {team1_wins}\n**Team B Wins:** {team2_wins}"
            embed.add_field(
                name="Team Statistics",
                value=team_stats,
                inline=True
            )
            
            # Add map stats
            if most_common_maps:
                map_stats = "\n".join([f"**{map_name}**: {count} times" for map_name, count in most_common_maps])
                embed.add_field(
                    name="Most Played Maps",
                    value=map_stats,
                    inline=True
                )
                
            await ctx.respond(embed=embed)
    except Exception as e:
        logger.error(f"Error getting queue stats: {e}")
        embed = discord.Embed(
            title="Error",
            description="❌ There was an error retrieving the queue statistics.",
            color=WARNING_COLOR
        )
        await ctx.respond(embed=embed, ephemeral=True)

# Get bot token from environment variable for security
# Make sure to set the DISCORD_BOT_TOKEN environment variable
# If not set, it will fall back to the value specified here (for development only)
bot_token = os.environ.get("DISCORD_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Print warning if using default token
if bot_token == "YOUR_BOT_TOKEN_HERE":
    logger.warning("Using default bot token! Set the DISCORD_BOT_TOKEN environment variable for production use.")

# Start the bot
bot.run(bot_token)

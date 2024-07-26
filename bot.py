import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import Button, View
import asyncio
import re
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import random

# Load environment variables from .env file
load_dotenv()
DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')

# Initialize intents
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.reactions = True
intents.message_content = True

# Initialize bot
bot = commands.Bot(command_prefix='ch/', intents=intents)

# Dictionary to store unique data for each guild
checkin_channels = {}
active_sessions = {}
manager_roles = {}
manager_members = {}

# List of variation messages
progress_messages = [
    "How's your progress?",
    "What have you achieved so far?",
    "Any updates on your task?",
    "How are things going?",
    "How is your work progressing?",
    "What have you done since the last check-in?",
    "What's your status?",
    "How's it going?",
    "Any progress to report?",
    "What have you completed?"
]

# Classes and Functions

# Class to represent a Checkin Session
class CheckinSession:
    def __init__(self, guild_id, channel, creator, duration, mentions):
        self.guild_id = guild_id
        self.channel = channel
        self.creator = creator
        self.duration = duration
        self.mentions = mentions
        self.task = None
        self.start_time = datetime.now()  # Track when the session started

# Function to parse duration strings into seconds
async def parse_duration(duration_str):
    match = re.match(r'(\d+)\s*(s|secs?|seconds?|m|mins?|minutes?|h|hrs?|hours?|d|days?)', duration_str, re.IGNORECASE)
    if not match:
        return None
    value, unit = match.groups()
    value = int(value)
    unit = unit.lower()
    if 's' in unit:
        return value
    elif 'm' in unit:
        return value * 60
    elif 'h' in unit:
        return value * 3600
    elif 'd' in unit:
        return value * 86400
    return None

# Helper function to parse mentions
def parse_mentions(ctx, mentions):
    mention_list = mentions.split()
    members = []

    for mention in mention_list:
        mention = mention.strip()
        if mention.startswith('<@&'):  # Role mention
            role_id = int(mention.strip('<@&>'))
            role = ctx.guild.get_role(role_id)
            if role:
                members.extend(role.members)
        elif mention.startswith('<@'):  # User mention
            user_id = int(mention.strip('<@!>'))
            member = ctx.guild.get_member(user_id)
            if member:
                members.append(member)
    
    return members

# Helper function to check if a user is a manager
def is_manager(ctx):
    guild_id = ctx.guild.id
    if guild_id not in manager_roles:
        manager_roles[guild_id] = []
    if guild_id not in manager_members:
        manager_members[guild_id] = []
    
    user_roles = ctx.author.roles
    if ctx.author.guild_permissions.administrator or any(role.id in manager_roles[guild_id] for role in user_roles) or ctx.author.id in manager_members[guild_id]:
        return True
    return False


# Event when the bot is ready
@bot.event
async def on_ready():
    print(f'Bot is ready as {bot.user}')
    await sync_commands_with_all_guilds()
    print('Commands synced with all guilds')

# Event when the bot joins a new guild
@bot.event
async def on_guild_join(guild):
    await sync_commands_with_guild(guild)
    print(f'Synced commands for new guild: {guild.name} (ID: {guild.id})')

# Function to sync commands with all guilds the bot is in
async def sync_commands_with_all_guilds():
    for guild in bot.guilds:
        await sync_commands_with_guild(guild)
        print(f'Synced commands for guild: {guild.name} (ID: {guild.id})')

# Function to sync commands with a specific guild
async def sync_commands_with_guild(guild):
    guild_object = discord.Object(id=guild.id)
    bot.tree.copy_global_to(guild=guild_object)
    await bot.tree.sync(guild=guild_object)
    print(f'Commands synced with guild: {guild.name} (ID: {guild.id})')

# Task to send reminders
async def send_reminders(session):
    last_reminder_time = datetime.now()  # Track the last reminder time
    while True:
        try:
            print(f'Waiting for {session.duration} seconds before sending the next reminder.')
            await asyncio.sleep(session.duration)
            current_time = datetime.now()
            time_difference = current_time - last_reminder_time
            minutes_ago = int(time_difference.total_seconds() // 60)
            time_message = f"{minutes_ago} minutes ago"
            random_progress_message = random.choice(progress_messages)
            message = f'{session.creator.mention} and {" ".join(member.mention for member in session.mentions)}, {random_progress_message}\nLast reminder: {time_message}'
            print(f'Sending reminder to {session.channel} for session by {session.creator}')
            await session.channel.send(message, view=ReminderView(session))
            last_reminder_time = current_time  # Update the last reminder time
        except Exception as e:
            print(f'Error in send_reminders task: {e}')

# Command to set check-in channels
@bot.hybrid_command(name='checkin_channels', description='Set the channels where check-in commands can be used')
# @commands.check(is_manager)
async def checkin_channels_cmd(ctx: commands.Context, *, channels: str):
    guild_id = ctx.guild.id
    checkin_channels[guild_id] = [ctx.guild.get_channel(int(channel.strip('<#>'))) for channel in channels.split()]
    await ctx.send(f'Check-in channels updated: {", ".join(channel.mention for channel in checkin_channels[guild_id])}')
    print(f'Check-in channels set for guild {guild_id}: {checkin_channels[guild_id]}')

# Command to check bot permissions in a channel
@bot.hybrid_command(name='check_perms', description='Check bot permissions in the current channel')
# @commands.check(is_manager)
async def check_perms_cmd(ctx: commands.Context):
    permissions = ctx.channel.permissions_for(ctx.guild.me)
    required_perms = [
        ('read_messages', 'Read Messages'),
        ('send_messages', 'Send Messages'),
        ('read_message_history', 'Read Message History')
    ]
    missing_perms = [name for perm, name in required_perms if not getattr(permissions, perm)]
    
    if missing_perms:
        await ctx.send(f'Missing permissions: {", ".join(missing_perms)}')
    else:
        await ctx.send('Bot has all necessary permissions.')
    print(f'Permissions checked in channel {ctx.channel.id}: {", ".join(missing_perms) if missing_perms else "All permissions are present"}')

# Command to start a check-in session
@bot.hybrid_command(name='checkin', description='Start a check-in session')
async def checkin_cmd(ctx: commands.Context, duration: str, *, mentions: str):
    # Check if there are channels defined for the guild
    guild_id = ctx.guild.id
    guild_name = ctx.guild.name
    if guild_id not in checkin_channels or not checkin_channels[guild_id]:
        await ctx.send('No check-in channels are defined for this server. Please contact your admins to set up the bot.')
        print(f'No check-in channels defined for guild {guild_name} with ID: {guild_id}')
        return

    # Parse duration and validate
    duration_seconds = await parse_duration(duration)
    if duration_seconds is None or duration_seconds < 30:
        await ctx.send('Invalid duration. Minimum duration is 30 seconds.')
        print(f'Invalid duration provided: {duration}')
        return

    print(f'Parsed duration (in seconds): {duration_seconds}')

    # Parse mentions
    members = parse_mentions(ctx, mentions)

    # Include the creator in the mentions list
    if ctx.author not in members:
        members.append(ctx.author)

    session = CheckinSession(guild_id=guild_id, channel=ctx.channel, creator=ctx.author, duration=duration_seconds, mentions=members)

    if guild_id not in active_sessions:
        active_sessions[guild_id] = []
    active_sessions[guild_id].append(session)

    # Start the periodic reminder task
    print(f'Starting check-in session for {session.creator} in guild {guild_id}')
    session.task = bot.loop.create_task(send_reminders(session))

    # Send initial session start message with embed and buttons
    # embed = create_session_embed(session)
    # view = ReminderView(session)
    await ctx.send(f'Check-in session started for {duration}!', embed=embed, view=view)
    print(f'Check-in session created: {session}')


# Run the bot
bot.run(DISCORD_BOT_TOKEN)

##########################################################################################################################

'''

# Helper function to create session embed
def create_session_embed(session):
    embed = discord.Embed(title="Check-in Session", description="Progress updates", color=discord.Color.blue())
    embed.add_field(name="Creator", value=session.creator.mention, inline=False)
    embed.add_field(name="Duration", value=f"{session.duration} seconds", inline=False)
    embed.add_field(name="Participants", value=", ".join(member.mention for member in session.mentions), inline=False)
    return embed


# Command to add managers
@bot.hybrid_command(name='add_managers', description='Add roles or members as managers')
@commands.check(is_manager)
async def add_managers_cmd(ctx: commands.Context, *, mentions: str):
    guild_id = ctx.guild.id
    if guild_id not in manager_roles:
        manager_roles[guild_id] = []
    if guild_id not in manager_members:
        manager_members[guild_id] = []

    members = parse_mentions(ctx, mentions)

    for member in members:
        if isinstance(member, discord.Role):
            if member.id not in manager_roles[guild_id]:
                manager_roles[guild_id].append(member.id)
        else:
            if member.id not in manager_members[guild_id]:
                manager_members[guild_id].append(member.id)

    await ctx.send('Managers have been updated.')

# Command to view managers
@bot.hybrid_command(name='view_managers', description='View roles and members who are managers')
@commands.check(is_manager)
async def view_managers_cmd(ctx: commands.Context):
    guild_id = ctx.guild.id
    if guild_id not in manager_roles:
        manager_roles[guild_id] = []
    if guild_id not in manager_members:
        manager_members[guild_id] = []

    embed = discord.Embed(title="Managers", description="Roles and members who can use setting commands", color=discord.Color.blue())
    
    roles = [ctx.guild.get_role(role_id) for role_id in manager_roles[guild_id]]
    members = [ctx.guild.get_member(user_id) for user_id in manager_members[guild_id]]

    embed.add_field(name="Roles", value=", ".join(role.name for role in roles if role), inline=False)
    embed.add_field(name="Members", value=", ".join(member.display_name for member in members if member), inline=False)

    await ctx.send(embed=embed)



class ReminderView(View):
    def __init__(self, session):
        super().__init__()
        self.session = session

    @discord.ui.button(label='Join', style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.session.mentions:
            self.session.mentions.append(interaction.user)
            await interaction.response.send_message('You have now joined the check-in session.', ephemeral=True)
        else:
            await interaction.response.send_message('You have already joined the check-in session.', ephemeral=True)

    @discord.ui.button(label='Leave', style=discord.ButtonStyle.danger)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user in self.session.mentions:
            self.session.mentions.remove(interaction.user)
            await interaction.response.send_message('You have left the check-in session.', ephemeral=True)
        else:
            await interaction.response.send_message('You are not part of the check-in session.', ephemeral=True)

    @discord.ui.button(label='End', style=discord.ButtonStyle.primary)
    async def end(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user in self.session.mentions:
            self.session.task.cancel()
            await self.session.channel.send('The check-in session has now ended.')
        else:
            await interaction.response.send_message('You are not part of the check-in session.', ephemeral=True)


'''
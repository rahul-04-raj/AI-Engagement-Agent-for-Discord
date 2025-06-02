from agno.agent import Agent
from agno.models.groq import Groq
from agno.tools.duckduckgo import DuckDuckGoTools
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import json
from datetime import datetime, timedelta
import io
from contextlib import redirect_stdout
import re
import asyncio
import random
import aiohttp
from io import BytesIO
from analytics import Analytics
import pandas as pd

# Load environment variables
load_dotenv()

# Initialize analytics
analytics = Analytics()

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True  # Enable presence intent
bot = commands.Bot(command_prefix='!', intents=intents)

# Bot configuration
BOT_NAME = "Grey"
COMMAND_PREFIX = "!"
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")

# Create engagement agent
agent = Agent(
    model=Groq(id="meta-llama/llama-4-scout-17b-16e-instruct"),
    description=f"""You are a helpful community assistant named {BOT_NAME} that engages only when necessary. Your role is to:
    1. Respond selectively:
       - Only reply to unanswered messages after 1-2 minutes
       - Answer questions when asked
       - Help when users need assistance
       - Respond when mentioned by name or tagged
       - Don't respond to every message
       
    2. Maintain conversation context:
       - Remember previous interactions
       - Reference past discussions
       - Build on existing topics
       
    3. Handle specific situations:
       - Questions (brief, direct answers)
       - Requests for help (concise assistance)
       - Unanswered messages (gentle engagement)
       - Technical issues (quick solutions)
       - Mentions of your name (friendly acknowledgment)
       
    4. Engagement strategies:
       - Ask short, focused questions
       - Share quick, relevant information
       - Suggest solutions briefly
       - Encourage participation concisely
       
    5. Tone and style:
       - Be friendly and approachable
       - Use appropriate humor
       - Maintain professionalism
       - Adapt to the channel's culture
       
    6. Special features:
       - Help with technical issues
       - Answer questions
       - Provide brief assistance
       - Share relevant information
       - Respond to name mentions
       
    7. Search capabilities:
       - Use search only when necessary for factual information
       - Format search queries as simple text questions
       - Don't use function call syntax
       - Keep searches focused and specific
       - Use natural language for queries
       - Share only the most relevant information
       - Keep search results concise
       - Focus on key points
       - Format search results as simple text without function calls""",
    tools=[DuckDuckGoTools()],
    markdown=True
)

# Store conversation history and message tracking
CONVERSATION_HISTORY = {}
UNANSWERED_MESSAGES = {}
MAX_HISTORY_LENGTH = 10
HISTORY_EXPIRY = timedelta(hours=24)
DISCORD_MAX_LENGTH = 1900
RESPONSE_DELAY = 60  # 1 minute delay before responding to unanswered messages


def is_question(text):
    """Check if the message is a question"""
    question_indicators = ['?', 'what', 'how', 'why', 'when', 'where', 'who', 'can you', 'could you', 'help', 'please']
    text_lower = text.lower()
    return any(indicator in text_lower for indicator in question_indicators)

def is_help_request(text):
    """Check if the message is asking for help"""
    help_indicators = ['help', 'assist', 'support', 'trouble', 'issue', 'problem', 'how to', 'guide', 'tutorial']
    text_lower = text.lower()
    return any(indicator in text_lower for indicator in help_indicators)

def is_bot_mentioned(message):
    """Check if the bot is mentioned by name or tag"""
    # Check for mentions
    if any(mention.id == bot.user.id for mention in message.mentions):
        return True
    
    # Check for name mentions (case insensitive)
    text_lower = message.content.lower()
    return BOT_NAME.lower() in text_lower

def extract_response(text):
    """Extract the actual response message after 'Response'"""
    response_match = re.search(r'Response.*?\n(.*)', text, re.DOTALL)
    if response_match:
        return response_match.group(1).strip()
    return text.strip()

def clean_message(text):
    """Clean up message formatting and remove unnecessary symbols"""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    text = ansi_escape.sub('', text)
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'`.*?`', '', text)
    text = re.sub(r'[|*_~>]', '', text)
    text = re.sub(r'\n\s*\n', '\n\n', text)
    text = text.strip()
    text = re.sub(r'[^\w\s.,!?₹$€£¥@%&*()\-+=:;<>/\\|\[\]{}]', '', text)
    text = ' '.join(text.split())
    return text

def get_channel_history(channel_id):
    """Get conversation history for a channel"""
    if channel_id not in CONVERSATION_HISTORY:
        CONVERSATION_HISTORY[channel_id] = []
    return CONVERSATION_HISTORY[channel_id]

def update_channel_history(channel_id, message):
    """Update conversation history for a channel"""
    history = get_channel_history(channel_id)
    history.append({
        'content': message,
        'timestamp': datetime.now()
    })
    while len(history) > MAX_HISTORY_LENGTH:
        history.pop(0)
    current_time = datetime.now()
    CONVERSATION_HISTORY[channel_id] = [
        msg for msg in history 
        if current_time - msg['timestamp'] < HISTORY_EXPIRY
    ]

def format_conversation_history(channel_id):
    """Format conversation history for the agent"""
    history = get_channel_history(channel_id)
    if not history:
        return "No previous conversation history."
    formatted_history = "Recent conversation history:\n"
    for msg in history:
        formatted_history += f"- {msg['content']}\n"
    return formatted_history

def split_message(message):
    """Split a message into chunks that fit Discord's character limit"""
    if len(message) <= DISCORD_MAX_LENGTH:
        return [message]
    chunks = []
    current_chunk = ""
    lines = message.split('\n')
    for line in lines:
        if len(current_chunk) + len(line) + 1 > DISCORD_MAX_LENGTH:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = line
        else:
            if current_chunk:
                current_chunk += '\n'
            current_chunk += line
    if current_chunk:
        chunks.append(current_chunk)
    return chunks

async def check_unanswered_message(channel, message):
    """Check and respond to unanswered messages after delay"""
    await asyncio.sleep(RESPONSE_DELAY)
    if message.id in UNANSWERED_MESSAGES:
        # Check if message still needs a response
        async for msg in channel.history(limit=10, after=message):
            if msg.author != bot.user and not msg.author.bot:
                # Someone else responded, remove from tracking
                UNANSWERED_MESSAGES.pop(message.id, None)
                return
        
        # No response received, send a gentle engagement message
        prompt = f"""Context: {format_conversation_history(channel.id)}
        
        Current message: {message.content}
        
        This message hasn't received a response. Please provide a brief, engaging response that:
        1. Acknowledges the message gently
        2. Encourages discussion
        3. Keeps the conversation going
        
        Keep your response short and friendly."""
        
        f = io.StringIO()
        with redirect_stdout(f):
            agent.print_response(prompt)
        response = f.getvalue()
        actual_response = extract_response(response)
        cleaned_response = clean_message(actual_response)
        
        chunks = split_message(cleaned_response)
        for chunk in chunks:
            sent_message = await channel.send(chunk)
            # Log bot response to analytics (counts as a bot response)
            analytics.log_message(sent_message, is_bot=True)
        
        UNANSWERED_MESSAGES.pop(message.id, None)

async def get_pexels_image(query):
    """Get an image from Pexels API"""
    try:
        headers = {
            'Authorization': PEXELS_API_KEY
        }
        search_url = f"https://api.pexels.com/v1/search?query={query}&per_page=1"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(search_url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    if data['photos']:
                        return data['photos'][0]['src']['large']
                print(f"Pexels API error: {response.status}")
    except Exception as e:
        print(f"Error fetching from Pexels: {str(e)}")
    return None

async def send_image(ctx, image_url, caption=None):
    """Send an image to the channel"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as response:
                if response.status == 200:
                    image_data = await response.read()
                    image_io = BytesIO(image_data)
                    
                    if caption:
                        await ctx.send(caption, file=discord.File(image_io, "image.jpg"))
                    else:
                        await ctx.send(file=discord.File(image_io, "image.jpg"))
                else:
                    await ctx.send("Sorry, I couldn't download the image. Please try again. 😕")
    except Exception as e:
        await ctx.send(f"Sorry, there was an error sending the image: {str(e)}")

@bot.command(name='image')
async def image_command(ctx, *, query):
    """Search and send an image from Pexels"""
    if not PEXELS_API_KEY:
        await ctx.send("Sorry, the image feature is not configured. Please set up the Pexels API key. 😕")
        return
        
    try:
        # Show searching message
        searching_msg = await ctx.send("🔍 Searching for images...")
        
        # Get image from Pexels
        image_url = await get_pexels_image(query)
        
        if not image_url:
            await searching_msg.edit(content="Sorry, I couldn't find any images. Please try a different search term. 😕")
            return
            
        # Send the image
        await searching_msg.edit(content=f"Here's an image for '{query}':")
        await send_image(ctx, image_url)
        
    except Exception as e:
        await ctx.send(f"Sorry, there was an error: {str(e)}")

# Command handlers
@bot.command(name='commands')
async def commands_command(ctx):
    """Show available commands"""
    help_text = f"""**{BOT_NAME}'s Commands:**
    
`{COMMAND_PREFIX}commands` - Show this help message
`{COMMAND_PREFIX}ping` - Check if I'm responsive
`{COMMAND_PREFIX}clear` - Clear conversation history
`{COMMAND_PREFIX}stats` - Show conversation statistics
`{COMMAND_PREFIX}search <query>` - Search for information
`{COMMAND_PREFIX}image <query>` - Search and send an image
`{COMMAND_PREFIX}members` - Show server member count

You can also:
- Mention me by name ({BOT_NAME})
- Tag me with @{BOT_NAME}
- Ask me questions directly
- Ask for help with technical issues"""
    
    await ctx.send(help_text)

@bot.command(name='ping')
async def ping_command(ctx):
    """Check bot's response time"""
    latency = round(bot.latency * 1000)
    await ctx.send(f"Pong! 🏓 Latency: {latency}ms")

@bot.command(name='clear')
async def clear_command(ctx):
    """Clear conversation history for the current channel"""
    if ctx.channel.id in CONVERSATION_HISTORY:
        CONVERSATION_HISTORY[ctx.channel.id] = []
    await ctx.send("Conversation history cleared! 🧹")

@bot.command(name='stats')
async def stats_command(ctx):
    """Show conversation statistics"""
    history = get_channel_history(ctx.channel.id)
    total_messages = len(history)
    unique_users = len(set(msg.get('author', 'unknown') for msg in history))
    
    stats_text = f"""**Channel Statistics:**
    
📊 Total Messages: {total_messages}
👥 Unique Users: {unique_users}
⏰ History Duration: {HISTORY_EXPIRY.total_seconds() / 3600:.1f} hours"""
    
    await ctx.send(stats_text)

@bot.command(name='search')
async def search_command(ctx, *, query):
    """Search for information"""
    prompt = f"""Please search for information about: {query}
    
    Provide a brief, informative response with the most relevant information.
    Keep it concise and focused on the key points."""
    
    f = io.StringIO()
    with redirect_stdout(f):
        agent.print_response(prompt)
    response = f.getvalue()
    actual_response = extract_response(response)
    cleaned_response = clean_message(actual_response)
    
    chunks = split_message(cleaned_response)
    for chunk in chunks:
        await ctx.send(chunk)

@bot.command(name='members')
async def members_command(ctx):
    """Show server member count"""
    guild = ctx.guild
    total_members = guild.member_count
    
    # Count members by status
    online = 0
    idle = 0
    dnd = 0
    offline = 0
    
    for member in guild.members:
        if member.status == discord.Status.online:
            online += 1
        elif member.status == discord.Status.idle:
            idle += 1
        elif member.status == discord.Status.dnd:
            dnd += 1
        else:
            offline += 1
    
    member_stats = f"""**Server Member Statistics:**
    
👥 Total Members: {total_members}
🟢 Online: {online}
🟡 Idle: {idle}
🔴 Do Not Disturb: {dnd}
⚫ Offline: {offline}"""
    
    await ctx.send(member_stats)

@bot.event
async def on_ready():
    print(f'Bot is ready! Logged in as {bot.user.name}')
    # Set bot's nickname to Grey
    for guild in bot.guilds:
        try:
            await guild.me.edit(nick=BOT_NAME)
        except:
            pass
    
    # Start the daily stats update task
    bot.loop.create_task(update_daily_stats_task())

@bot.event
async def on_message(message):
    # Process commands first
    await bot.process_commands(message)
    
    # Ignore messages from the bot itself
    if message.author == bot.user:
        return
    
    # Log user message to analytics
    is_reply = message.reference is not None
    reply_to_id = message.reference.message_id if is_reply else None
    analytics.log_message(message, is_bot=False, is_reply=is_reply, reply_to_id=reply_to_id)
    
    # If this is a reply to a bot message, mark the bot message as replied
    if is_reply and message.reference.resolved.author == bot.user:
        analytics.mark_message_as_replied(message.reference.message_id)
    
    # Update conversation history
    update_channel_history(message.channel.id, message.content)
    
    # Check if message needs immediate response
    needs_response = (
        is_question(message.content) or
        is_help_request(message.content) or
        is_bot_mentioned(message)
    )
    
    if needs_response:
        # Immediate response for questions, help requests, or mentions
        prompt = f"""Context: {format_conversation_history(message.channel.id)}
        
        Current message: {message.content}
        
        Please provide a response that is:
        1. Short and concise (1-2 sentences)
        2. Directly addresses the question, help request, or mention
        3. Friendly and helpful
        4. Uses appropriate emojis
        
        If you need to search for information:
        - Use natural language for your search query
        - Don't use function call syntax
        - Keep the search focused and specific
        
        Keep your response brief and to the point."""
        
        f = io.StringIO()
        with redirect_stdout(f):
            agent.print_response(prompt)
        response = f.getvalue()
        actual_response = extract_response(response)
        cleaned_response = clean_message(actual_response)
        
        chunks = split_message(cleaned_response)
        for chunk in chunks:
            sent_message = await message.channel.send(chunk)
            # Log bot response to analytics (counts as a bot response)
            analytics.log_message(sent_message, is_bot=True)
    else:
        # Track message for potential later response
        UNANSWERED_MESSAGES[message.id] = message
        bot.loop.create_task(check_unanswered_message(message.channel, message))

@bot.command(name='analytics')
async def analytics_command(ctx):
    """Display analytics data"""
    try:
        # Update stats
        analytics.update_hourly_stats()
        
        # Get latest stats
        latest_stats = analytics.get_hourly_stats(hours=24).iloc[-1]
        
        # Calculate additional metrics
        total_messages = int(float(latest_stats['total_messages']))
        unique_users = int(float(latest_stats['unique_users']))
        bot_responses = int(float(latest_stats['bot_responses']))
        
        avg_messages = total_messages / unique_users if unique_users > 0 else 0
        response_ratio = bot_responses / total_messages if total_messages > 0 else 0
        
        # Get trends
        trends = analytics.get_hourly_stats(hours=24)
        most_active_hour = trends.loc[trends['total_messages'].idxmax()]
        peak_users = trends['unique_users'].max()
        best_response_hour = trends.loc[trends['bot_responses'].idxmax()]
        
        # Format the output
        stats_text = f"""📊 **Analytics Overview (Last 24 Hours)**

**Current Hour Activity:**
• Total Messages: {total_messages}
• Active Users: {unique_users}
• Bot Responses: {bot_responses}
• Avg Messages/User: {avg_messages:.1f}
• Bot Response Ratio: {response_ratio:.1%}

**Trends (Last 24 Hours):**
• Most Active Hour: {most_active_hour['hour'].strftime('%H:%M')} ({int(most_active_hour['total_messages'])} messages)
• Peak Users: {int(peak_users)}
• Best Response Hour: {best_response_hour['hour'].strftime('%H:%M')} ({int(best_response_hour['bot_responses'])} responses)"""
        
        # Generate and send plot
        plot_path = analytics.generate_engagement_plot(hours=24)
        if plot_path and plot_path.exists():
            await ctx.send(stats_text, file=discord.File(str(plot_path)))
        else:
            await ctx.send(stats_text)
            
    except Exception as e:
        print(f"Error in analytics command: {e}")
        await ctx.send("❌ Error generating analytics. Please try again later.")

async def update_daily_stats_task():
    """Task to update hourly stats every hour"""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            analytics.update_hourly_stats()
        except Exception as e:
            print(f"Error updating hourly stats: {e}")
        await asyncio.sleep(3600)  # Update every hour

# Run the bot
if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_TOKEN")) 

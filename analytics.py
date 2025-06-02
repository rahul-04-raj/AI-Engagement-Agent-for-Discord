import sqlite3
from datetime import datetime, timedelta
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import json
import pytz

class Analytics:
    def __init__(self, db_path="analytics.db"):
        self.db_path = db_path
        self.ist = pytz.timezone('Asia/Kolkata')
        self._init_db()
    
    def _get_ist_time(self):
        """Get current time in IST"""
        return datetime.now(self.ist)
    
    def _format_ist_time(self, dt):
        """Format datetime to IST string"""
        if dt.tzinfo is None:
            dt = self.ist.localize(dt)
        return dt.strftime('%Y-%m-%d %H:00:00')
    
    def _init_db(self):
        """Initialize the SQLite database with required tables"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            # Messages table
            c.execute('''CREATE TABLE IF NOT EXISTS messages
                        (id INTEGER PRIMARY KEY,
                         channel_id TEXT,
                         author_id TEXT,
                         content TEXT,
                         timestamp DATETIME,
                         is_bot INTEGER,
                         is_reply INTEGER,
                         reply_to_id INTEGER,
                         has_reply INTEGER DEFAULT 0)''')
            
            # Hourly stats table
            c.execute('''CREATE TABLE IF NOT EXISTS hourly_stats
                        (hour TEXT PRIMARY KEY,
                         total_messages INTEGER,
                         unique_users INTEGER,
                         bot_responses INTEGER,
                         response_rate REAL)''')
            
            conn.commit()
        except Exception as e:
            print(f"Error initializing database: {e}")
        finally:
            conn.close()
    
    def log_message(self, message, is_bot=False, is_reply=False, reply_to_id=None):
        """Log a message to the database"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            # Convert message timestamp to IST
            message_time = message.created_at.astimezone(self.ist)
            
            c.execute('''INSERT INTO messages 
                        (channel_id, author_id, content, timestamp, is_bot, is_reply, reply_to_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?)''',
                     (str(message.channel.id), str(message.author.id), message.content,
                      message_time.isoformat(), 1 if is_bot else 0, 1 if is_reply else 0, reply_to_id))
            
            conn.commit()
        except Exception as e:
            print(f"Error logging message: {e}")
        finally:
            conn.close()
    
    def mark_message_as_replied(self, message_id):
        """Mark a message as having received a reply"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            c.execute('''UPDATE messages 
                        SET has_reply = 1 
                        WHERE id = ?''', (message_id,))
            
            conn.commit()
        except Exception as e:
            print(f"Error marking message as replied: {e}")
        finally:
            conn.close()
    
    def update_hourly_stats(self):
        """Update hourly statistics"""
        try:
            conn = sqlite3.connect(self.db_path)
            
            # Get current hour in IST
            current_hour = self._format_ist_time(self._get_ist_time())
            
            # Calculate stats for current hour
            query = '''
            SELECT 
                CAST(COUNT(*) AS INTEGER) as total_messages,
                CAST(COUNT(DISTINCT author_id) AS INTEGER) as unique_users,
                CAST(SUM(CASE WHEN is_bot = 1 THEN 1 ELSE 0 END) AS INTEGER) as bot_responses,
                CAST(AVG(CASE WHEN is_bot = 1 THEN has_reply ELSE NULL END) AS REAL) as response_rate
            FROM messages
            WHERE datetime(timestamp) >= datetime(?)
            AND datetime(timestamp) < datetime(?, '+1 hour')
            '''
            
            stats = pd.read_sql_query(query, conn, params=(current_hour, current_hour))
            
            # Update hourly stats table
            if not stats.empty:
                c = conn.cursor()
                # Handle potential None values with default 0
                total_messages = int(stats['total_messages'].iloc[0]) if pd.notnull(stats['total_messages'].iloc[0]) else 0
                unique_users = int(stats['unique_users'].iloc[0]) if pd.notnull(stats['unique_users'].iloc[0]) else 0
                bot_responses = int(stats['bot_responses'].iloc[0]) if pd.notnull(stats['bot_responses'].iloc[0]) else 0
                response_rate = float(stats['response_rate'].iloc[0]) if pd.notnull(stats['response_rate'].iloc[0]) else 0.0
                
                c.execute('''INSERT OR REPLACE INTO hourly_stats
                            (hour, total_messages, unique_users, bot_responses, response_rate)
                            VALUES (?, ?, ?, ?, ?)''',
                         (current_hour, total_messages, unique_users, bot_responses, response_rate))
                
                conn.commit()
            else:
                # If no messages this hour, insert zeros
                c = conn.cursor()
                c.execute('''INSERT OR REPLACE INTO hourly_stats
                            (hour, total_messages, unique_users, bot_responses, response_rate)
                            VALUES (?, 0, 0, 0, 0.0)''', (current_hour,))
                conn.commit()
                
        except Exception as e:
            print(f"Error updating hourly stats: {e}")
        finally:
            conn.close()
    
    def get_hourly_stats(self, hours=24):
        """Get hourly statistics for the last n hours"""
        try:
            conn = sqlite3.connect(self.db_path)
            
            # Calculate the start time for the last n hours in IST
            start_time = (self._get_ist_time() - timedelta(hours=hours))
            start_time_str = self._format_ist_time(start_time)
            
            # Query to get stats directly from messages table
            query = '''
            WITH hourly_data AS (
                SELECT 
                    strftime('%Y-%m-%d %H:00:00', datetime(timestamp, '+5 hours', '+30 minutes')) as hour,
                    COUNT(*) as total_messages,
                    COUNT(DISTINCT author_id) as unique_users,
                    SUM(CASE WHEN is_bot = 1 THEN 1 ELSE 0 END) as bot_responses,
                    AVG(CASE WHEN is_bot = 1 THEN has_reply ELSE NULL END) as response_rate
                FROM messages
                WHERE datetime(timestamp) >= datetime(?)
                GROUP BY strftime('%Y-%m-%d %H:00:00', datetime(timestamp, '+5 hours', '+30 minutes'))
            )
            SELECT 
                hour,
                COALESCE(total_messages, 0) as total_messages,
                COALESCE(unique_users, 0) as unique_users,
                COALESCE(bot_responses, 0) as bot_responses,
                COALESCE(response_rate, 0) as response_rate
            FROM hourly_data
            ORDER BY hour ASC
            '''
            
            stats = pd.read_sql_query(query, conn, params=(start_time_str,))
            
            # If no data, create a row for the current hour with zeros
            if stats.empty:
                current_hour = self._format_ist_time(self._get_ist_time())
                stats = pd.DataFrame({
                    'hour': [current_hour],
                    'total_messages': [0],
                    'unique_users': [0],
                    'bot_responses': [0],
                    'response_rate': [0]
                })
            
            # Convert hour strings to datetime
            stats['hour'] = pd.to_datetime(stats['hour'])
            return stats
            
        except Exception as e:
            print(f"Error getting hourly stats: {e}")
            return pd.DataFrame()
        finally:
            conn.close()
    
    def generate_engagement_plot(self, hours=24):
        """Generate engagement visualization"""
        stats = self.get_hourly_stats(hours)
        
        if stats.empty:
            return None
        
        # Create a figure with two subplots
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))
        fig.suptitle('Community Engagement Overview (Last 24 Hours - IST)', fontsize=16, y=0.95)
        
        # Plot 1: Message Activity
        ax1.plot(stats['hour'], stats['total_messages'], 'b-', marker='o', label='Messages')
        ax1.plot(stats['hour'], stats['bot_responses'], 'g-', marker='s', label='Bot Responses')
        ax1.set_title('Hourly Message Activity', fontsize=12)
        ax1.set_xlabel('Hour (IST)')
        ax1.set_ylabel('Number of Messages')
        ax1.grid(True, linestyle='--', alpha=0.7)
        ax1.legend()
        
        # Format x-axis to show hours
        ax1.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter('%H:%M'))
        ax1.xaxis.set_major_locator(plt.matplotlib.dates.HourLocator(interval=2))
        
        # Plot 2: User Engagement
        ax2.plot(stats['hour'], stats['unique_users'], 'r-', marker='^', label='Active Users')
        ax2.plot(stats['hour'], stats['response_rate'] * 100, 'm-', marker='d', label='Response Rate (%)')
        ax2.set_title('User Engagement', fontsize=12)
        ax2.set_xlabel('Hour (IST)')
        ax2.set_ylabel('Count / Percentage')
        ax2.grid(True, linestyle='--', alpha=0.7)
        ax2.legend()
        
        # Format x-axis to show hours
        ax2.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter('%H:%M'))
        ax2.xaxis.set_major_locator(plt.matplotlib.dates.HourLocator(interval=2))
        
        # Rotate x-axis labels for better readability
        plt.xticks(rotation=45)
        
        # Adjust layout to prevent label cutoff
        plt.tight_layout()
        
        # Save plot
        plot_path = Path("engagement_plots")
        plot_path.mkdir(exist_ok=True)
        plt.savefig(plot_path / f"engagement_{self._get_ist_time().strftime('%Y%m%d_%H%M')}.png", 
                   bbox_inches='tight', dpi=300)
        plt.close()
        
        return plot_path / f"engagement_{self._get_ist_time().strftime('%Y%m%d_%H%M')}.png"
    
    def get_response_effectiveness(self, hours=24):
        """Calculate bot response effectiveness"""
        try:
            conn = sqlite3.connect(self.db_path)
            
            query = '''
            SELECT 
                strftime('%Y-%m-%d %H:00:00', timestamp) as hour,
                CAST(COUNT(*) AS INTEGER) as total_responses,
                CAST(SUM(has_reply) AS INTEGER) as responses_with_replies,
                CAST(AVG(has_reply) AS REAL) as response_rate
            FROM messages
            WHERE is_bot = 1
            AND timestamp >= datetime('now', ?)
            GROUP BY strftime('%Y-%m-%d %H:00:00', timestamp)
            ORDER BY hour ASC
            '''
            
            effectiveness = pd.read_sql_query(query, conn, params=(f'-{hours} hours',))
            # Convert hour strings to datetime
            effectiveness['hour'] = pd.to_datetime(effectiveness['hour'])
            return effectiveness
        except Exception as e:
            print(f"Error getting response effectiveness: {e}")
            return pd.DataFrame()
        finally:
            conn.close() 
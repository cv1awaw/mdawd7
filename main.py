# main.py
import os
import re
import sqlite3
import logging
from datetime import datetime, timedelta
from telegram import Update, ChatPermissions
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
)

DATABASE = 'warnings.db'
ADMIN_IDS = []  # Add your admin user IDs here

REGULATIONS_MESSAGE = """
**Communication Channels Regulation**

The Official Groups and channels have been created to facilitate the communication between the  
students and the officials, therefore we hereby list the regulation for the groups: 
• The official language of the group is **ENGLISH ONLY**  
• Avoid any side discussion by any means. 
• When having a general request or question it should be sent to the group and the student  
should tag the related official (TARA or other officials). 
• The messages should be sent in the official working hours (8:00 AM to 5:00 PM) and only  
important questions and inquiries should be sent after the mentioned time.

Please note that not complying with the above-mentioned regulation will result in: 
1- Primary warning sent to the student and he/she will be banned from sending messages for  
ONE DAY. 
2- Second warning sent to the student and he/she will be banned from sending messages for  
SEVEN DAYS. 
3- Third warning sent to the student and he/she will be banned from sending messages and  
May be addressed to DISCIPLINARY COMMITTEE.
"""

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS warnings (
            user_id INTEGER PRIMARY KEY,
            warnings INTEGER NOT NULL,
            banned_until TEXT
        )
    ''')
    conn.commit()
    conn.close()

def is_arabic(text):
    return bool(re.search(r'[\u0600-\u06FF]', text))

def get_user_warnings(user_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('SELECT warnings, banned_until FROM warnings WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        warnings, banned_until = row
        return warnings, banned_until
    return 0, None

def update_warnings(user_id, warnings, banned_until):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('REPLACE INTO warnings (user_id, warnings, banned_until) VALUES (?, ?, ?)',
              (user_id, warnings, banned_until))
    conn.commit()
    conn.close()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user = message.from_user
    chat = message.chat

    if chat.type not in ['group', 'supergroup']:
        return

    # Check if the bot is an admin in the chat
    try:
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
        if bot_member.status not in ['administrator', 'creator']:
            logger.info("Bot is not an admin in the chat.")
            return
    except Exception as e:
        logger.error(f"Error checking bot admin status: {e}")
        return

    warnings, banned_until = get_user_warnings(user.id)
    now = datetime.utcnow()

    if banned_until:
        try:
            banned_until_dt = datetime.strptime(banned_until, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            banned_until_dt = None

        if banned_until_dt and now < banned_until_dt:
            return
        else:
            update_warnings(user.id, warnings, None)

    if is_arabic(message.text):
        warnings += 1
        if warnings == 1:
            ban_duration = timedelta(days=1)
            reason = "1- Primary warning sent to the student and he/she will be banned from sending messages for ONE DAY."
        elif warnings == 2:
            ban_duration = timedelta(days=7)
            reason = "2- Second warning sent to the student and he/she will be banned from sending messages for SEVEN DAYS."
        else:
            ban_duration = None
            reason = "3- Third warning sent to the student and he/she will be banned from sending messages and may be addressed to DISCIPLINARY COMMITTEE."

        if ban_duration:
            banned_until = now + ban_duration
            update_warnings(user.id, warnings, banned_until.strftime('%Y-%m-%d %H:%M:%S'))
            try:
                await context.bot.restrict_chat_member(
                    chat_id=chat.id,
                    user_id=user.id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=int(banned_until.timestamp())
                )
            except Exception as e:
                logger.error(f"Error restricting user: {e}")
        else:
            update_warnings(user.id, warnings, None)
            try:
                await context.bot.ban_chat_member(chat_id=chat.id, user_id=user.id)
            except Exception as e:
                logger.error(f"Error banning user: {e}")

        # Send private message with regulations
        try:
            alarm_message = f"{REGULATIONS_MESSAGE}\n\n{reason}"
            await context.bot.send_message(
                chat_id=user.id,
                text=alarm_message,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error sending private message: {e}")

        # Removed message deletion to prevent deleting the user's message
        # If you need to keep message deletion, you can uncomment the following lines
        # try:
        #     await context.bot.delete_message(chat_id=chat.id, message_id=message.message_id)
        # except Exception as e:
        #     logger.error(f"Error deleting message: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot is running.")

def main():
    init_db()
    TOKEN = os.getenv('BOT_TOKEN')
    if not TOKEN:
        logger.error("BOT_TOKEN is not set.")
        return

    TOKEN = TOKEN.strip()

    # Ensure the token does not have the 'bot=' prefix
    if TOKEN.lower().startswith('bot='):
        TOKEN = TOKEN[len('bot='):].strip()
        logger.warning("BOT_TOKEN should not include 'bot=' prefix. Stripping it.")

    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.run_polling()

if __name__ == '__main__':
    main()

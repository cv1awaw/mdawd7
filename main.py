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
from telegram.error import Forbidden, BadRequest

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
            warnings INTEGER NOT NULL DEFAULT 0,
            banned_until INTEGER
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
    c.execute('''
        INSERT INTO warnings (user_id, warnings, banned_until) 
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET 
            warnings=excluded.warnings,
            banned_until=excluded.banned_until
    ''', (user_id, warnings, banned_until))
    conn.commit()
    conn.close()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return  # Ignore non-text messages

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
    now = datetime.utcnow().timestamp()

    if banned_until:
        if now < banned_until:
            # User is currently banned; do not process further
            logger.info(f"User {user.id} is currently banned until {datetime.fromtimestamp(banned_until)}.")
            return
        else:
            # Ban period has expired
            warnings = warnings  # Keep the warning count
            banned_until = None
            update_warnings(user.id, warnings, banned_until)

    if is_arabic(message.text):
        warnings += 1
        logger.info(f"User {user.id} has {warnings} warning(s).")
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
            banned_until = int((datetime.utcnow() + ban_duration).timestamp())
            update_warnings(user.id, warnings, banned_until)
            try:
                # Ensure the chat is a supergroup before restricting
                if chat.type == 'supergroup':
                    await context.bot.restrict_chat_member(
                        chat_id=chat.id,
                        user_id=user.id,
                        permissions=ChatPermissions(can_send_messages=False),
                        until_date=banned_until
                    )
                    logger.info(f"User {user.id} has been restricted until {datetime.fromtimestamp(banned_until)}.")
                else:
                    logger.error("Cannot restrict members in a regular group. Please convert the group to a supergroup.")
            except BadRequest as e:
                logger.error(f"BadRequest Error restricting user: {e}")
            except Exception as e:
                logger.error(f"Error restricting user: {e}")
        else:
            update_warnings(user.id, warnings, None)
            try:
                await context.bot.ban_chat_member(chat_id=chat.id, user_id=user.id)
                logger.info(f"User {user.id} has been banned permanently.")
            except BadRequest as e:
                logger.error(f"BadRequest Error banning user: {e}")
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
            logger.info(f"Alarm message sent to user {user.id}.")
        except Forbidden:
            logger.error("Cannot send private message to the user. They might not have started a conversation with the bot.")
            # Send a message in the group notifying the user to start a private chat
            try:
                notification = f"{user.first_name}, please start a private chat with me to receive warnings and regulations."
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=notification
                )
                logger.info(f"Notification sent in group for user {user.id}.")
            except Exception as e:
                logger.error(f"Error sending notification in group: {e}")
        except Exception as e:
            logger.error(f"Error sending private message: {e}")

        # Removed message deletion to prevent deleting the user's message

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

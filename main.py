# main.py
import os
import re
import aiosqlite
import logging
from datetime import datetime
from telegram import Update
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

async def init_db():
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS warnings (
                user_id INTEGER PRIMARY KEY,
                warnings INTEGER NOT NULL DEFAULT 0
            )
        ''')
        await db.commit()

def is_arabic(text):
    return bool(re.search(r'[\u0600-\u06FF]', text))

async def get_user_warnings(user_id):
    async with aiosqlite.connect(DATABASE) as db:
        async with db.execute('SELECT warnings FROM warnings WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                (warnings,) = row
                return warnings
            return 0

async def update_warnings(user_id, warnings):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute('''
            INSERT INTO warnings (user_id, warnings) 
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET 
                warnings=excluded.warnings
        ''', (user_id, warnings))
        await db.commit()

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

    if is_arabic(message.text):
        warnings = await get_user_warnings(user.id) + 1
        logger.info(f"User {user.id} has {warnings} warning(s).")

        if warnings == 1:
            reason = "1- Primary warning sent to the student."
        elif warnings == 2:
            reason = "2- Second warning sent to the student."
        else:
            reason = "3- Third warning sent to the student. May be addressed to DISCIPLINARY COMMITTEE."

        await update_warnings(user.id, warnings)

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
    import asyncio
    asyncio.run(init_db())
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

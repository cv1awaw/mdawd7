# main.py
import os
import re
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, ChatPermissions
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext, CommandHandler

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

def handle_message(update: Update, context: CallbackContext):
    message = update.message
    user = message.from_user
    chat = message.chat

    if chat.type not in ['group', 'supergroup']:
        return

    warnings, banned_until = get_user_warnings(user.id)
    now = datetime.utcnow()

    if banned_until:
        banned_until_dt = datetime.strptime(banned_until, '%Y-%m-%d %H:%M:%S')
        if now < banned_until_dt:
            try:
                context.bot.delete_message(chat_id=chat.id, message_id=message.message_id)
            except:
                pass
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
            until_timestamp = int(banned_until.timestamp())
            context.bot.restrict_chat_member(
                chat_id=chat.id,
                user_id=user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until_timestamp
            )
        else:
            update_warnings(user.id, warnings, None)
            context.bot.kick_chat_member(chat_id=chat.id, user_id=user.id)

        # Send private message with regulations
        try:
            alarm_message = f"{REGULATIONS_MESSAGE}\n\n{reason}"
            context.bot.send_message(
                chat_id=user.id,
                text=alarm_message,
                parse_mode='Markdown'
            )
        except:
            pass

        # Delete the offending message
        try:
            context.bot.delete_message(chat_id=chat.id, message_id=message.message_id)
        except:
            pass

def start(update: Update, context: CallbackContext):
    update.message.reply_text("Bot is running.")

def main():
    init_db()
    TOKEN = os.getenv('BOT_TOKEN')
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()

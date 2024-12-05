import os
import re
import sqlite3
import logging
from datetime import datetime
from telegram import Update, ForceReply
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
    ConversationHandler,
    CallbackContext,
)
from telegram.error import Forbidden, BadRequest

# Constants for Conversation States
GROUP_NAME, GROUP_CUSTOM_ID, CHANGE_NAME = range(3)

DATABASE = 'warnings.db'
AUTHORIZED_USER_ID = 6177929931  # Only this user can execute admin commands

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
1- Primary warning sent to the student.
2- Second warning sent to the student.
3- Third warning sent to the student. May be addressed to DISCIPLINARY COMMITTEE.
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
    # Existing warnings table
    c.execute('''
        CREATE TABLE IF NOT EXISTS warnings (
            user_id INTEGER PRIMARY KEY,
            warnings INTEGER NOT NULL DEFAULT 0
        )
    ''')
    # New warnings_history table
    c.execute('''
        CREATE TABLE IF NOT EXISTS warnings_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            warning_number INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES warnings(user_id)
        )
    ''')
    # New groups table
    c.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            group_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            group_custom_id TEXT NOT NULL
        )
    ''')
    # New admins table
    c.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY
        )
    ''')
    conn.commit()
    conn.close()

def is_arabic(text):
    return bool(re.search(r'[\u0600-\u06FF]', text))

def get_user_warnings(user_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('SELECT warnings FROM warnings WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        (warnings,) = row
        return warnings
    return 0

def update_warnings(user_id, warnings):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO warnings (user_id, warnings) 
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET 
            warnings=excluded.warnings
    ''', (user_id, warnings))
    conn.commit()
    conn.close()

def log_warning(user_id, warning_number):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    c.execute('''
        INSERT INTO warnings_history (user_id, warning_number, timestamp)
        VALUES (?, ?, ?)
    ''', (user_id, warning_number, timestamp))
    conn.commit()
    conn.close()

def load_admin_ids():
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('SELECT user_id FROM admins')
        rows = c.fetchall()
        conn.close()
        admin_ids = [row[0] for row in rows]
        return admin_ids
    except Exception as e:
        logger.error(f"Error loading admin IDs from database: {e}")
        return []

def add_admin(user_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (user_id,))
    conn.commit()
    conn.close()

def remove_admin(user_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('DELETE FROM admins WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def is_authorized(user_id):
    return user_id == AUTHORIZED_USER_ID

def add_group_to_db(group_id, name, group_custom_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('INSERT INTO groups (group_id, name, group_custom_id) VALUES (?, ?, ?)', 
              (group_id, name, group_custom_id))
    conn.commit()
    conn.close()

def remove_group_from_db(group_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('DELETE FROM groups WHERE group_id = ?', (group_id,))
    conn.commit()
    conn.close()

def change_group_name_in_db(group_id, new_name):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('UPDATE groups SET name = ? WHERE group_id = ?', (new_name, group_id))
    conn.commit()
    conn.close()

def get_group_from_db(group_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('SELECT name, group_custom_id FROM groups WHERE group_id = ?', (group_id,))
    row = c.fetchone()
    conn.close()
    return row

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return  # Ignore non-text messages

    user = message.from_user
    chat = message.chat

    if chat.type not in ['group', 'supergroup']:
        return

    if is_arabic(message.text):
        warnings = get_user_warnings(user.id) + 1
        logger.info(f"User {user.id} has {warnings} warning(s).")

        if warnings == 1:
            reason = "1- Primary warning sent to the student."
        elif warnings == 2:
            reason = "2- Second warning sent to the student."
        else:
            reason = "3- Third warning sent to the student. May be addressed to DISCIPLINARY COMMITTEE."

        update_warnings(user.id, warnings)
        log_warning(user.id, warnings)  # Log the warning with timestamp

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
            
            # **New Code: Notify admins that the user hasn't started the bot**
            admin_ids = load_admin_ids()
            if admin_ids:
                username = f"@{user.username}" if user.username else "NoUsername"
                notification_message = (
                    f"⚠️ **Notification:**\n"
                    f"**User ID:** {user.id}\n"
                    f"**Username:** {username}\n"
                    f"**Issue:** The user has triggered a warning but hasn't started a private conversation with the bot.\n"
                    f"**Action Needed:** Please reach out to the user to ensure they start a conversation with the bot to receive warnings."
                )
                for admin_id in admin_ids:
                    try:
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=notification_message,
                            parse_mode='Markdown'
                        )
                        logger.info(f"Notification sent to admin {admin_id} about user {user.id} not starting the bot.")
                    except Forbidden:
                        logger.error(f"Cannot send notification to admin ID {admin_id}. They might have blocked the bot.")
                    except Exception as e:
                        logger.error(f"Error sending notification to admin ID {admin_id}: {e}")
            else:
                logger.warning("No admin IDs found in the database to notify about the user not starting the bot.")
            
            # Optionally, you can notify the group that the user hasn't started the bot
            # Uncomment the following lines if you want to notify the group as well
            # try:
            #     await message.reply_text(
            #         f"⚠️ {user.mention_html()} has triggered a warning but hasn't started a private conversation with the bot. Please ensure they are aware of this requirement.",
            #         parse_mode='HTML'
            #     )
            # except Exception as e:
            #     logger.error(f"Error notifying group about user {user.id}: {e}")

        except Exception as e:
            logger.error(f"Error sending private message: {e}")

        # Notify admins about the number of alarms
        admin_ids = load_admin_ids()
        if not admin_ids:
            logger.warning("No admin IDs found in the database.")
            return

        # Construct the alarm report message
        username = f"@{user.username}" if user.username else "NoUsername"
        alarm_report = (
            f"**Alarm Report**\n"
            f"**Student ID:** {user.id}\n"
            f"**Username:** {username}\n"
            f"**Number of Alarms:** {warnings}\n"
            f"**Date:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )

        for admin_id in admin_ids:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=alarm_report,
                    parse_mode='Markdown'
                )
                logger.info(f"Alarm report sent to admin {admin_id}.")
            except Forbidden:
                logger.error(f"Cannot send message to admin ID {admin_id}. They might have blocked the bot.")
            except Exception as e:
                logger.error(f"Error sending message to admin ID {admin_id}: {e}")

        # Optionally, you can log this event or save it to a file for auditing

# Conversation handler for adding a group
async def start_group_addition(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user.id):
        await update.message.reply_text("You are not authorized to use this command.")
        return ConversationHandler.END

    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("This command can only be used in groups.")
        return ConversationHandler.END

    group_id = chat.id
    context.user_data['group_id'] = group_id
    await update.message.reply_text("Please provide a name for this group.")
    return GROUP_NAME

async def receive_group_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_name = update.message.text.strip()
    if not group_name:
        await update.message.reply_text("Group name cannot be empty. Please provide a valid name.")
        return GROUP_NAME
    context.user_data['group_name'] = group_name
    await update.message.reply_text("Please provide a custom ID for this group.")
    return GROUP_CUSTOM_ID

async def receive_group_custom_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_custom_id = update.message.text.strip()
    if not group_custom_id:
        await update.message.reply_text("Group custom ID cannot be empty. Please provide a valid custom ID.")
        return GROUP_CUSTOM_ID

    group_id = context.user_data['group_id']
    group_name = context.user_data['group_name']

    # Save to database
    try:
        add_group_to_db(group_id, group_name, group_custom_id)
        await update.message.reply_text(f"Group '{group_name}' with custom ID '{group_custom_id}' has been added successfully.")
        logger.info(f"Added group: ID={group_id}, Name={group_name}, Custom ID={group_custom_id}")
    except sqlite3.IntegrityError:
        await update.message.reply_text("This group is already registered.")
        logger.warning(f"Attempted to add an existing group: ID={group_id}")
    except Exception as e:
        await update.message.reply_text("An error occurred while adding the group.")
        logger.error(f"Error adding group: {e}")

    return ConversationHandler.END

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

# Command handler for adding Tara (admin)
async def tara_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user.id):
        await update.message.reply_text("You are not authorized to use this command.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("Usage: /tara <user_id>")
        return

    try:
        tara_id = int(context.args[0])
        add_admin(tara_id)
        await update.message.reply_text(f"User ID {tara_id} has been added as an admin.")
        logger.info(f"Added admin: {tara_id}")
    except ValueError:
        await update.message.reply_text("Please provide a valid numeric user ID.")
    except Exception as e:
        await update.message.reply_text("An error occurred while adding the admin.")
        logger.error(f"Error adding admin: {e}")

# Command handler for removing Tara (admin)
async def remove_tara_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user.id):
        await update.message.reply_text("You are not authorized to use this command.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("Usage: /remove <user_id>")
        return

    try:
        tara_id = int(context.args[0])
        remove_admin(tara_id)
        await update.message.reply_text(f"User ID {tara_id} has been removed from admins.")
        logger.info(f"Removed admin: {tara_id}")
    except ValueError:
        await update.message.reply_text("Please provide a valid numeric user ID.")
    except Exception as e:
        await update.message.reply_text("An error occurred while removing the admin.")
        logger.error(f"Error removing admin: {e}")

# Command handler for removing a group
async def remove_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user.id):
        await update.message.reply_text("You are not authorized to use this command.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("Usage: /remove_group <group_id>")
        return

    try:
        group_id = int(context.args[0])
        group = get_group_from_db(group_id)
        if not group:
            await update.message.reply_text("Group ID not found.")
            return
        remove_group_from_db(group_id)
        await update.message.reply_text(f"Group ID {group_id} has been removed from the bot's memory.")
        logger.info(f"Removed group: ID={group_id}")
    except ValueError:
        await update.message.reply_text("Please provide a valid numeric group ID.")
    except Exception as e:
        await update.message.reply_text("An error occurred while removing the group.")
        logger.error(f"Error removing group: {e}")

# Conversation handler for changing a group's name
async def change_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user.id):
        await update.message.reply_text("You are not authorized to use this command.")
        return ConversationHandler.END

    if len(context.args) != 1:
        await update.message.reply_text("Usage: /change <group_id>")
        return ConversationHandler.END

    try:
        group_id = int(context.args[0])
        group = get_group_from_db(group_id)
        if not group:
            await update.message.reply_text("Group ID not found.")
            return ConversationHandler.END
        context.user_data['change_group_id'] = group_id
        await update.message.reply_text(f"Current group name is '{group[0]}'. Please provide the new name for this group.")
        return CHANGE_NAME
    except ValueError:
        await update.message.reply_text("Please provide a valid numeric group ID.")
        return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text("An error occurred while initiating the name change.")
        logger.error(f"Error initiating group name change: {e}")
        return ConversationHandler.END

async def receive_new_group_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_name = update.message.text.strip()
    if not new_name:
        await update.message.reply_text("Group name cannot be empty. Please provide a valid name.")
        return CHANGE_NAME
    group_id = context.user_data['change_group_id']
    try:
        change_group_name_in_db(group_id, new_name)
        await update.message.reply_text(f"Group ID {group_id} has been renamed to '{new_name}'.")
        logger.info(f"Changed group name: ID={group_id}, New Name={new_name}")
    except Exception as e:
        await update.message.reply_text("An error occurred while changing the group name.")
        logger.error(f"Error changing group name: {e}")
    return ConversationHandler.END

# Command handler for /start in groups (to add a group)
group_add_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('start', start_group_addition)],
    states={
        GROUP_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_group_name)],
        GROUP_CUSTOM_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_group_custom_id)],
    },
    fallbacks=[CommandHandler('cancel', cancel_conversation)],
    allow_reentry=True,
)

# Conversation handler for changing group name
change_group_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('change', change_group_command, pass_args=True)],
    states={
        CHANGE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_group_name)],
    },
    fallbacks=[CommandHandler('cancel', cancel_conversation)],
    allow_reentry=True,
)

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

    # Handlers for existing functionalities
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Admin command handlers
    application.add_handler(CommandHandler("tara", tara_command))
    application.add_handler(CommandHandler("remove", remove_tara_command))
    application.add_handler(CommandHandler("remove_group", remove_group_command))

    # Conversation handlers
    application.add_handler(group_add_conv_handler)
    application.add_handler(change_group_conv_handler)

    application.run_polling()

if __name__ == '__main__':
    main()

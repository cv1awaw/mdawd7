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
)
from telegram.error import Forbidden, BadRequest

# ------------------ Constants ------------------

DATABASE = 'warnings.db'
GROUPS_FILE = 'groups.json'  # Optional if you prefer JSON over SQLite
ADMIN_IDS = []  # Not used anymore since we load from Tara_access.txt

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

# ------------------ Setup Logging ------------------

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO  # Changed to INFO to reduce verbosity
)
logger = logging.getLogger(__name__)

# ------------------ Database Initialization ------------------

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
            group_name TEXT NOT NULL,
            tara_team_id INTEGER NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

# ------------------ Helper Functions ------------------

def is_arabic(text):
    """Check if the text contains Arabic characters."""
    return bool(re.search(r'[\u0600-\u06FF]', text))

def get_user_warnings(user_id):
    """Retrieve the number of warnings a user has."""
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
    """Update the number of warnings for a user."""
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
    """Log a warning event with timestamp."""
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
    """Load admin IDs from Tara_access.txt."""
    try:
        with open('Tara_access.txt', 'r') as file:
            admin_ids = [int(line.strip()) for line in file if line.strip().isdigit()]
        logger.info(f"Loaded {len(admin_ids)} admin IDs from Tara_access.txt.")
        return admin_ids
    except FileNotFoundError:
        logger.error("Tara_access.txt not found! Please create the file and add admin Telegram user IDs.")
        return []
    except ValueError as e:
        logger.error(f"Error parsing admin IDs: {e}")
        return []

def get_display_name(user):
    """Return the display name for a user."""
    if user.username:
        return f"@{user.username}"
    else:
        full_name = f"{user.first_name} {user.last_name}" if user.last_name else user.first_name
        return full_name

async def notify_admins(context, message_text):
    """Send a notification message to all admins."""
    admin_ids = load_admin_ids()
    if not admin_ids:
        logger.warning("No admin IDs found to send notifications.")
        return
    for admin_id in admin_ids:
        try:
            await context.bot.send_message(chat_id=admin_id, text=message_text, parse_mode='Markdown')
            logger.info(f"Notification sent to admin {admin_id}.")
        except Forbidden:
            logger.error(f"Cannot send message to admin ID {admin_id}. They might have blocked the bot.")
        except Exception as e:
            logger.error(f"Error sending message to admin ID {admin_id}: {e}")

# ------------------ Command Handlers ------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /start command in group for registration."""
    message = update.message
    chat = message.chat
    user = message.from_user

    if chat.type not in ['group', 'supergroup']:
        return

    # Check if the user is an admin
    member = await chat.get_member(user.id)
    if not member.can_manage_chat:
        await message.reply_text("Only group admins can register the group with this bot.")
        logger.warning(f"Non-admin user {user.id} attempted to register the group.")
        return

    # Start the registration conversation
    await GroupRegistration.GROUP_NAME.set()
    await message.reply_text("Please enter the **name of the group**.", parse_mode='Markdown')

class GroupRegistration:
    GROUP_NAME, TARA_TEAM_ID = range(2)

async def group_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the group name input."""
    group_name = update.message.text.strip()
    if not group_name:
        await update.message.reply_text("Group name cannot be empty. Please enter a valid group name.", parse_mode='Markdown')
        return GroupRegistration.GROUP_NAME

    context.user_data['group_name'] = group_name
    await GroupRegistration.next()
    await update.message.reply_text("Please enter the **Tara Team ID** for this group.", parse_mode='Markdown')

async def tara_team_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the Tara Team ID input and save the group info."""
    try:
        tara_team_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Invalid ID. Please enter a numeric **Tara Team ID**.", parse_mode='Markdown')
        return GroupRegistration.TARA_TEAM_ID

    group_name = context.user_data.get('group_name')
    group_id = update.message.chat.id

    # Save to the database
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO groups (group_id, group_name, tara_team_id)
        VALUES (?, ?, ?)
        ON CONFLICT(group_id) DO UPDATE SET 
            group_name=excluded.group_name,
            tara_team_id=excluded.tara_team_id
    ''', (group_id, group_name, tara_team_id))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ **Group '{group_name}' has been registered successfully!**", parse_mode='Markdown')
    logger.info(f"Group '{group_name}' (ID: {group_id}) registered with Tara Team ID: {tara_team_id}.")

    # Notify admins about the new registration
    notification = (
        f"**New Group Registered**\n"
        f"**Group Name:** {group_name}\n"
        f"**Group ID:** {group_id}\n"
        f"**Tara Team ID:** {tara_team_id}"
    )
    await notify_admins(context, notification)

    return ConversationHandler.END

async def cancel_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the cancellation of group registration."""
    await update.message.reply_text("Group registration has been cancelled.", parse_mode='Markdown')
    logger.info(f"Group registration cancelled by user {update.effective_user.id}.")
    return ConversationHandler.END

# ------------------ Adding More Groups ------------------

async def add_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the /add_groupname command to add a new group.
    Usage: /add_groupname <group_name> <tara_team_id>
    Example: /add_WritersGroup 123456789
    """
    message = update.message
    chat = message.chat
    user = message.from_user

    if chat.type not in ['group', 'supergroup']:
        return

    # Check if the user is an admin
    member = await chat.get_member(user.id)
    if not member.can_manage_chat:
        await message.reply_text("Only group admins can add new groups with this command.")
        logger.warning(f"Non-admin user {user.id} attempted to add a new group.")
        return

    args = context.args
    if len(args) < 2:
        await message.reply_text("Usage: `/add_groupname <group_name> <tara_team_id>`", parse_mode='Markdown')
        return

    group_name = args[0].strip()
    try:
        tara_team_id = int(args[1].strip())
    except ValueError:
        await message.reply_text("Invalid Tara Team ID. It must be a numeric value.", parse_mode='Markdown')
        return

    group_id = chat.id

    # Save to the database
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO groups (group_id, group_name, tara_team_id)
        VALUES (?, ?, ?)
        ON CONFLICT(group_id) DO UPDATE SET 
            group_name=excluded.group_name,
            tara_team_id=excluded.tara_team_id
    ''', (group_id, group_name, tara_team_id))
    conn.commit()
    conn.close()

    await message.reply_text(f"✅ **Group '{group_name}' has been added successfully!**", parse_mode='Markdown')
    logger.info(f"Group '{group_name}' (ID: {group_id}) added with Tara Team ID: {tara_team_id}.")

    # Notify admins about the new addition
    notification = (
        f"**Group Added**\n"
        f"**Group Name:** {group_name}\n"
        f"**Group ID:** {group_id}\n"
        f"**Tara Team ID:** {tara_team_id}"
    )
    await notify_admins(context, notification)

# ------------------ Warning Handler ------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages in groups and issue warnings if necessary."""
    message = update.message
    if not message or not message.text:
        return  # Ignore non-text messages

    user = message.from_user
    chat = message.chat

    if chat.type not in ['group', 'supergroup']:
        return

    # Check if the user is an admin; if so, ignore
    member = await chat.get_member(user.id)
    if member.status in ['administrator', 'creator']:
        return  # Admins are exempt from warnings

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

            # Notify admins that the user hasn't started the bot
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
                logger.warning("No admin IDs found in Tara_access.txt to notify about the user not starting the bot.")

        except Exception as e:
            logger.error(f"Error sending private message: {e}")

        # Notify admins about the number of alarms
        admin_ids = load_admin_ids()
        if not admin_ids:
            logger.warning("No admin IDs found in Tara_access.txt.")
            return

        # Retrieve the group information
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('SELECT group_name FROM groups WHERE group_id = ?', (chat.id,))
        row = c.fetchone()
        conn.close()

        group_name = row[0] if row else f"ID: {chat.id}"

        # Construct the alarm report message
        username = f"@{user.username}" if user.username else "NoUsername"
        alarm_report = (
            f"**Alarm Report**\n"
            f"**Student ID:** {user.id}\n"
            f"**Username:** {username}\n"
            f"**Number of Alarms:** {warnings}\n"
            f"**Group:** {group_name}\n"
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

# ------------------ Main Function ------------------

def main():
    """Main function to start the Telegram bot."""
    init_db()
    TOKEN = os.getenv('BOT_TOKEN')
    if not TOKEN:
        logger.error("BOT_TOKEN is not set. Please set the BOT_TOKEN environment variable.")
        return

    TOKEN = TOKEN.strip()

    # Ensure the token does not have the 'bot=' prefix
    if TOKEN.lower().startswith('bot='):
        TOKEN = TOKEN[len('bot='):].strip()
        logger.warning("BOT_TOKEN should not include 'bot=' prefix. Stripping it.")

    application = ApplicationBuilder().token(TOKEN).build()

    # Conversation handler for group registration using /start
    registration_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            GroupRegistration.GROUP_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, group_name)],
            GroupRegistration.TARA_TEAM_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, tara_team_id)],
        },
        fallbacks=[CommandHandler('cancel', cancel_registration)],
        allow_reentry=True,
    )

    # Add handlers
    application.add_handler(registration_conv_handler)
    application.add_handler(CommandHandler("add_groupname", add_group))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Start the bot
    logger.info("Bot started polling...")
    application.run_polling()

if __name__ == '__main__':
    main()

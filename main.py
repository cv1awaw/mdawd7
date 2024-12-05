import os
import re
import sqlite3
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
    ConversationHandler,
)
from telegram.error import Forbidden, BadRequest

# Constants
DATABASE = 'warnings.db'
TARA_ACCESS_FILE = 'Tara_access.txt'
PRIMARY_ADMIN_ID = 6177929931  # The main admin who can add/remove TARA

# States for ConversationHandler
SET_WARNING, CONFIRM_WARNING = range(2)

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
        with open(TARA_ACCESS_FILE, 'r') as file:
            admin_ids = [int(line.strip()) for line in file if line.strip().isdigit()]
        return admin_ids
    except FileNotFoundError:
        logger.error(f"{TARA_ACCESS_FILE} not found! Please create the file and add admin Telegram user IDs.")
        return []
    except ValueError as e:
        logger.error(f"Error parsing admin IDs: {e}")
        return []

def save_admin_ids(admin_ids):
    try:
        with open(TARA_ACCESS_FILE, 'w') as file:
            for admin_id in admin_ids:
                file.write(f"{admin_id}\n")
        logger.info("Admin IDs have been updated successfully.")
    except Exception as e:
        logger.error(f"Error saving admin IDs: {e}")

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
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(f"Alarm message sent to user {user.id}.")
        except Forbidden:
            logger.error("Cannot send private message to the user. They might not have started a conversation with the bot.")
            
            # **New Code: Notify admins that the user hasn't started the bot**
            admin_ids = load_admin_ids()
            if admin_ids:
                username = f"@{user.username}" if user.username else user.full_name
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
                            parse_mode=ParseMode.MARKDOWN
                        )
                        logger.info(f"Notification sent to admin {admin_id} about user {user.id} not starting the bot.")
                    except Forbidden:
                        logger.error(f"Cannot send notification to admin ID {admin_id}. They might have blocked the bot.")
                    except Exception as e:
                        logger.error(f"Error sending notification to admin ID {admin_id}: {e}")
            else:
                logger.warning(f"No admin IDs found in {TARA_ACCESS_FILE} to notify about the user not starting the bot.")
            
            # Optionally, you can notify the group that the user hasn't started the bot
            # Uncomment the following lines if you want to notify the group as well
            # try:
            #     await message.reply_text(
            #         f"⚠️ {user.mention_html()} has triggered a warning but hasn't started a private conversation with the bot. Please ensure they are aware of this requirement.",
            #         parse_mode=ParseMode.HTML
            #     )
            # except Exception as e:
            #     logger.error(f"Error notifying group about user {user.id}: {e}")

        except Exception as e:
            logger.error(f"Error sending private message: {e}")

        # Notify admins about the number of alarms
        admin_ids = load_admin_ids()
        if not admin_ids:
            logger.warning(f"No admin IDs found in {TARA_ACCESS_FILE}.")
            return

        # Construct the alarm report message
        username = f"@{user.username}" if user.username else user.full_name
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
                    parse_mode=ParseMode.MARKDOWN
                )
                logger.info(f"Alarm report sent to admin {admin_id}.")
            except Forbidden:
                logger.error(f"Cannot send message to admin ID {admin_id}. They might have blocked the bot.")
            except Exception as e:
                logger.error(f"Error sending message to admin ID {admin_id}: {e}")

        # Optionally, you can log this event or save it to a file for auditing

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot is running.")

# /tara command handler
async def add_tara(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != PRIMARY_ADMIN_ID:
        await update.message.reply_text("You do not have permission to use this command.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("Usage: /tara <user_id>")
        return

    try:
        new_tara_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Please provide a valid numeric user ID.")
        return

    admin_ids = load_admin_ids()
    if new_tara_id in admin_ids:
        await update.message.reply_text("This user is already a TARA.")
        return

    admin_ids.append(new_tara_id)
    save_admin_ids(admin_ids)
    await update.message.reply_text(f"User ID {new_tara_id} has been added as a TARA.")
    logger.info(f"User ID {new_tara_id} added as TARA by {user_id}.")

# /rmove command handler
async def remove_tara(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != PRIMARY_ADMIN_ID:
        await update.message.reply_text("You do not have permission to use this command.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("Usage: /rmove <user_id>")
        return

    try:
        tara_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Please provide a valid numeric user ID.")
        return

    admin_ids = load_admin_ids()
    if tara_id not in admin_ids:
        await update.message.reply_text("This user is not a TARA.")
        return

    admin_ids.remove(tara_id)
    save_admin_ids(admin_ids)
    await update.message.reply_text(f"User ID {tara_id} has been removed from TARA.")
    logger.info(f"User ID {tara_id} removed from TARA by {user_id}.")

# /information command handler
async def information(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    admin_ids = load_admin_ids()
    if user_id not in admin_ids:
        await update.message.reply_text("You do not have permission to use this command.")
        return

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('SELECT user_id, warnings FROM warnings')
    users = c.fetchall()
    conn.close()

    if not users:
        await update.message.reply_text("No users have received warnings yet.")
        return

    report_lines = ["**Warnings Report:**\n"]
    for uid, warns in users:
        try:
            user = await context.bot.get_chat(uid)
            username = f"@{user.username}" if user.username else user.full_name
        except Exception:
            username = "Unknown"

        # Fetch latest warning date
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('''
            SELECT timestamp FROM warnings_history 
            WHERE user_id = ? 
            ORDER BY id DESC 
            LIMIT 1
        ''', (uid,))
        row = c.fetchone()
        conn.close()
        last_warning = row[0] if row else "N/A"

        report_lines.append(
            f"**Id:** {uid}\n"
            f"**Username:** {username}\n"
            f"**Warning number:** {warns}\n"
            f"**Date:** {last_warning} UTC\n"
        )

    report = "\n".join(report_lines)
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=report,
            parse_mode=ParseMode.MARKDOWN
        )
        logger.info(f"Warnings report sent to TARA {user_id}.")
    except Forbidden:
        logger.error(f"Cannot send warnings report to TARA {user_id}. They might have blocked the bot.")
    except Exception as e:
        logger.error(f"Error sending warnings report to TARA {user_id}: {e}")

# /set command handler - starts the conversation
async def set_warning_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != PRIMARY_ADMIN_ID:
        await update.message.reply_text("You do not have permission to use this command.")
        return ConversationHandler.END

    if len(context.args) != 1:
        await update.message.reply_text("Usage: /set <user_id>")
        return ConversationHandler.END

    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Please provide a valid numeric user ID.")
        return ConversationHandler.END

    context.user_data['target_user_id'] = target_user_id
    await update.message.reply_text("Please enter the number of warnings to set:")
    return SET_WARNING

# /set command handler - receives the number of warnings
async def set_warning_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        warnings = int(update.message.text.strip())
        if warnings < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Please enter a valid non-negative integer for warnings.")
        return SET_WARNING

    context.user_data['set_warnings'] = warnings
    target_user_id = context.user_data['target_user_id']
    
    # Fetch user information
    try:
        user = await context.bot.get_chat(target_user_id)
        username = f"@{user.username}" if user.username else user.full_name
    except Exception:
        username = "Unknown"

    confirmation_message = (
        f"Are you sure you want to set {warnings} warnings for the following user?\n\n"
        f"**Id:** {target_user_id}\n"
        f"**Username:** {username}"
    )
    # Create inline keyboard for confirmation
    keyboard = [
        [
            InlineKeyboardButton("Confirm", callback_data='confirm_set_warning'),
            InlineKeyboardButton("Cancel", callback_data='cancel_set_warning')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(confirmation_message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    return CONFIRM_WARNING

# /set command handler - confirms or cancels the setting
async def set_warning_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'confirm_set_warning':
        target_user_id = context.user_data['target_user_id']
        warnings = context.user_data['set_warnings']
        update_warnings(target_user_id, warnings)
        log_warning(target_user_id, warnings)
        await query.edit_message_text(f"Set {warnings} warnings for user ID {target_user_id}.")
        logger.info(f"Set {warnings} warnings for user ID {target_user_id} by {update.effective_user.id}.")
    else:
        await query.edit_message_text("Setting warnings canceled.")
    return ConversationHandler.END

def cancel_set_warning(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update.message.reply_text("Setting warnings canceled.")
    return ConversationHandler.END

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

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("tara", add_tara))
    application.add_handler(CommandHandler("rmove", remove_tara))
    application.add_handler(CommandHandler("information", information))

    # ConversationHandler for /set command
    set_warning_conv = ConversationHandler(
        entry_points=[CommandHandler('set', set_warning_start)],
        states={
            SET_WARNING: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_warning_number)],
            CONFIRM_WARNING: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_warning_confirm)],
        },
        fallbacks=[CommandHandler('cancel', cancel_set_warning)],
    )
    application.add_handler(set_warning_conv)

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.run_polling()

if __name__ == '__main__':
    main()

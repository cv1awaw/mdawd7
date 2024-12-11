# delete.py

import sqlite3
import logging
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters
from telegram.helpers import escape_markdown

# Configure logger
logger = logging.getLogger(__name__)

# Define the path to the SQLite database
DATABASE = 'warnings.db'

# ------------------- Database Helper Functions -------------------

def enable_deletion(group_id):
    """
    Enable message deletion for a specific group.
    """
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('''
            INSERT INTO deletion_settings (group_id, enabled)
            VALUES (?, 1)
            ON CONFLICT(group_id) DO UPDATE SET enabled=1
        ''', (group_id,))
        conn.commit()
        conn.close()
        logger.info(f"Enabled message deletion for group {group_id}.")
    except Exception as e:
        logger.error(f"Error enabling deletion for group {group_id}: {e}")
        raise

def disable_deletion(group_id):
    """
    Disable message deletion for a specific group.
    """
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('''
            INSERT INTO deletion_settings (group_id, enabled)
            VALUES (?, 0)
            ON CONFLICT(group_id) DO UPDATE SET enabled=0
        ''', (group_id,))
        conn.commit()
        conn.close()
        logger.info(f"Disabled message deletion for group {group_id}.")
    except Exception as e:
        logger.error(f"Error disabling deletion for group {group_id}: {e}")
        raise

def is_deletion_enabled(group_id):
    """
    Check if message deletion is enabled for a specific group.
    """
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('SELECT enabled FROM deletion_settings WHERE group_id = ?', (group_id,))
        row = c.fetchone()
        conn.close()
        enabled = row[0] if row else False
        logger.debug(f"Deletion enabled for group {group_id}: {enabled}")
        return bool(enabled)
    except Exception as e:
        logger.error(f"Error checking deletion status for group {group_id}: {e}")
        return False

# ------------------- Command Handler Functions -------------------

async def be_sad_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the /be_sad command to enable message deletion in a group.
    Usage: /be_sad <group_id>
    """
    user = update.effective_user
    args = context.args
    logger.debug(f"/be_sad called by user {user.id} with args: {args}")

    # Check if the user is authorized
    if user.id not in [111111, 6177929931]:
        message = escape_markdown("❌ You don't have permission to use this command.", version=2)
        await update.message.reply_text(
            message,
            parse_mode='MarkdownV2'
        )
        logger.warning(f"Unauthorized /be_sad attempt by user {user.id}")
        return

    if len(args) != 1:
        message = escape_markdown("⚠️ Usage: `/be_sad <group_id>`", version=2)
        await update.message.reply_text(
            message,
            parse_mode='MarkdownV2'
        )
        logger.warning(f"Incorrect usage of /be_sad by user {user.id}")
        return

    try:
        group_id = int(args[0])
    except ValueError:
        message = escape_markdown("⚠️ `group_id` must be an integer.", version=2)
        await update.message.reply_text(
            message,
            parse_mode='MarkdownV2'
        )
        logger.warning(f"Non-integer group_id provided to /be_sad by user {user.id}")
        return

    # Enable deletion
    try:
        enable_deletion(group_id)
    except Exception:
        message = escape_markdown("⚠️ Failed to enable message deletion. Please try again later.", version=2)
        await update.message.reply_text(
            message,
            parse_mode='MarkdownV2'
        )
        return

    # Confirm to the admin
    confirmation_message = escape_markdown(
        f"✅ Message deletion enabled for group `{group_id}`.",
        version=2
    )
    await update.message.reply_text(
        confirmation_message,
        parse_mode='MarkdownV2'
    )
    logger.info(f"User {user.id} enabled message deletion for group {group_id}.")

async def be_happy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the /be_happy command to disable message deletion in a group.
    Usage: /be_happy <group_id>
    """
    user = update.effective_user
    args = context.args
    logger.debug(f"/be_happy called by user {user.id} with args: {args}")

    # Check if the user is authorized
    if user.id not in [111111, 6177929931]:
        message = escape_markdown("❌ You don't have permission to use this command.", version=2)
        await update.message.reply_text(
            message,
            parse_mode='MarkdownV2'
        )
        logger.warning(f"Unauthorized /be_happy attempt by user {user.id}")
        return

    if len(args) != 1:
        message = escape_markdown("⚠️ Usage: `/be_happy <group_id>`", version=2)
        await update.message.reply_text(
            message,
            parse_mode='MarkdownV2'
        )
        logger.warning(f"Incorrect usage of /be_happy by user {user.id}")
        return

    try:
        group_id = int(args[0])
    except ValueError:
        message = escape_markdown("⚠️ `group_id` must be an integer.", version=2)
        await update.message.reply_text(
            message,
            parse_mode='MarkdownV2'
        )
        logger.warning(f"Non-integer group_id provided to /be_happy by user {user.id}")
        return

    # Disable deletion
    try:
        disable_deletion(group_id)
    except Exception:
        message = escape_markdown("⚠️ Failed to disable message deletion. Please try again later.", version=2)
        await update.message.reply_text(
            message,
            parse_mode='MarkdownV2'
        )
        return

    # Confirm to the admin
    confirmation_message = escape_markdown(
        f"✅ Message deletion disabled for group `{group_id}`.",
        version=2
    )
    await update.message.reply_text(
        confirmation_message,
        parse_mode='MarkdownV2'
    )
    logger.info(f"User {user.id} disabled message deletion for group {group_id}.")

# ------------------- Message Handler Function -------------------

async def delete_arabic_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Delete messages containing Arabic text in groups where deletion is enabled.
    """
    message = update.message
    if not message or not message.text:
        logger.debug("Received a non-text or empty message.")
        return  # Ignore non-text messages

    user = message.from_user
    chat = message.chat
    group_id = chat.id

    logger.debug(f"Checking message in group {group_id} from user {user.id}: {message.text}")

    # Check if deletion is enabled for this group
    if not is_deletion_enabled(group_id):
        logger.debug(f"Deletion not enabled for group {group_id}.")
        return

    # Check if the message contains Arabic
    if is_arabic(message.text):
        try:
            await message.delete()
            logger.info(f"Deleted Arabic message from user {user.id} in group {group_id}.")
            # Optionally, send a warning to the user
            warning_message = escape_markdown(
                "⚠️ Arabic messages are not allowed in this group.",
                version=2
            )
            await message.reply_text(
                warning_message,
                parse_mode='MarkdownV2'
            )
            logger.debug(f"Sent warning to user {user.id} for Arabic message in group {group_id}.")
        except Exception as e:
            logger.error(f"Error deleting message in group {group_id}: {e}")

# ------------------- Utility Function -------------------

def is_arabic(text):
    """
    Check if the text contains any Arabic characters.
    """
    import re
    return bool(re.search(r'[\u0600-\u06FF]', text))

# ------------------- Initialization Function -------------------

def init_delete_module(application):
    """
    Initialize the delete module by adding command and message handlers.
    """
    # Register command handlers
    application.add_handler(CommandHandler("be_sad", be_sad_cmd))
    application.add_handler(CommandHandler("be_happy", be_happy_cmd))

    # Register message handler
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & (filters.ChatType.GROUP | filters.ChatType.SUPERGROUP),
        delete_arabic_messages
    ))

    logger.info("Delete module handlers registered successfully.")

# warning_handler.py

import re
import sqlite3
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import Forbidden
from telegram.helpers import escape_markdown

DATABASE = 'warnings.db'
logger = logging.getLogger(__name__)

REGULATIONS_MESSAGE = """
*Communication Channels Regulation*

• The official language of the group is *ENGLISH ONLY*
• Avoid side discussions.
• Send general requests to the group and tag the official.
• Messages should be within official hours (8:00 AM to 5:00 PM), and only important questions after that time.

Please note that not complying with the above-mentioned regulation will result in:
1- Primary warning sent to the student.
2- Second warning sent to the student.
3- Third warning sent to the student. May be addressed to DISCIPLINARY COMMITTEE.
"""

def is_arabic(text):
    return bool(re.search(r'[\u0600-\u06FF]', text))

def get_user_warnings(user_id):
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('SELECT warnings FROM warnings WHERE user_id = ?', (user_id,))
        row = c.fetchone()
        conn.close()
        warnings = row[0] if row else 0
        logger.debug(f"User {user_id} has {warnings} warnings.")
        return warnings
    except Exception as e:
        logger.error(f"Error retrieving warnings for user {user_id}: {e}")
        return 0

def update_warnings(user_id, warnings):
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('''
            INSERT INTO warnings (user_id, warnings)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET warnings=excluded.warnings
        ''', (user_id, warnings))
        conn.commit()
        conn.close()
        logger.debug(f"Updated warnings for user {user_id} to {warnings}")
    except Exception as e:
        logger.error(f"Error updating warnings for user {user_id}: {e}")
        raise

def log_warning(user_id, warning_number, group_id):
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        c.execute('''
            INSERT INTO warnings_history (user_id, warning_number, timestamp, group_id)
            VALUES (?, ?, ?, ?)
        ''', (user_id, warning_number, timestamp, group_id))
        conn.commit()
        conn.close()
        logger.debug(f"Logged warning {warning_number} for user {user_id} in group {group_id} at {timestamp}")
    except Exception as e:
        logger.error(f"Error logging warning for user {user_id} in group {group_id}: {e}")
        raise

def update_user_info(user):
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('''
            INSERT INTO users (user_id, first_name, last_name, username)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                username=excluded.username
        ''', (user.id, user.first_name, user.last_name, user.username))
        conn.commit()
        conn.close()
        logger.debug(f"Updated user info for user {user.id}")
    except Exception as e:
        logger.error(f"Error updating user info for user {user.id}: {e}")
        raise

def group_exists(group_id):
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('SELECT 1 FROM groups WHERE group_id = ?', (group_id,))
        exists = c.fetchone() is not None
        conn.close()
        logger.debug(f"Checked existence of group {group_id}: {exists}")
        return exists
    except Exception as e:
        logger.error(f"Error checking group existence for {group_id}: {e}")
        return False

def get_group_taras(g_id):
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('SELECT tara_user_id FROM tara_links WHERE group_id = ?', (g_id,))
        rows = c.fetchall()
        conn.close()
        taras = [r[0] for r in rows]
        logger.debug(f"Group {g_id} has TARAs: {taras}")
        return taras
    except Exception as e:
        logger.error(f"Error retrieving TARAs for group {g_id}: {e}")
        return []

def is_bypass_user(user_id):
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('SELECT 1 FROM bypass_users WHERE user_id = ?', (user_id,))
        res = c.fetchone() is not None
        conn.close()
        logger.debug(f"Checked if user {user_id} is bypassed: {res}")
        return res
    except Exception as e:
        logger.error(f"Error checking bypass status for user {user_id}: {e}")
        return False

async def handle_warnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        logger.debug("Received a non-text or empty message.")
        return

    user = message.from_user
    chat = message.chat
    g_id = chat.id

    logger.debug(f"Processing message from user {user.id} in group {g_id}: {message.text}")

    # Ensure this is a registered group
    if not group_exists(g_id):
        logger.warning(f"Group {g_id} is not registered.")
        try:
            await message.reply_text(
                "⚠️ This group is not registered. Please contact the administrator."
            )
        except Exception as e:
            logger.error(f"Error sending unregistered group message: {e}")
        return

    # Check if user is in bypass list
    if is_bypass_user(user.id):
        logger.debug(f"User {user.id} is bypassed from warnings.")
        return  # Do not process warnings for bypassed users

    # Update user info in the database
    try:
        update_user_info(user)
    except Exception as e:
        logger.error(f"Failed to update user info for user {user.id}: {e}")

    # Check if the message contains Arabic
    if is_arabic(message.text):
        try:
            warnings_count = get_user_warnings(user.id) + 1
            update_warnings(user.id, warnings_count)
            log_warning(user.id, warnings_count, g_id)
            logger.info(f"User {user.id} now has {warnings_count} warnings.")
        except Exception as e:
            logger.error(f"Failed to update warnings for user {user.id}: {e}")
            return

        if warnings_count == 1:
            reason_line = "1- Primary warning sent to the student."
        elif warnings_count == 2:
            reason_line = "2- Second warning sent to the student."
        else:
            reason_line = "3- Third warning sent to the student. May be addressed to DISCIPLINARY COMMITTEE."

        # Attempt to send a private message to the user
        alarm_message = f"{REGULATIONS_MESSAGE}\n\n{reason_line}"
        try:
            await context.bot.send_message(
                chat_id=user.id,
                text=alarm_message,
                parse_mode='Markdown'
            )
            logger.info(f"Sent alarm message to user {user.id}.")
            user_notification = "✅ Alarm sent to user."
        except Forbidden:
            logger.error(f"Cannot send PM to user {user.id}. They might not have started the bot.")
            user_notification = (
                f"⚠️ User `{user.id}` hasn't started the bot.\n"
                f"**Full Name:** {user.first_name or 'N/A'} {user.last_name or ''}\n"
                f"**Username:** @{user.username if user.username else 'N/A'}"
            )
        except Exception as e:
            logger.error(f"Error sending PM to user {user.id}: {e}")
            user_notification = f"⚠️ Error sending alarm to user `{user.id}`: {e}"

        # Notify TARAs linked to this group
        group_taras = get_group_taras(g_id)
        if not group_taras:
            logger.debug(f"No TARAs linked to group {g_id}.")

        # Fetch group name
        try:
            conn = sqlite3.connect(DATABASE)
            c = conn.cursor()
            c.execute('SELECT group_name FROM groups WHERE group_id = ?', (g_id,))
            group_row = c.fetchone()
            conn.close()
            group_name = group_row[0] if group_row and group_row[0] else "No Name Set"
        except Exception as e:
            group_name = "No Name Set"
            logger.error(f"Error retrieving group name for {g_id}: {e}")

        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "N/A"
        username_display = f"@{user.username}" if user.username else "NoUsername"

        alarm_report = (
            f"**Alarm Report**\n"
            f"**Group:** {escape_markdown(group_name, version=2)}\n"
            f"**Group ID:** `{g_id}`\n"
            f"**Student ID:** `{user.id}`\n"
            f"**Full Name:** {escape_markdown(full_name, version=2)}\n"
            f"**Username:** {escape_markdown(username_display, version=2)}\n"
            f"**Number of Warnings:** `{warnings_count}`\n"
            f"**Reason:** {reason_line}\n"
            f"**Date:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            f"{user_notification}\n"
        )

        for t_id in group_taras:
            try:
                await context.bot.send_message(
                    chat_id=t_id,
                    text=alarm_report,
                    parse_mode='Markdown'
                )
                # Forward the original Arabic message to the TARA
                await context.bot.forward_message(
                    chat_id=t_id,
                    from_chat_id=chat.id,
                    message_id=message.message_id
                )
                logger.info(f"Sent alarm report and forwarded message to TARA {t_id}.")
            except Forbidden:
                logger.error(f"Cannot send message to TARA {t_id}. They might have blocked the bot.")
            except Exception as e:
                logger.error(f"Error sending message to TARA {t_id}: {e}")
    else:
        logger.debug("No Arabic characters detected in the message.")

async def check_arabic(text):
    try:
        result = is_arabic(text)
        logger.debug(f"Arabic detection for '{text}': {result}")
        return result
    except Exception as e:
        logger.error(f"Error checking Arabic in text '{text}': {e}")
        return False

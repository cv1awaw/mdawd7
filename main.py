#!/usr/bin/env python3

import os
import sys
import sqlite3
import logging
import fcntl
from datetime import datetime, timedelta
import re
import asyncio
import tempfile
import signal

# -------------------------------------------------------------------------------------
# OPTIONAL IMPORTS (PDF and OCR)
# -------------------------------------------------------------------------------------
pdf_available = True
try:
    import PyPDF2
except ImportError:
    pdf_available = False

pytesseract_available = True
pillow_available = True
try:
    import pytesseract
    from PIL import Image
except ImportError:
    pytesseract_available = False
    pillow_available = False

from telegram import (
    Update,
    ChatPermissions,
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)
from telegram.helpers import escape_markdown

# ------------------- Configuration -------------------

DATABASE = 'warnings.db'
ALLOWED_USER_ID = 6177929931  # Replace with your own Telegram user ID
LOCK_FILE = '/tmp/telegram_bot.lock'
MESSAGE_DELETE_TIMEFRAME = 15  # Seconds for temporary message deletion after removal

# ------------------- Logging Setup -------------------

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Allowed user statuses
ALLOWED_STATUSES = ("member", "administrator", "creator")

# In-memory dict for group name requests
pending_group_names = {}

# ------------------- File Lock Mechanism -------------------

def acquire_lock():
    """
    Acquire an exclusive file lock so only one bot instance can run.
    """
    try:
        lock_file = open(LOCK_FILE, 'w')
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        logger.info("Lock acquired. Only one instance running.")
        return lock_file
    except IOError:
        logger.error("Another instance of this bot is already running. Exiting.")
        sys.exit("Another instance is already running.")

def release_lock(lock_file):
    """
    Release the file lock upon exit.
    """
    try:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()
        os.remove(LOCK_FILE)
        logger.info("Lock released. Bot stopped.")
    except Exception as e:
        logger.error(f"Error releasing lock: {e}")

lock_file = acquire_lock()
import atexit
atexit.register(release_lock, lock_file)

# Handle graceful shutdowns
def signal_handler(sig, frame):
    logger.info("Shutdown signal received. Exiting gracefully...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ------------------- DB Initialization -------------------

def init_permissions_db():
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS permissions (
                user_id INTEGER PRIMARY KEY,
                role TEXT NOT NULL
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS removed_users (
                group_id INTEGER,
                user_id INTEGER,
                removal_reason TEXT,
                removal_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (group_id, user_id),
                FOREIGN KEY (group_id) REFERENCES groups(group_id)
            )
        ''')
        conn.commit()
        conn.close()
        logger.info("Permissions & Removed Users tables initialized.")
    except Exception as e:
        logger.error(f"Failed to init permissions DB: {e}")
        raise

def init_db():
    try:
        conn = sqlite3.connect(DATABASE)
        conn.execute("PRAGMA foreign_keys = 1")
        c = conn.cursor()

        # groups
        c.execute('''
            CREATE TABLE IF NOT EXISTS groups (
                group_id INTEGER PRIMARY KEY,
                group_name TEXT
            )
        ''')

        # bypass_users
        c.execute('''
            CREATE TABLE IF NOT EXISTS bypass_users (
                user_id INTEGER PRIMARY KEY
            )
        ''')

        # deletion_settings
        c.execute('''
            CREATE TABLE IF NOT EXISTS deletion_settings (
                group_id INTEGER PRIMARY KEY,
                delete_commands BOOLEAN NOT NULL DEFAULT 1,
                mute_users BOOLEAN NOT NULL DEFAULT 1,
                FOREIGN KEY(group_id) REFERENCES groups(group_id)
            )
        ''')

        # users
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT,
                last_name TEXT,
                username TEXT
            )
        ''')

        conn.commit()
        conn.close()
        logger.info("Main DB tables initialized.")
        
        init_permissions_db()
    except Exception as e:
        logger.error(f"Failed to initialize DB: {e}")
        raise

# ------------------- DB Helpers -------------------

def add_group(group_id):
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("""
            INSERT OR IGNORE INTO groups (group_id, group_name)
            VALUES (?, ?)
        """, (group_id, None))
        # Initialize deletion_settings with defaults
        c.execute("""
            INSERT OR IGNORE INTO deletion_settings (group_id, delete_commands, mute_users)
            VALUES (?, 1, 1)
        """, (group_id,))
        conn.commit()
        conn.close()
        logger.info(f"Added group {group_id} to DB.")
    except Exception as e:
        logger.error(f"Error adding group {group_id}: {e}")
        raise

def set_group_name(group_id, name):
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('UPDATE groups SET group_name=? WHERE group_id=?', (name, group_id))
        conn.commit()
        conn.close()
        logger.info(f"Group {group_id} name set to '{name}'.")
    except Exception as e:
        logger.error(f"Error setting group name for {group_id}: {e}")
        raise

def group_exists(group_id):
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('SELECT 1 FROM groups WHERE group_id=?', (group_id,))
        row = c.fetchone()
        conn.close()
        return bool(row)
    except Exception as e:
        logger.error(f"Error checking group {group_id}: {e}")
        return False

def is_bypass_user(user_id):
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('SELECT 1 FROM bypass_users WHERE user_id=?', (user_id,))
        row = c.fetchone()
        conn.close()
        return bool(row)
    except Exception as e:
        logger.error(f"Error checking bypass for user {user_id}: {e}")
        return False

def add_bypass_user(user_id):
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('INSERT OR IGNORE INTO bypass_users (user_id) VALUES (?)', (user_id,))
        conn.commit()
        conn.close()
        logger.info(f"User {user_id} added to bypass list.")
    except Exception as e:
        logger.error(f"Error adding user {user_id} to bypass list: {e}")
        raise

def remove_bypass_user(user_id):
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('DELETE FROM bypass_users WHERE user_id=?', (user_id,))
        changes = c.rowcount
        conn.commit()
        conn.close()
        if changes > 0:
            logger.info(f"Removed user {user_id} from bypass list.")
            return True
        else:
            logger.warning(f"User {user_id} not found in bypass list.")
            return False
    except Exception as e:
        logger.error(f"Error removing user {user_id} from bypass list: {e}")
        return False

def enable_delete_commands(group_id):
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("""
            UPDATE deletion_settings
            SET delete_commands=1
            WHERE group_id=?
        """, (group_id,))
        conn.commit()
        conn.close()
        logger.info(f"Enabled delete_commands for group {group_id}.")
    except Exception as e:
        logger.error(f"Error enabling delete_commands for group {group_id}: {e}")
        raise

def disable_delete_commands(group_id):
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("""
            UPDATE deletion_settings
            SET delete_commands=0
            WHERE group_id=?
        """, (group_id,))
        conn.commit()
        conn.close()
        logger.info(f"Disabled delete_commands for group {group_id}.")
    except Exception as e:
        logger.error(f"Error disabling delete_commands for group {group_id}: {e}")
        raise

def enable_mute_users(group_id):
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("""
            UPDATE deletion_settings
            SET mute_users=1
            WHERE group_id=?
        """, (group_id,))
        conn.commit()
        conn.close()
        logger.info(f"Enabled mute_users for group {group_id}.")
    except Exception as e:
        logger.error(f"Error enabling mute_users for group {group_id}: {e}")
        raise

def disable_mute_users(group_id):
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("""
            UPDATE deletion_settings
            SET mute_users=0
            WHERE group_id=?
        """, (group_id,))
        conn.commit()
        conn.close()
        logger.info(f"Disabled mute_users for group {group_id}.")
    except Exception as e:
        logger.error(f"Error disabling mute_users for group {group_id}: {e}")
        raise

def is_delete_commands_enabled(group_id):
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('SELECT delete_commands FROM deletion_settings WHERE group_id=?', (group_id,))
        row = c.fetchone()
        conn.close()
        return bool(row and row[0])
    except Exception as e:
        logger.error(f"Error checking delete_commands for group {group_id}: {e}")
        return False

def is_mute_users_enabled(group_id):
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('SELECT mute_users FROM deletion_settings WHERE group_id=?', (group_id,))
        row = c.fetchone()
        conn.close()
        return bool(row and row[0])
    except Exception as e:
        logger.error(f"Error checking mute_users for group {group_id}: {e}")
        return False

def revoke_user_permissions(user_id):
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('UPDATE permissions SET role=? WHERE user_id=?', ('removed', user_id))
        conn.commit()
        conn.close()
        logger.info(f"Revoked permissions for user {user_id} (role='removed').")
    except Exception as e:
        logger.error(f"Error revoking permissions for user {user_id}: {e}")
        raise

def remove_user_from_removed_users(group_id, user_id):
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('DELETE FROM removed_users WHERE group_id=? AND user_id=?', (group_id, user_id))
        changes = c.rowcount
        conn.commit()
        conn.close()
        if changes > 0:
            logger.info(f"Removed user {user_id} from removed_users for group {group_id}.")
            return True
        else:
            logger.warning(f"User {user_id} not in removed_users for group {group_id}.")
            return False
    except Exception as e:
        logger.error(f"Error removing user {user_id} from removed_users: {e}")
        return False

def list_removed_users(group_id=None):
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        if group_id is None:
            c.execute("""
                SELECT group_id, user_id, removal_reason, removal_time
                FROM removed_users
            """)
            rows = c.fetchall()
        else:
            c.execute("""
                SELECT user_id, removal_reason, removal_time
                FROM removed_users
                WHERE group_id=?
            """, (group_id,))
            rows = c.fetchall()
        conn.close()
        logger.info("Fetched removed_users entries.")
        return rows
    except Exception as e:
        logger.error(f"Error fetching removed_users: {e}")
        return []

delete_all_messages_after_removal = {}

# ------------------- Command Handlers -------------------

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ALLOWED_USER_ID:
        return
    await context.bot.send_message(
        chat_id=user.id,
        text=escape_markdown("✅ Bot is running.", version=2),
        parse_mode='MarkdownV2'
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ALLOWED_USER_ID:
        return

    help_text = (
        "*Available Commands:*\n\n"
        "• `/start` – Check if the bot is running.\n"
        "• `/help` – Show help text.\n"
        "• `/group_add <group_id>` – Register a group.\n"
        "• `/rmove_group <group_id>` – Unregister a group.\n"
        "• `/bypass <user_id>` – Add a user to bypass list.\n"
        "• `/unbypass <user_id>` – Remove a user from bypass list.\n"
        "• `/love <group_id> <user_id>` – Remove a user from 'Removed Users'.\n"
        "• `/rmove_user <group_id> <user_id>` – Force remove user from group.\n"
        "• `/mute <group_id> <user_id> <minutes>` – Mute user.\n"
        "• `/unmute <group_id> <user_id>` – Remove mute from user.\n"
        "• `/limit <group_id> <user_id> <permission_type> <on/off>` – Toggle user permission.\n"
        "• `/slow <group_id> <seconds>` – Placeholder for slow mode.\n"
        "• `/be_sad <group_id>` – Enable Arabic deletion.\n"
        "• `/be_happy <group_id>` – Disable Arabic deletion.\n"
        "• `/check <group_id>` – Validate 'Removed Users' vs actual membership.\n"
        "• `/link <group_id>` – Create one-time invite link.\n"
        "• `/permission_type` – Show valid `<permission_type>` for `/limit`.\n"
        "• `/enable_delete <group_id>` – Enable deletion of unauthorized commands.\n"
        "• `/disable_delete <group_id>` – Disable deletion of unauthorized commands.\n"
        "• `/enable_mute <group_id>` – Enable muting of users who send unauthorized commands.\n"
        "• `/disable_mute <group_id>` – Disable muting of users who send unauthorized commands.\n"
        "\n"
        "*Note:* The bot must be *admin* with 'can_restrict_members' to effectively mute/limit.\n"
    )
    await context.bot.send_message(
        chat_id=user.id,
        text=escape_markdown(help_text, version=2),
        parse_mode='MarkdownV2'
    )

async def group_add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ALLOWED_USER_ID:
        return

    if len(context.args) != 1:
        msg = "⚠️ Usage: `/group_add <group_id>`"
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(msg, version=2), parse_mode='MarkdownV2')
        return

    try:
        g_id = int(context.args[0])
    except ValueError:
        w = "⚠️ group_id must be integer."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(w, version=2), parse_mode='MarkdownV2')
        return

    if group_exists(g_id):
        wr = "⚠️ That group is already registered."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(wr, version=2), parse_mode='MarkdownV2')
        return

    add_group(g_id)
    pending_group_names[user.id] = g_id
    confirm = f"✅ Group `{g_id}` added.\nNow send the group name in a message."
    await context.bot.send_message(chat_id=user.id, text=escape_markdown(confirm, version=2), parse_mode='MarkdownV2')

async def handle_group_name_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ALLOWED_USER_ID:
        return

    if user.id not in pending_group_names:
        return

    text = (update.message.text or "").strip()
    if not text:
        return

    group_id = pending_group_names.pop(user.id)
    try:
        set_group_name(group_id, text)
        msg = f"✅ Group `{group_id}` name set to: *{text}*"
        await context.bot.send_message(
            chat_id=user.id,
            text=escape_markdown(msg, version=2),
            parse_mode='MarkdownV2'
        )
    except Exception as e:
        logger.error(f"Error setting group name for {group_id}: {e}")
        err = "⚠️ Could not set group name. Check logs."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(err, version=2), parse_mode='MarkdownV2')

async def rmove_group_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ALLOWED_USER_ID:
        return

    if len(context.args) != 1:
        msg = "⚠️ Usage: `/rmove_group <group_id>`"
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(msg, version=2), parse_mode='MarkdownV2')
        return

    try:
        g_id = int(context.args[0])
    except:
        w = "⚠️ group_id must be integer."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(w, version=2), parse_mode='MarkdownV2')
        return

    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('DELETE FROM groups WHERE group_id=?', (g_id,))
        c.execute('DELETE FROM deletion_settings WHERE group_id=?', (g_id,))
        changes = c.rowcount
        conn.commit()
        conn.close()

        if changes > 0:
            cf = f"✅ Group `{g_id}` removed."
            await context.bot.send_message(chat_id=user.id, text=escape_markdown(cf, version=2), parse_mode='MarkdownV2')
        else:
            wr = f"⚠️ Group `{g_id}` not found."
            await context.bot.send_message(chat_id=user.id, text=escape_markdown(wr, version=2), parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Error removing group {g_id}: {e}")
        msg = "⚠️ Could not remove group. Check logs."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(msg, version=2), parse_mode='MarkdownV2')

async def bypass_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ALLOWED_USER_ID:
        return

    if len(context.args) != 1:
        msg = "⚠️ Usage: `/bypass <user_id>`"
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(msg, version=2), parse_mode='MarkdownV2')
        return

    try:
        uid = int(context.args[0])
    except:
        wr = "⚠️ user_id must be integer."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(wr, version=2), parse_mode='MarkdownV2')
        return

    if is_bypass_user(uid):
        wr = f"⚠️ User `{uid}` is already bypassed."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(wr, version=2), parse_mode='MarkdownV2')
        return

    try:
        add_bypass_user(uid)
        cf = f"✅ User `{uid}` added to bypass list."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(cf, version=2), parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Error bypassing {uid}: {e}")
        err = "⚠️ Could not bypass user. Check logs."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(err, version=2), parse_mode='MarkdownV2')

async def unbypass_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ALLOWED_USER_ID:
        return

    if len(context.args) != 1:
        msg = "⚠️ Usage: `/unbypass <user_id>`"
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(msg, version=2), parse_mode='MarkdownV2')
        return

    try:
        uid = int(context.args[0])
    except:
        wr = "⚠️ user_id must be integer."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(wr, version=2), parse_mode='MarkdownV2')
        return

    removed = remove_bypass_user(uid)
    if removed:
        cf = f"✅ User `{uid}` removed from bypass list."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(cf, version=2), parse_mode='MarkdownV2')
    else:
        wr = f"⚠️ User `{uid}` not found in bypass list."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(wr, version=2), parse_mode='MarkdownV2')

async def love_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /love <group_id> <user_id>
    """
    user = update.effective_user
    if user.id != ALLOWED_USER_ID:
        return

    if len(context.args) != 2:
        msg = "⚠️ Usage: `/love <group_id> <user_id>`"
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(msg, version=2), parse_mode='MarkdownV2')
        return

    try:
        g_id = int(context.args[0])
        u_id = int(context.args[1])
    except:
        e = "⚠️ Both group_id and user_id must be integers."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(e, version=2), parse_mode='MarkdownV2')
        return

    if not group_exists(g_id):
        wr = f"⚠️ Group `{g_id}` is not registered."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(wr, version=2), parse_mode='MarkdownV2')
        return

    removed = remove_user_from_removed_users(g_id, u_id)
    if not removed:
        wr = f"⚠️ User `{u_id}` is not in 'Removed Users' for group `{g_id}`."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(wr, version=2), parse_mode='MarkdownV2')
        return

    try:
        revoke_user_permissions(u_id)
    except Exception as e:
        logger.error(f"Error revoking permissions for {u_id}: {e}")

    cf = f"✅ Loved user `{u_id}` (removed from 'Removed Users') in group `{g_id}`."
    await context.bot.send_message(chat_id=user.id, text=escape_markdown(cf, version=2), parse_mode='MarkdownV2')

async def rmove_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /rmove_user <group_id> <user_id>
    """
    user = update.effective_user
    if user.id != ALLOWED_USER_ID:
        return

    if len(context.args) != 2:
        msg = "⚠️ Usage: `/rmove_user <group_id> <user_id>`"
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(msg, version=2), parse_mode='MarkdownV2')
        return

    try:
        g_id = int(context.args[0])
        u_id = int(context.args[1])
    except:
        e = "⚠️ Both group_id and user_id must be integers."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(e, version=2), parse_mode='MarkdownV2')
        return

    remove_bypass_user(u_id)
    remove_user_from_removed_users(g_id, u_id)
    try:
        revoke_user_permissions(u_id)
    except Exception as e:
        logger.error(f"Revoke permissions failed for {u_id}: {e}")

    try:
        await context.bot.ban_chat_member(chat_id=g_id, user_id=u_id)
    except Exception as e:
        err = f"⚠️ Could not ban `{u_id}` from group `{g_id}` (check bot permissions)."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(err, version=2), parse_mode='MarkdownV2')
        logger.error(f"Ban error for user {u_id} in group {g_id}: {e}")
        return

    delete_all_messages_after_removal[g_id] = datetime.utcnow() + timedelta(seconds=MESSAGE_DELETE_TIMEFRAME)
    asyncio.create_task(remove_deletion_flag_after_timeout(g_id))

    cf = f"✅ Removed `{u_id}` from group `{g_id}`.\nMessages for next {MESSAGE_DELETE_TIMEFRAME} seconds will be deleted."
    await context.bot.send_message(chat_id=user.id, text=escape_markdown(cf, version=2), parse_mode='MarkdownV2')

# MUTE:
async def mute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /mute <group_id> <user_id> <minutes>
    """
    user = update.effective_user
    if user.id != ALLOWED_USER_ID:
        return

    if len(context.args) != 3:
        msg = "⚠️ Usage: `/mute <group_id> <user_id> <minutes>`"
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(msg, version=2), parse_mode='MarkdownV2')
        return

    try:
        g_id = int(context.args[0])
        u_id = int(context.args[1])
        minutes = int(context.args[2])
    except:
        w = "⚠️ group_id, user_id, & minutes must be integers."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(w, version=2), parse_mode='MarkdownV2')
        return

    if not group_exists(g_id):
        ef = f"⚠️ Group `{g_id}` not registered."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(ef, version=2), parse_mode='MarkdownV2')
        return

    until_date = datetime.utcnow() + timedelta(minutes=minutes)
    perms = ChatPermissions(can_send_messages=False)

    try:
        # Attempt to restrict
        await context.bot.restrict_chat_member(chat_id=g_id, user_id=u_id, permissions=perms, until_date=until_date)
        cf = f"✅ Muted user `{u_id}` in group `{g_id}` for {minutes} minute(s)."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(cf, version=2), parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Error muting user {u_id} in group {g_id}: {e}")
        err = "⚠️ Could not mute. Bot must be admin with can_restrict_members."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(err, version=2), parse_mode='MarkdownV2')

# UNMUTE:
async def unmute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /unmute <group_id> <user_id> – remove the user's mute (allow sending messages again)
    """
    user = update.effective_user
    if user.id != ALLOWED_USER_ID:
        return

    if len(context.args) != 2:
        msg = "⚠️ Usage: `/unmute <group_id> <user_id>`"
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(msg, version=2), parse_mode='MarkdownV2')
        return

    try:
        g_id = int(context.args[0])
        u_id = int(context.args[1])
    except ValueError:
        w = "⚠️ group_id, user_id must be integers."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(w, version=2), parse_mode='MarkdownV2')
        return

    if not group_exists(g_id):
        ef = f"⚠️ Group `{g_id}` is not registered."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(ef, version=2), parse_mode='MarkdownV2')
        return

    # Restore normal permissions
    perms = ChatPermissions(
        can_send_messages=True,
        can_send_media_messages=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True
    )

    try:
        await context.bot.restrict_chat_member(chat_id=g_id, user_id=u_id, permissions=perms)
        cf = f"✅ Unmuted user `{u_id}` in group `{g_id}`."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(cf, version=2), parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Error unmuting user {u_id} in group {g_id}: {e}")
        err = "⚠️ Could not unmute. Bot must be admin with can_restrict_members."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(err, version=2), parse_mode='MarkdownV2')

# -------------- Permission Types for /limit --------------
VALID_PERMISSION_TYPES = [
    "text",
    "photos",
    "videos",
    "files",
    "music",
    "gifs",
    "voice",
    "video_messages",
    "inlinebots",
    "embed_links",
    "polls",
    "stickers",
    "games"
]

async def limit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /limit <group_id> <user_id> <permission_type> <on/off>
    toggles a specific permission for a user
    """
    user = update.effective_user
    if user.id != ALLOWED_USER_ID:
        return

    # Parse arguments
    if len(context.args) != 4:
        msg = (
            "⚠️ Usage: `/limit <group_id> <user_id> <permission_type> <on/off>`\n"
            "e.g. /limit -10012345 999999 photos off\n\n"
            "*Valid permission_type values:* " + ", ".join(VALID_PERMISSION_TYPES)
        )
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(msg, version=2), parse_mode='MarkdownV2')
        return

    try:
        g_id = int(context.args[0])
        u_id = int(context.args[1])
        p_type = context.args[2].lower().strip()
        toggle = context.args[3].lower().strip()
    except:
        wr = "⚠️ group_id & user_id must be integers, followed by permission_type and on/off."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(wr, version=2), parse_mode='MarkdownV2')
        return

    # Check if group is registered
    if not group_exists(g_id):
        w = f"⚠️ Group `{g_id}` not registered."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(w, version=2), parse_mode='MarkdownV2')
        return

    # Optional: Check if group is supergroup
    try:
        chat_info = await context.bot.get_chat(g_id)
        if chat_info.type != "supergroup":
            note = f"⚠️ This group is type '{chat_info.type}'. Telegram restrictions typically require a supergroup."
            await context.bot.send_message(chat_id=user.id, text=escape_markdown(note, version=2), parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Error getting chat info for group {g_id}: {e}")
        pass

    # Check the user status
    try:
        target_member = await context.bot.get_chat_member(chat_id=g_id, user_id=u_id)
        # If user is admin or creator, we can't restrict them
        if target_member.status in ["administrator", "creator"]:
            wr = (
                f"⚠️ Cannot restrict user `{u_id}` because they're an admin/creator.\n"
                "Telegram does not allow restricting admins."
            )
            await context.bot.send_message(chat_id=user.id, text=escape_markdown(wr, version=2), parse_mode='MarkdownV2')
            return
    except Exception as e:
        logger.error(f"Error getting chat member for {u_id} in group {g_id}: {e}")
        wr = "⚠️ Could not fetch user status. Possibly user left or was never in the group?"
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(wr, version=2), parse_mode='MarkdownV2')
        return

    # Build permissions
    def toggle_off():
        return toggle == "off"

    # Initialize permissions to current settings
    can_send_messages = True
    can_send_media_messages = True
    can_send_polls = True
    can_send_other_messages = True
    can_add_web_page_previews = True

    # Modify permissions based on command
    if p_type in ["photos", "videos", "files", "music", "gifs", "voice", "video_messages", "inlinebots", "embed_links"]:
        if toggle_off():
            can_send_media_messages = False
    elif p_type in ["stickers", "games"]:
        if toggle_off():
            can_send_other_messages = False
    elif p_type == "polls":
        if toggle_off():
            can_send_polls = False
    elif p_type == "text":
        if toggle_off():
            can_send_messages = False
    else:
        wr = (
            "⚠️ Unknown permission_type.\n"
            "Try one of: " + ", ".join(VALID_PERMISSION_TYPES)
        )
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(wr, version=2), parse_mode='MarkdownV2')
        return

    perms = ChatPermissions(
        can_send_messages=can_send_messages,
        can_send_media_messages=can_send_media_messages,
        can_send_polls=can_send_polls,
        can_send_other_messages=can_send_other_messages,
        can_add_web_page_previews=can_add_web_page_previews
    )

    # Attempt to apply
    try:
        await context.bot.restrict_chat_member(chat_id=g_id, user_id=u_id, permissions=perms)
        msg = (
            f"✅ Set permission '{p_type}' to '{toggle}' for `{u_id}` in group `{g_id}`.\n\n"
            "If the user can still send the restricted content, ensure:\n"
            "1) The user is not an admin.\n"
            "2) The group is a supergroup.\n"
            "3) The bot is admin with can_restrict_members.\n"
        )
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(msg, version=2), parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Error limiting permissions for {u_id} in group {g_id}: {e}")
        err = (
            "⚠️ Could not limit permission. Ensure the bot is admin with can_restrict_members.\n"
            "Check logs for details."
        )
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(err, version=2), parse_mode='MarkdownV2')

async def slow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ALLOWED_USER_ID:
        return

    if len(context.args) != 2:
        msg = "⚠️ Usage: `/slow <group_id> <delay_in_seconds>`"
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(msg, version=2), parse_mode='MarkdownV2')
        return

    try:
        g_id = int(context.args[0])
        delay = int(context.args[1])
    except:
        w = "⚠️ group_id & delay must be integers."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(w, version=2), parse_mode='MarkdownV2')
        return

    if not group_exists(g_id):
        e = f"⚠️ Group `{g_id}` not registered."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(e, version=2), parse_mode='MarkdownV2')
        return

    logger.warning("Setting slow mode is not supported by Bot API. Placeholder only.")
    note = "⚠️ No official method to set slow mode. (Placeholder only.)"
    await context.bot.send_message(chat_id=user.id, text=escape_markdown(note, version=2), parse_mode='MarkdownV2')

async def permission_type_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ALLOWED_USER_ID:
        return

    types_list = "\n".join([f"• `{ptype}`" for ptype in VALID_PERMISSION_TYPES])
    message = (
        "*Possible `permission_type` values for `/limit`:*\n\n"
        f"{types_list}\n\n"
        "Example usage:\n"
        "`/limit <group_id> <user_id> photos off`\n\n"
        "This disallows that user from sending **photos** in the group.\n\n"
        "Remember: The bot must be an admin with can_restrict_members for this to work."
    )

    await context.bot.send_message(
        chat_id=user.id,
        text=escape_markdown(message, version=2),
        parse_mode='MarkdownV2'
    )

# ------------------- Deletion / Filtering Handlers -------------------

def has_arabic(text):
    return bool(re.search(r'[\u0600-\u06FF]', text))

async def delete_arabic_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    user = msg.from_user
    chat_id = msg.chat.id

    # If not enabled for this group, or user is bypassed, do nothing
    if not is_deletion_enabled(chat_id):
        return
    if is_bypass_user(user.id):
        return

    # Check text or caption
    text_or_caption = (msg.text or msg.caption or "")
    if text_or_caption and has_arabic(text_or_caption):
        try:
            await msg.delete()
            logger.info(f"Deleted Arabic text from user {user.id} in group {chat_id}.")
        except Exception as e:
            logger.error(f"Error deleting Arabic message: {e}")
        return

    # If PDF, check its text
    if msg.document and msg.document.file_name and msg.document.file_name.lower().endswith('.pdf'):
        if pdf_available:
            file_id = msg.document.file_id
            try:
                file_ref = await context.bot.get_file(file_id)
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
                    await file_ref.download_to_drive(tmp_pdf.name)
                    tmp_pdf.flush()
                    try:
                        with open(tmp_pdf.name, 'rb') as pdf_file:
                            try:
                                reader = PyPDF2.PdfReader(pdf_file)
                                all_text = ""
                                for page in reader.pages:
                                    all_text += page.extract_text() or ""
                                if has_arabic(all_text):
                                    await msg.delete()
                                    logger.info(f"Deleted PDF with Arabic from user {user.id} in group {chat_id}.")
                            except Exception as e:
                                logger.error(f"PyPDF2 read error: {e}")
                    except Exception as e:
                        logger.error(f"PDF parse error: {e}")
                    finally:
                        try:
                            os.remove(tmp_pdf.name)
                        except:
                            pass
            except Exception as e:
                logger.error(f"Error processing PDF file: {e}")

    # If photo, do OCR check
    if msg.photo:
        if pytesseract_available and pillow_available:
            photo_obj = msg.photo[-1]  # Highest resolution
            file_id = photo_obj.file_id
            try:
                file_ref = await context.bot.get_file(file_id)
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp_img:
                    await file_ref.download_to_drive(tmp_img.name)
                    tmp_img.flush()
                    try:
                        extracted = pytesseract.image_to_string(Image.open(tmp_img.name)) or ""
                        if has_arabic(extracted):
                            await msg.delete()
                            logger.info(f"Deleted image with Arabic from user {user.id} in group {chat_id}.")
                    except Exception as e:
                        logger.error(f"OCR error: {e}")
                    finally:
                        try:
                            os.remove(tmp_img.name)
                        except:
                            pass
            except Exception as e:
                logger.error(f"Error processing image file: {e}")

async def delete_any_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    chat_id = msg.chat.id
    if chat_id in delete_all_messages_after_removal:
        expiry = delete_all_messages_after_removal[chat_id]
        if datetime.utcnow() > expiry:
            delete_all_messages_after_removal.pop(chat_id, None)
            logger.info(f"Short-term deletion expired for group {chat_id}.")
            return
        try:
            await msg.delete()
            logger.info(f"Deleted a message in group {chat_id} (short-term).")
        except Exception as e:
            logger.error(f"Failed to delete flagged message in group {chat_id}: {e}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Error in the bot:", exc_info=context.error)

async def remove_deletion_flag_after_timeout(group_id):
    await asyncio.sleep(MESSAGE_DELETE_TIMEFRAME)
    if group_id in delete_all_messages_after_removal:
        delete_all_messages_after_removal.pop(group_id, None)
        logger.info(f"Deletion flag removed for group {group_id}")

# ------------------- Unauthorized Command Handler -------------------

async def unauthorized_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    user = msg.from_user
    chat_id = msg.chat.id

    # Check if the user is allowed
    if user.id == ALLOWED_USER_ID:
        return  # Do nothing if the user is allowed

    # Log the unauthorized attempt
    logger.info(f"Received unauthorized command from user {user.id} in chat {chat_id}: {msg.text}")

    # Check if delete_commands is enabled
    delete_enabled = is_delete_commands_enabled(chat_id)

    # Check if mute_users is enabled
    mute_enabled = is_mute_users_enabled(chat_id)

    # Delete the message if enabled
    if delete_enabled:
        try:
            await msg.delete()
            logger.info(f"Deleted unauthorized message from user {user.id} in group {chat_id}.")
        except Exception as e:
            logger.error(f"Failed to delete message: {e}")

    # Mute the user if enabled
    if mute_enabled:
        until_date = datetime.utcnow() + timedelta(hours=1)
        perms = ChatPermissions(can_send_messages=False)

        try:
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user.id,
                permissions=perms,
                until_date=until_date
            )
            logger.info(f"Muted user {user.id} in group {chat_id} for one hour due to unauthorized command.")
        except Exception as e:
            logger.error(f"Failed to mute user {user.id} in group {chat_id}: {e}")

# ------------------- /be_sad & /be_happy & /check & /link Commands -------------------

async def be_sad_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ALLOWED_USER_ID:
        return

    if len(context.args) != 1:
        msg = "⚠️ Usage: `/be_sad <group_id>`"
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(msg, version=2), parse_mode='MarkdownV2')
        return

    try:
        g_id = int(context.args[0])
    except:
        w = "⚠️ group_id must be integer."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(w, version=2), parse_mode='MarkdownV2')
        return

    try:
        enable_deletion(g_id)
        cf = f"✅ Arabic deletion enabled for group `{g_id}`."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(cf, version=2), parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Error enabling deletion for group {g_id}: {e}")
        er = "⚠️ Could not enable deletion. Check logs."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(er, version=2), parse_mode='MarkdownV2')

async def be_happy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ALLOWED_USER_ID:
        return

    if len(context.args) != 1:
        msg = "⚠️ Usage: `/be_happy <group_id>`"
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(msg, version=2), parse_mode='MarkdownV2')
        return

    try:
        g_id = int(context.args[0])
    except:
        w = "⚠️ group_id must be integer."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(w, version=2), parse_mode='MarkdownV2')
        return

    try:
        disable_deletion(g_id)
        cf = f"✅ Arabic deletion disabled for group `{g_id}`."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(cf, version=2), parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Error disabling deletion for group {g_id}: {e}")
        err = "⚠️ Could not disable deletion. Check logs."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(err, version=2), parse_mode='MarkdownV2')

async def check_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ALLOWED_USER_ID:
        return

    if len(context.args) != 1:
        msg = "⚠️ Usage: `/check <group_id>`"
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(msg, version=2), parse_mode='MarkdownV2')
        return

    try:
        g_id = int(context.args[0])
    except:
        wr = "⚠️ group_id must be integer."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(wr, version=2), parse_mode='MarkdownV2')
        return

    if not group_exists(g_id):
        ef = f"⚠️ Group `{g_id}` is not registered."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(ef, version=2), parse_mode='MarkdownV2')
        return

    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('SELECT user_id FROM removed_users WHERE group_id=?', (g_id,))
        removed_list = [row[0] for row in c.fetchall()]
        conn.close()
    except Exception as e:
        logger.error(f"Error listing removed users for group {g_id}: {e}")
        e2 = "⚠️ Database error. Check logs."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(e2, version=2), parse_mode='MarkdownV2')
        return

    if not removed_list:
        msg = f"⚠️ No removed users found for group `{g_id}`."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(msg, version=2), parse_mode='MarkdownV2')
        return

    still_in = []
    not_in = []
    for uid in removed_list:
        try:
            member = await context.bot.get_chat_member(chat_id=g_id, user_id=uid)
            if member.status in ALLOWED_STATUSES:
                still_in.append(uid)
            else:
                not_in.append(uid)
        except Exception as e:
            logger.error(f"Error getting chat member for user {uid} in group {g_id}: {e}")
            not_in.append(uid)

    resp = f"*Check Results for Group `{g_id}`:*\n\n"
    if still_in:
        resp += "*These removed users are still in the group:*\n"
        for x in still_in:
            resp += f"• `{x}`\n"
    else:
        resp += "No removed users are still in the group.\n"
    resp += "\n"
    if not_in:
        resp += "*Users not in the group (OK):*\n"
        for x in not_in:
            resp += f"• `{x}`\n"

    await context.bot.send_message(chat_id=user.id, text=escape_markdown(resp, version=2), parse_mode='MarkdownV2')

    for x in still_in:
        try:
            await context.bot.ban_chat_member(chat_id=g_id, user_id=x)
            logger.info(f"Auto-banned user {x} in group {g_id} after /check.")
        except Exception as e:
            logger.error(f"Failed to ban user {x} in group {g_id}: {e}")

async def link_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ALLOWED_USER_ID:
        return

    if len(context.args) != 1:
        msg = "⚠️ Usage: `/link <group_id>`"
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(msg, version=2), parse_mode='MarkdownV2')
        return

    try:
        g_id = int(context.args[0])
    except:
        w = "⚠️ group_id must be integer."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(w, version=2), parse_mode='MarkdownV2')
        return

    if not group_exists(g_id):
        e = f"⚠️ Group `{g_id}` is not registered."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(e, version=2), parse_mode='MarkdownV2')
        return

    try:
        invite_link_obj = await context.bot.create_chat_invite_link(
            chat_id=g_id,
            member_limit=1,
            name="One-Time Link"
        )
        cf = f"✅ One-time invite link for group `{g_id}`:\n\n{invite_link_obj.invite_link}"
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(cf, version=2), parse_mode='MarkdownV2')
        logger.info(f"Created one-time link for group {g_id}: {invite_link_obj.invite_link}")
    except Exception as e:
        logger.error(f"Error creating invite link for group {g_id}: {e}")
        err = "⚠️ Could not create invite link. Check bot permissions & logs."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(err, version=2), parse_mode='MarkdownV2')

# ------------------- main() -------------------

def main():
    try:
        init_db()
    except Exception as e:
        logger.critical(f"DB initialization failure: {e}")
        sys.exit("Cannot start due to DB initialization failure.")

    TOKEN = os.getenv('BOT_TOKEN')
    if not TOKEN:
        logger.error("BOT_TOKEN not set.")
        sys.exit("BOT_TOKEN not set.")
    TOKEN = TOKEN.strip()
    if TOKEN.lower().startswith('bot='):
        TOKEN = TOKEN[4:].strip()

    try:
        app = ApplicationBuilder().token(TOKEN).build()
    except Exception as e:
        logger.critical(f"Failed to build Telegram app: {e}")
        sys.exit("Bot build error.")

    # Register commands
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("group_add", group_add_cmd))
    app.add_handler(CommandHandler("rmove_group", rmove_group_cmd))
    app.add_handler(CommandHandler("bypass", bypass_cmd))
    app.add_handler(CommandHandler("unbypass", unbypass_cmd))
    app.add_handler(CommandHandler("love", love_cmd))
    app.add_handler(CommandHandler("rmove_user", rmove_user_cmd))
    app.add_handler(CommandHandler("mute", mute_cmd))
    app.add_handler(CommandHandler("unmute", unmute_cmd))  # New
    app.add_handler(CommandHandler("limit", limit_cmd))
    app.add_handler(CommandHandler("slow", slow_cmd))
    app.add_handler(CommandHandler("be_sad", be_sad_cmd))
    app.add_handler(CommandHandler("be_happy", be_happy_cmd))
    app.add_handler(CommandHandler("check", check_cmd))
    app.add_handler(CommandHandler("link", link_cmd))
    app.add_handler(CommandHandler("permission_type", permission_type_cmd))
    # New Commands for Deletion and Mute Control
    app.add_handler(CommandHandler("enable_delete", enable_delete_cmd))
    app.add_handler(CommandHandler("disable_delete", disable_delete_cmd))
    app.add_handler(CommandHandler("enable_mute", enable_mute_cmd))
    app.add_handler(CommandHandler("disable_mute", disable_mute_cmd))

    # ------------------- Unauthorized Command Handler -------------------
    # Register unauthorized command handler BEFORE other message handlers
    app.add_handler(MessageHandler(filters.COMMAND & ~filters.User(ALLOWED_USER_ID), unauthorized_command_handler))

    # Message handlers
    app.add_handler(MessageHandler(
        filters.TEXT | filters.CAPTION | filters.Document.ALL | filters.PHOTO,
        delete_arabic_messages
    ))
    app.add_handler(MessageHandler(
        filters.ALL,
        delete_any_messages
    ))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_group_name_reply
    ))

    # Error handler
    app.add_error_handler(error_handler)

    logger.info("Bot starting with separated delete and mute functionalities.")
    app.run_polling()

# ------------------- New Command Handlers for Enable/Disable -------------------

async def enable_delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /enable_delete <group_id> – Enable deletion of unauthorized commands in the specified group.
    """
    user = update.effective_user
    if user.id != ALLOWED_USER_ID:
        return

    if len(context.args) != 1:
        msg = "⚠️ Usage: `/enable_delete <group_id>`"
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(msg, version=2), parse_mode='MarkdownV2')
        return

    try:
        g_id = int(context.args[0])
    except:
        w = "⚠️ group_id must be integer."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(w, version=2), parse_mode='MarkdownV2')
        return

    if not group_exists(g_id):
        wr = f"⚠️ Group `{g_id}` is not registered."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(wr, version=2), parse_mode='MarkdownV2')
        return

    try:
        enable_delete_commands(g_id)
        cf = f"✅ Deletion of unauthorized commands enabled for group `{g_id}`."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(cf, version=2), parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Error enabling delete_commands for group {g_id}: {e}")
        err = "⚠️ Could not enable deletion. Check logs."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(err, version=2), parse_mode='MarkdownV2')

async def disable_delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /disable_delete <group_id> – Disable deletion of unauthorized commands in the specified group.
    """
    user = update.effective_user
    if user.id != ALLOWED_USER_ID:
        return

    if len(context.args) != 1:
        msg = "⚠️ Usage: `/disable_delete <group_id>`"
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(msg, version=2), parse_mode='MarkdownV2')
        return

    try:
        g_id = int(context.args[0])
    except:
        w = "⚠️ group_id must be integer."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(w, version=2), parse_mode='MarkdownV2')
        return

    if not group_exists(g_id):
        wr = f"⚠️ Group `{g_id}` is not registered."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(wr, version=2), parse_mode='MarkdownV2')
        return

    try:
        disable_delete_commands(g_id)
        cf = f"✅ Deletion of unauthorized commands disabled for group `{g_id}`."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(cf, version=2), parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Error disabling delete_commands for group {g_id}: {e}")
        err = "⚠️ Could not disable deletion. Check logs."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(err, version=2), parse_mode='MarkdownV2')

async def enable_mute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /enable_mute <group_id> – Enable muting of users who send unauthorized commands in the specified group.
    """
    user = update.effective_user
    if user.id != ALLOWED_USER_ID:
        return

    if len(context.args) != 1:
        msg = "⚠️ Usage: `/enable_mute <group_id>`"
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(msg, version=2), parse_mode='MarkdownV2')
        return

    try:
        g_id = int(context.args[0])
    except:
        w = "⚠️ group_id must be integer."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(w, version=2), parse_mode='MarkdownV2')
        return

    if not group_exists(g_id):
        wr = f"⚠️ Group `{g_id}` is not registered."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(wr, version=2), parse_mode='MarkdownV2')
        return

    try:
        enable_mute_users(g_id)
        cf = f"✅ Muting of users who send unauthorized commands enabled for group `{g_id}`."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(cf, version=2), parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Error enabling mute_users for group {g_id}: {e}")
        err = "⚠️ Could not enable muting. Check logs."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(err, version=2), parse_mode='MarkdownV2')

async def disable_mute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /disable_mute <group_id> – Disable muting of users who send unauthorized commands in the specified group.
    """
    user = update.effective_user
    if user.id != ALLOWED_USER_ID:
        return

    if len(context.args) != 1:
        msg = "⚠️ Usage: `/disable_mute <group_id>`"
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(msg, version=2), parse_mode='MarkdownV2')
        return

    try:
        g_id = int(context.args[0])
    except:
        w = "⚠️ group_id must be integer."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(w, version=2), parse_mode='MarkdownV2')
        return

    if not group_exists(g_id):
        wr = f"⚠️ Group `{g_id}` is not registered."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(wr, version=2), parse_mode='MarkdownV2')
        return

    try:
        disable_mute_users(g_id)
        cf = f"✅ Muting of users who send unauthorized commands disabled for group `{g_id}`."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(cf, version=2), parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Error disabling mute_users for group {g_id}: {e}")
        err = "⚠️ Could not disable muting. Check logs."
        await context.bot.send_message(chat_id=user.id, text=escape_markdown(err, version=2), parse_mode='MarkdownV2')

# ------------------- main() -------------------

if __name__ == "__main__":
    main()

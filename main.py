# main.py

import logging
import os
import re
import json
import uuid
import asyncio
from pathlib import Path
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    filters,
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
)
from roles import (
    WRITER_IDS,
    MCQS_TEAM_IDS,
    CHECKER_TEAM_IDS,
    WORD_TEAM_IDS,
    DESIGN_TEAM_IDS,
    KING_TEAM_IDS,
    TARA_TEAM_IDS,
    MIND_MAP_FORM_CREATOR_IDS,  # Newly added
)

# ------------------ Setup Logging ------------------

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG  # Set to DEBUG for detailed logs
)
logger = logging.getLogger(__name__)

# ------------------ Define Roles ------------------

# Define roles and their corresponding IDs
ROLE_MAP = {
    'writer': WRITER_IDS,
    'mcqs_team': MCQS_TEAM_IDS,
    'checker_team': CHECKER_TEAM_IDS,
    'word_team': WORD_TEAM_IDS,
    'design_team': DESIGN_TEAM_IDS,
    'king_team': KING_TEAM_IDS,
    'tara_team': TARA_TEAM_IDS,
    'mind_map_form_creator': MIND_MAP_FORM_CREATOR_IDS,  # Newly added
}

# Define display names for each role
ROLE_DISPLAY_NAMES = {
    'writer': 'Writer Team',
    'mcqs_team': 'MCQs Team',
    'checker_team': 'Editor Team',
    'word_team': 'Digital Writers',
    'design_team': 'Design Team',
    'king_team': 'Admin Team',
    'tara_team': 'Tara Team',
    'mind_map_form_creator': 'Mind Map & Form Creation Team',  # Newly added
}

# Define trigger to target roles mapping
TRIGGER_TARGET_MAP = {
    '-w': ['writer'],
    '-e': ['checker_team'],          # Editor Team
    '-mcq': ['mcqs_team'],
    '-d': ['word_team'],
    '-de': ['design_team'],
    '-mf': ['mind_map_form_creator'],
    '-c': ['checker_team'],          # Newly added trigger for Checker Team
}

# Define target roles for each role
# Adjusted to ensure that other roles can only send messages to 'tara_team' and their own role
SENDING_ROLE_TARGETS = {
    'writer': ['writer', 'tara_team'],
    'mcqs_team': ['mcqs_team', 'tara_team'],
    'checker_team': ['checker_team', 'tara_team'],
    'word_team': ['word_team', 'tara_team'],
    'design_team': ['design_team', 'tara_team'],
    'king_team': ['king_team', 'tara_team'],
    'tara_team': list(ROLE_MAP.keys()),  # Tara can send to all roles
    'mind_map_form_creator': ['mind_map_form_creator', 'tara_team'],
}

# ------------------ Define Conversation States ------------------

TEAM_MESSAGE = 1
SPECIFIC_TEAM_MESSAGE = 2
SPECIFIC_USER_MESSAGE = 3
TARA_MESSAGE = 4
CONFIRMATION = 5
SELECT_ROLE = 6

# ------------------ User Data Storage ------------------

# User data storage: username (lowercase) -> user_id
USER_DATA_FILE = Path('user_data.json')

# Load existing user data if the file exists
if USER_DATA_FILE.exists():
    with open(USER_DATA_FILE, 'r') as f:
        try:
            user_data_store = json.load(f)
            # Convert keys to lowercase to maintain consistency
            user_data_store = {k.lower(): v for k, v in user_data_store.items()}
            logger.info("Loaded existing user data from user_data.json.")
        except json.JSONDecodeError:
            user_data_store = {}
            logger.error("user_data.json is not a valid JSON file. Starting with an empty data store.")
else:
    user_data_store = {}

def save_user_data():
    """Save the user_data_store to a JSON file."""
    try:
        with open(USER_DATA_FILE, 'w') as f:
            json.dump(user_data_store, f)
            logger.info("Saved user data to user_data.json.")
    except Exception as e:
        logger.error(f"Failed to save user data: {e}")

def get_user_roles(user_id):
    """Determine all roles of a user based on their user ID."""
    roles = []
    for role, ids in ROLE_MAP.items():
        if user_id in ids:
            roles.append(role)
    return roles

# ------------------ Mute Functionality ------------------

# Mute data storage: list of muted user IDs
MUTED_USERS_FILE = Path('muted_users.json')

# Load existing muted users if the file exists
if MUTED_USERS_FILE.exists():
    with open(MUTED_USERS_FILE, 'r') as f:
        try:
            muted_users = set(json.load(f))
            logger.info("Loaded existing muted users from muted_users.json.")
        except json.JSONDecodeError:
            muted_users = set()
            logger.error("muted_users.json is not a valid JSON file. Starting with an empty muted users set.")
else:
    muted_users = set()

def save_muted_users():
    """Save the muted_users set to a JSON file."""
    try:
        with open(MUTED_USERS_FILE, 'w') as f:
            json.dump(list(muted_users), f)
            logger.info("Saved muted users to muted_users.json.")
    except Exception as e:
        logger.error(f"Failed to save muted users: {e}")

# ------------------ Helper Functions ------------------

def get_display_name(user):
    """Return the display name for a user."""
    if user.username:
        return f"@{user.username}"
    else:
        full_name = f"{user.first_name} {user.last_name}" if user.last_name else user.first_name
        return full_name

def get_role_selection_keyboard(roles):
    """Return an inline keyboard for role selection with a Cancel option."""
    keyboard = []
    for role in roles:
        display_name = ROLE_DISPLAY_NAMES.get(role, role.capitalize())
        callback_data = f"role:{role}"
        keyboard.append([InlineKeyboardButton(display_name, callback_data=callback_data)])
    # Add a Cancel button
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel_role_selection')])
    return InlineKeyboardMarkup(keyboard)

async def forward_messages(bot, messages, target_ids, sender_role):
    """Forward multiple documents or text messages to a list of target user IDs and notify about the sender's role."""
    try:
        # Get the display name for the sender's role
        sender_display_name = ROLE_DISPLAY_NAMES.get(sender_role, sender_role.capitalize())

        # Get the sender's display name using the helper function
        username_display = get_display_name(messages[0].from_user)

        # Construct a common caption
        caption = f"🔄 *These documents/messages were sent by **{username_display} ({sender_display_name})**.*"

        # Prepare media group for documents
        media_group = []
        for msg in messages:
            if msg.document:
                media = {
                    'type': 'document',
                    'media': msg.document.file_id,
                    'caption': caption if msg == messages[0] else None,  # Only the first document has the caption
                    'parse_mode': 'Markdown'
                }
                media_group.append(media)
            elif msg.text:
                # Telegram does not support media groups for text messages. Send them individually.
                for user_id in target_ids:
                    try:
                        await bot.send_message(
                            chat_id=user_id,
                            text=f"{caption}\n\n{msg.text}",
                            parse_mode='Markdown'
                        )
                        logger.info(f"Forwarded text message to {user_id}")
                    except Exception as e:
                        logger.error(f"Failed to forward text message to {user_id}: {e}")
            else:
                # Handle other message types if necessary
                pass

        if media_group:
            for user_id in target_ids:
                try:
                    await bot.send_media_group(
                        chat_id=user_id,
                        media=media_group
                    )
                    logger.info(f"Forwarded media group to {user_id}")
                except Exception as e:
                    logger.error(f"Failed to forward media group to {user_id}: {e}")
    except Exception as e:
        logger.error(f"Error in forward_messages: {e}")

async def send_confirmation(messages, context, sender_role, target_ids, target_roles=None):
    """Send a confirmation message with inline buttons for a group of documents or text."""
    try:
        # Determine the content description
        if any(msg.document for msg in messages):
            document_names = [f"`{msg.document.file_name}`" for msg in messages if msg.document]
            content_description = f"PDF Documents: {', '.join(document_names)}"
        elif all(msg.text for msg in messages):
            content_description = f"{len(messages)} Text Message(s)"
        else:
            content_description = "Unsupported message types."

        if target_roles:
            target_roles_display = [ROLE_DISPLAY_NAMES.get(r, r.capitalize()) for r in target_roles]
        else:
            target_roles_display = [ROLE_DISPLAY_NAMES.get(r, r.capitalize()) for r in SENDING_ROLE_TARGETS.get(sender_role, [])]

        confirmation_text = (
            f"📩 *You are about to send the following to **{', '.join(target_roles_display)}**:*\n\n"
            f"{content_description}\n\n"
            "Do you want to send this?"
        )

        # Generate a unique UUID for this confirmation
        confirmation_uuid = str(uuid.uuid4())

        # Create confirmation keyboard with UUID in callback_data
        keyboard = [
            [
                InlineKeyboardButton("✅ Confirm", callback_data=f'confirm:{confirmation_uuid}'),
                InlineKeyboardButton("❌ Cancel", callback_data=f'cancel:{confirmation_uuid}'),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Send the confirmation message
        confirmation_message = await messages[0].reply_text(confirmation_text, parse_mode='Markdown', reply_markup=reply_markup)

        # Store confirmation data using UUID
        context.bot_data[f'confirm_{confirmation_uuid}'] = {
            'messages': messages,
            'target_ids': target_ids,
            'sender_role': sender_role,
            'target_roles': target_roles if target_roles else SENDING_ROLE_TARGETS.get(sender_role, [])
        }

        logger.debug(f"Sent confirmation with UUID {confirmation_uuid} to user {messages[0].from_user.id}")

    except Exception as e:
        logger.error(f"Error in send_confirmation: {e}")

# ------------------ Handler Functions ------------------

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the conversation."""
    try:
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text("Operation cancelled.")
        else:
            await update.message.reply_text("Operation cancelled.")
        logger.info(f"User {update.effective_user.id} cancelled the operation.")
    except Exception as e:
        logger.error(f"Error in cancel handler: {e}")
    return ConversationHandler.END

async def confirmation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the user's confirmation response."""
    try:
        query = update.callback_query
        await query.answer()
        data = query.data

        logger.debug(f"Received confirmation callback data: {data}")

        if data.startswith('confirm:') or data.startswith('cancel:'):
            try:
                action, confirmation_uuid = data.split(':', 1)
            except ValueError:
                await query.edit_message_text("Invalid confirmation data. Please try again.")
                logger.error("Failed to parse confirmation data.")
                return ConversationHandler.END

            confirm_data = context.bot_data.get(f'confirm_{confirmation_uuid}')

            if not confirm_data:
                await query.edit_message_text("An error occurred. Please try again.")
                logger.error(f"No confirmation data found for UUID {confirmation_uuid}.")
                return ConversationHandler.END

            if action == 'confirm':
                messages_to_send = confirm_data['messages']
                target_ids = confirm_data['target_ids']
                sender_role = confirm_data['sender_role']
                target_roles = confirm_data.get('target_roles', [])

                # Forward the messages
                await forward_messages(context.bot, messages_to_send, target_ids, sender_role)

                # Prepare display names for confirmation
                sender_display_name = ROLE_DISPLAY_NAMES.get(sender_role, sender_role.capitalize())

                if 'specific_user' in target_roles:
                    recipient_display_names = []
                    for tid in target_ids:
                        try:
                            chat = await context.bot.get_chat(tid)
                            recipient_display_names.append(get_display_name(chat))
                        except Exception as e:
                            logger.error(f"Failed to get chat info for user ID {tid}: {e}")
                            recipient_display_names.append(f"User ID {tid}")
                else:
                    recipient_display_names = [ROLE_DISPLAY_NAMES.get(r, r.capitalize()) for r in target_roles if r != 'specific_user']

                if any(msg.document for msg in messages_to_send):
                    confirmation_text = (
                        f"✅ *Your PDF documents have been sent from **{sender_display_name}** "
                        f"to **{', '.join(recipient_display_names)}**.*"
                    )
                elif all(msg.text for msg in messages_to_send):
                    confirmation_text = (
                        f"✅ *Your {len(messages_to_send)} message(s) have been sent from **{sender_display_name}** "
                        f"to **{', '.join(recipient_display_names)}**.*"
                    )
                else:
                    confirmation_text = (
                        f"✅ *Your messages have been sent from **{sender_display_name}** "
                        f"to **{', '.join(recipient_display_names)}**.*"
                    )

                await query.edit_message_text(confirmation_text, parse_mode='Markdown')
                logger.info(f"User {query.from_user.id} confirmed and sent the messages.")

                # Clean up the stored data
                del context.bot_data[f'confirm_{confirmation_uuid}']

            elif action == 'cancel':
                await query.edit_message_text("Operation cancelled.")
                logger.info(f"User {query.from_user.id} cancelled the message sending for UUID {confirmation_uuid}.")

                # Clean up the stored data
                if f'confirm_{confirmation_uuid}' in context.bot_data:
                    del context.bot_data[f'confirm_{confirmation_uuid}']

        else:
            await query.edit_message_text("Invalid choice.")
            logger.warning(f"User {query.from_user.id} sent invalid confirmation choice: {data}")

    except Exception as e:
        logger.error(f"Error in confirmation_handler: {e}")
        await update.message.reply_text("An error occurred. Please try again later.")
    return ConversationHandler.END

async def specific_user_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Trigger function when a Tara team member sends a specific user command."""
    try:
        user_id = update.message.from_user.id
        roles = get_user_roles(user_id)

        if 'tara_team' not in roles:
            await update.message.reply_text("You are not authorized to use this command.")
            logger.warning(f"Unauthorized access attempt by user {user_id} for specific user triggers.")
            return ConversationHandler.END

        # Extract username from the command using regex
        match = re.match(r'^\s*-\@([A-Za-z0-9_]{5,32})\s*$', update.message.text, re.IGNORECASE)
        if not match:
            await update.message.reply_text("Invalid format. Please use `-@username` to target a user.", parse_mode='Markdown')
            logger.warning(f"Invalid user command format from user {user_id}.")
            return ConversationHandler.END

        target_username = match.group(1).lower()
        target_user_id = user_data_store.get(target_username)

        if not target_user_id:
            await update.message.reply_text(f"User `@{target_username}` not found.", parse_mode='Markdown')
            logger.warning(f"Tara Team member {user_id} attempted to target non-existent user @{target_username}.")
            return ConversationHandler.END

        # Store target user ID and other necessary data in bot_data
        context.bot_data['target_user_id'] = target_user_id
        context.bot_data['target_username'] = target_username
        context.bot_data['sender_role'] = 'tara_team'  # Tara Team is sending the message

        await update.message.reply_text(f"Write your message for user `@{target_username}`.", parse_mode='Markdown')
        logger.info(f"User {user_id} is sending a message to user @{target_username} (ID: {target_user_id}).")
        return SPECIFIC_USER_MESSAGE

    except Exception as e:
        logger.error(f"Error in specific_user_trigger: {e}")
        await update.message.reply_text("An error occurred. Please try again later.")
        return ConversationHandler.END

async def specific_user_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the message intended for a specific user and ask for confirmation."""
    try:
        message = update.message
        user_id = message.from_user.id

        target_user_id = context.bot_data.get('target_user_id')
        target_username = context.bot_data.get('target_username')

        if not target_user_id:
            await message.reply_text("An error occurred. Please try again.")
            logger.error(f"No target user ID found in bot_data for user {user_id}.")
            return ConversationHandler.END

        # Ensure only the specific user is targeted
        target_ids = [target_user_id]
        target_roles = ['specific_user']
        sender_role = context.bot_data.get('sender_role', 'tara_team')  # Default to 'tara_team'

        # Store the message for confirmation
        messages_to_send = [message]

        # Send confirmation using UUID
        await send_confirmation(messages_to_send, context, sender_role, target_ids, target_roles=['specific_user'])

        logger.info(f"User {user_id} initiated sending a message to user @{target_username} (ID: {target_user_id}).")

        return CONFIRMATION

    except Exception as e:
        logger.error(f"Error in specific_user_message_handler: {e}")
        await update.message.reply_text("An error occurred. Please try again later.")
        return ConversationHandler.END

async def specific_team_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Trigger function when a Tara team member sends a specific team command."""
    try:
        user_id = update.message.from_user.id
        roles = get_user_roles(user_id)

        if 'tara_team' not in roles:
            await update.message.reply_text("You are not authorized to use this command.")
            logger.warning(f"Unauthorized access attempt by user {user_id} for specific team triggers.")
            return ConversationHandler.END

        message_text = update.message.text.strip()
        message = message_text.lower()
        target_roles = TRIGGER_TARGET_MAP.get(message)

        if not target_roles:
            await update.message.reply_text("Invalid trigger. Please try again.")
            logger.warning(f"Invalid trigger '{message}' from user {user_id}.")
            return ConversationHandler.END

        # Store target roles in bot_data
        context.bot_data['specific_target_roles'] = target_roles
        context.bot_data['sender_role'] = 'tara_team'  # Tara Team is sending the message

        await update.message.reply_text("Write your message for your team.")
        logger.info(f"User {user_id} is sending a message to roles {target_roles}.")
        return SPECIFIC_TEAM_MESSAGE

    except Exception as e:
        logger.error(f"Error in specific_team_trigger: {e}")
        await update.message.reply_text("An error occurred. Please try again later.")
        return ConversationHandler.END

async def specific_team_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the team message after the specific trigger and ask for confirmation."""
    try:
        message = update.message
        user_id = message.from_user.id

        target_roles = context.bot_data.get('specific_target_roles', [])
        target_ids = set()

        for target_role in target_roles:
            target_ids.update(ROLE_MAP.get(target_role, []))

        # Exclude the sender's user ID from all forwards
        target_ids.discard(user_id)

        if not target_ids:
            await message.reply_text("No recipients found to send your message.")
            logger.warning(f"No recipients found for user {user_id}.")
            return ConversationHandler.END

        # Store the message and targets for confirmation
        messages_to_send = [message]
        target_ids = list(target_ids)
        target_roles = target_roles
        sender_role = context.bot_data.get('sender_role', 'tara_team')

        # Send confirmation using UUID
        await send_confirmation(messages_to_send, context, sender_role, target_ids, target_roles=target_roles)

        logger.info(f"User {user_id} initiated sending a message to roles {target_roles}.")

        return CONFIRMATION

    except Exception as e:
        logger.error(f"Error in specific_team_message_handler: {e}")
        await update.message.reply_text("An error occurred. Please try again later.")
        return ConversationHandler.END

async def team_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the general team trigger."""
    try:
        user_id = update.message.from_user.id
        roles = get_user_roles(user_id)

        if not roles:
            await update.message.reply_text("You don't have a role assigned to use this bot.")
            logger.warning(f"Unauthorized access attempt by user {user_id} for general team trigger.")
            return ConversationHandler.END

        # Determine which roles the sender can send messages to
        # If user has multiple roles, they need to choose which role to use
        if len(roles) > 1:
            # Present role selection keyboard
            keyboard = get_role_selection_keyboard(roles)
            await update.message.reply_text(
                "You have multiple roles. Please choose which role you want to use to send this message:",
                reply_markup=keyboard
            )
            # Store pending messages
            context.bot_data['pending_messages'] = []
            logger.info(f"User {user_id} has multiple roles and is prompted to select one.")
            return SELECT_ROLE
        else:
            # Single role, proceed to message writing
            selected_role = roles[0]
            context.bot_data['sender_role'] = selected_role

            await update.message.reply_text("Write your message for your team and Tara Team.")
            logger.info(f"User {user_id} with role '{selected_role}' is sending a message to their team and Tara Team.")
            return TEAM_MESSAGE

    except Exception as e:
        logger.error(f"Error in team_trigger: {e}")
        await update.message.reply_text("An error occurred. Please try again later.")
        return ConversationHandler.END

async def team_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the team message after the general trigger and ask for confirmation."""
    try:
        message = update.message
        user_id = message.from_user.id
        sender_role = context.bot_data.get('sender_role')

        if not sender_role:
            await message.reply_text("An error occurred. Please try again.")
            logger.error(f"No sender role found in bot_data for user {user_id}.")
            return ConversationHandler.END

        target_roles = SENDING_ROLE_TARGETS.get(sender_role, [])
        target_ids = set()

        for role in target_roles:
            target_ids.update(ROLE_MAP.get(role, []))

        # Exclude the sender's user ID from all forwards
        target_ids.discard(user_id)

        if not target_ids:
            await message.reply_text("No recipients found to send your message.")
            logger.warning(f"No recipients found for user {user_id} with role '{sender_role}'.")
            return ConversationHandler.END

        # Store the message and targets for confirmation
        messages_to_send = [message]
        target_ids = list(target_ids)
        target_roles = target_roles
        sender_role = sender_role

        # Handle PDF documents and text messages
        if message.document and message.document.mime_type == 'application/pdf':
            # Send confirmation using UUID
            await send_confirmation(messages_to_send, context, sender_role, target_ids, target_roles=target_roles)
            logger.info(f"User {user_id} is sending PDF documents.")
        elif message.text:
            # Send confirmation using UUID
            await send_confirmation(messages_to_send, context, sender_role, target_ids, target_roles=target_roles)
            logger.info(f"User {user_id} is sending text messages.")
        else:
            await message.reply_text("Please send PDF documents or text messages only.")
            logger.warning(f"User {user_id} sent an unsupported message type.")
            return ConversationHandler.END

        return CONFIRMATION

    except Exception as e:
        logger.error(f"Error in team_message_handler: {e}")
        await update.message.reply_text("An error occurred. Please try again later.")
        return ConversationHandler.END

async def select_role_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the role selection from the user."""
    try:
        query = update.callback_query
        await query.answer()
        data = query.data

        logger.debug(f"Received role selection callback data: {data}")

        if data.startswith('role:'):
            selected_role = data.split(':', 1)[1]
            context.bot_data['sender_role'] = selected_role

            # Retrieve the pending messages
            pending_messages = context.bot_data.get('pending_messages', [])

            if not pending_messages:
                await query.edit_message_text("No pending messages found. Please try again.")
                logger.error(f"No pending messages found for user {query.from_user.id}.")
                return ConversationHandler.END

            # Remove the pending messages from bot_data
            del context.bot_data['pending_messages']

            # Determine target_ids and target_roles based on selected_role
            target_roles = SENDING_ROLE_TARGETS.get(selected_role, [])
            target_ids = set()
            for role in target_roles:
                target_ids.update(ROLE_MAP.get(role, []))
            target_ids.discard(query.from_user.id)

            if not target_ids:
                await query.edit_message_text("No recipients found to send your message.")
                logger.warning(f"No recipients found for user {query.from_user.id} with role '{selected_role}'.")
                return ConversationHandler.END

            # Send confirmation using UUID
            await send_confirmation(pending_messages, context, selected_role, list(target_ids), target_roles=target_roles)

            await query.edit_message_text("Processing your message...")
            logger.info(f"User {query.from_user.id} selected role '{selected_role}' and is prompted for confirmation.")
            return CONFIRMATION

        elif data == 'cancel_role_selection':
            await query.edit_message_text("Operation cancelled.")
            logger.info(f"User {query.from_user.id} cancelled role selection.")
            return ConversationHandler.END
        else:
            await query.edit_message_text("Invalid role selection.")
            logger.warning(f"User {query.from_user.id} sent invalid role selection: {data}")
            return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error in select_role_handler: {e}")
        await query.edit_message_text("An error occurred. Please try again later.")
        return ConversationHandler.END

async def tara_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the -t trigger to send a message to Tara team."""
    try:
        user_id = update.message.from_user.id
        roles = get_user_roles(user_id)

        if not roles:
            await update.message.reply_text("You don't have a role assigned to use this bot.")
            logger.warning(f"User {user_id} attempted to use -t without a role.")
            return ConversationHandler.END

        # Store the user's role
        context.bot_data['sender_role'] = roles[0]  # Use the first role

        await update.message.reply_text("Write your message for the Tara Team.")
        logger.info(f"User {user_id} with role '{roles[0]}' is sending a message to Tara Team.")
        return TARA_MESSAGE

    except Exception as e:
        logger.error(f"Error in tara_trigger: {e}")
        await update.message.reply_text("An error occurred. Please try again later.")
        return ConversationHandler.END

async def tara_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the message intended for Tara team and ask for confirmation."""
    try:
        message = update.message
        user_id = message.from_user.id
        sender_role = context.bot_data.get('sender_role')

        if not sender_role:
            await message.reply_text("You don't have a role assigned to use this bot.")
            logger.warning(f"Unauthorized access attempt by user {user_id}")
            return ConversationHandler.END

        target_roles = ['tara_team']
        target_ids = set(ROLE_MAP.get('tara_team', []))

        # Exclude the sender's user ID from all forwards (if user is in Tara team)
        target_ids.discard(user_id)

        if not target_ids:
            await message.reply_text("No recipients found to send your message.")
            logger.warning(f"No recipients found for user {user_id} with role '{sender_role}'.")
            return ConversationHandler.END

        # Store the message and targets for confirmation
        messages_to_send = [message]
        target_ids = list(target_ids)
        target_roles = target_roles
        sender_role = sender_role

        # Send confirmation using UUID
        await send_confirmation(messages_to_send, context, sender_role, target_ids, target_roles=target_roles)

        logger.info(f"User {user_id} is sending a message to Tara Team.")

        return CONFIRMATION

    except Exception as e:
        logger.error(f"Error in tara_message_handler: {e}")
        await update.message.reply_text("An error occurred. Please try again later.")
        return ConversationHandler.END

async def handle_general_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages and forward them based on user roles."""
    try:
        message = update.message
        if not message:
            return ConversationHandler.END  # Ignore non-message updates

        user_id = message.from_user.id
        username = message.from_user.username

        # Check if the user is muted
        if user_id in muted_users:
            await message.reply_text("You have been muted and cannot send messages through this bot.")
            logger.info(f"Muted user {user_id} attempted to send a message.")
            return ConversationHandler.END

        # Store the username and user_id if username exists
        if username:
            username_lower = username.lower()
            previous_id = user_data_store.get(username_lower)
            if previous_id != user_id:
                # Update if the user_id has changed
                user_data_store[username_lower] = user_id
                logger.info(f"Stored/Updated username '{username_lower}' for user ID {user_id}.")
                save_user_data()
        else:
            logger.info(f"User {user_id} has no username and cannot be targeted.")

        roles = get_user_roles(user_id)

        if not roles:
            await message.reply_text("You don't have a role assigned to use this bot.")
            logger.warning(f"Unauthorized access attempt by user {user_id}")
            return ConversationHandler.END

        logger.info(f"Received message from user {user_id} with roles '{roles}'")

        # Determine if the message is part of a media group
        media_group_id = message.media_group_id

        if media_group_id:
            # Handle media group (album)
            application = context.application
            pending_media_groups = application.bot_data.setdefault('pending_media_groups', defaultdict(list))

            pending_media_groups[media_group_id].append(message)
            logger.debug(f"Added message {message.message_id} to media group {media_group_id}.")

            if len(pending_media_groups[media_group_id]) == 1:
                # First message in the media group, start a task to process after a short delay
                asyncio.create_task(process_media_group(media_group_id, context))

            # Do not proceed further until the media group is processed
            return ConversationHandler.END
        else:
            # Handle single message
            if len(roles) > 1:
                # Present role selection keyboard
                keyboard = get_role_selection_keyboard(roles)
                await message.reply_text(
                    "You have multiple roles. Please choose which role you want to use to send this message:",
                    reply_markup=keyboard
                )
                # Store pending messages
                context.bot_data['pending_messages'] = [message]
                logger.info(f"User {user_id} has multiple roles and is prompted to select one.")
                return SELECT_ROLE
            else:
                # Single role, proceed to send message
                selected_role = roles[0]
                context.bot_data['sender_role'] = selected_role

                # Handle PDF documents and text messages
                if message.document and message.document.mime_type == 'application/pdf':
                    # Send confirmation using UUID
                    await send_confirmation(
                        [message],
                        context,
                        selected_role,
                        list(ROLE_MAP.get(selected_role, [])),
                        target_roles=SENDING_ROLE_TARGETS.get(selected_role, [])
                    )
                    logger.info(f"User {user_id} is sending PDF documents.")
                elif message.text:
                    # Send confirmation using UUID
                    await send_confirmation(
                        [message],
                        context,
                        selected_role,
                        list(ROLE_MAP.get(selected_role, [])),
                        target_roles=SENDING_ROLE_TARGETS.get(selected_role, [])
                    )
                    logger.info(f"User {user_id} is sending text messages.")
                else:
                    await message.reply_text("Please send PDF documents or text messages only.")
                    logger.warning(f"User {user_id} sent an unsupported message type.")
                    return ConversationHandler.END

                return CONFIRMATION

    except Exception as e:
        logger.error(f"Error in handle_general_message: {e}")
        await update.message.reply_text("An error occurred. Please try again later.")
        return ConversationHandler.END

async def process_media_group(media_group_id, context):
    """Process all messages in a media group after a short delay."""
    try:
        await asyncio.sleep(1)  # Wait to collect all messages in the media group

        application = context.application
        pending_media_groups = application.bot_data.get('pending_media_groups', {})
        messages = pending_media_groups.pop(media_group_id, [])

        if not messages:
            logger.error(f"No messages found for media group {media_group_id}.")
            return

        user_id = messages[0].from_user.id
        roles = get_user_roles(user_id)

        if not roles:
            await messages[0].reply_text("You don't have a role assigned to use this bot.")
            logger.warning(f"Unauthorized access attempt by user {user_id}")
            return

        # Determine target roles based on sender's roles
        if len(roles) > 1:
            # Present role selection keyboard
            keyboard = get_role_selection_keyboard(roles)
            await messages[0].reply_text(
                "You have multiple roles. Please choose which role you want to use to send this message:",
                reply_markup=keyboard
            )
            # Store pending messages
            application.bot_data['pending_messages'] = messages
            logger.info(f"User {user_id} with multiple roles is prompted to select one for media group {media_group_id}.")
            return SELECT_ROLE
        else:
            # Single role, proceed to send message
            selected_role = roles[0]
            application.bot_data['sender_role'] = selected_role

            target_roles = SENDING_ROLE_TARGETS.get(selected_role, [])
            target_ids = set()
            for role in target_roles:
                target_ids.update(ROLE_MAP.get(role, []))
            target_ids.discard(user_id)

            if not target_ids:
                await messages[0].reply_text("No recipients found to send your message.")
                logger.warning(f"No recipients found for user {user_id} with role '{selected_role}' in media group {media_group_id}.")
                return

            # Send confirmation using UUID
            await send_confirmation(messages, context, selected_role, list(target_ids), target_roles=target_roles)
            logger.info(f"User {user_id} is sending media group {media_group_id} with role '{selected_role}'.")

            return CONFIRMATION

    except Exception as e:
        logger.error(f"Error in process_media_group: {e}")
        await update.message.reply_text("An error occurred while processing your media group. Please try again later.")

# ------------------ Command Handlers ------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /start command."""
    try:
        user = update.effective_user
        if not user.username:
            await update.message.reply_text(
                "Please set a Telegram username in your profile to use specific commands like `-@username`.",
                parse_mode='Markdown'
            )
            logger.warning(f"User {user.id} has no username and cannot be targeted.")
            return

        # Store the username and user_id
        username_lower = user.username.lower()
        user_data_store[username_lower] = user.id
        logger.info(f"User {user.id} with username '{username_lower}' started the bot.")

        # Save to JSON file
        save_user_data()

        display_name = get_display_name(user)

        await update.message.reply_text(
            f"Hello, {display_name}! Welcome to the Team Communication Bot.\n\n"
            "Feel free to send messages using the available commands."
        )
    except Exception as e:
        logger.error(f"Error in start handler: {e}")
        await update.message.reply_text("An error occurred while starting the bot. Please try again later.")

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all stored usernames and their user IDs. Restricted to Tara Team."""
    try:
        user_id = update.message.from_user.id
        roles = get_user_roles(user_id)

        if 'tara_team' not in roles:
            await update.message.reply_text("You are not authorized to use this command.")
            logger.warning(f"Unauthorized access attempt by user {user_id} for /listusers.")
            return

        if not user_data_store:
            await update.message.reply_text("No users have interacted with the bot yet.")
            return

        user_list = "\n".join([f"@{username}: {uid}" for username, uid in user_data_store.items()])
        await update.message.reply_text(f"**Registered Users:**\n{user_list}", parse_mode='Markdown')
        logger.info(f"User {user_id} requested the list of users.")
    except Exception as e:
        logger.error(f"Error in list_users handler: {e}")
        await update.message.reply_text("An error occurred while listing users. Please try again later.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Provide help information to users with subcommands explanations."""
    try:
        help_text = (
            "📘 *Available Commands:*\n\n"
            "/start - Initialize interaction with the bot.\n"
            "/listusers - List all registered users (Tara Team only).\n"
            "/help - Show this help message.\n"
            "/refresh - Refresh your user information.\n"
            "/cancel - Cancel the current operation.\n\n"
            "*Message Sending Triggers:*\n"
            "`-team` - Send a message to your own team and Tara Team.\n"
            "`-t` - Send a message exclusively to the Tara Team.\n\n"
            "*Specific Commands for Tara Team:*\n"
            "`-@username` - Send a message to a specific user.\n"
            "`-w` - Send a message to the Writer Team.\n"
            "`-e` - Send a message to the Editor Team.\n"
            "`-mcq` - Send a message to the MCQs Team.\n"
            "`-d` - Send a message to the Digital Writers.\n"
            "`-de` - Send a message to the Design Team.\n"
            "`-mf` - Send a message to the Mind Map & Form Creation Team.\n"
            "`-c` - Send a message to the Editor Team.\n\n"
            "*Admin Commands (Tara Team only):*\n"
            "/mute [user_id] - Mute yourself or another user.\n"
            "/muteid <user_id> - Mute a specific user by their ID.\n"
            "/unmuteid <user_id> - Unmute a specific user by their ID.\n"
            "/listmuted - List all currently muted users.\n\n"
            "📌 *Notes:*\n"
            "- Only Tara Team members can use the side commands and `-@username` command.\n"
            "- Use `/cancel` to cancel any ongoing operation."
        )
        await update.message.reply_text(help_text, parse_mode='Markdown')
        logger.info(f"User {update.effective_user.id} requested help.")
    except Exception as e:
        logger.error(f"Error in help_command handler: {e}")
        await update.message.reply_text("An error occurred while providing help. Please try again later.")

async def refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Refresh user information."""
    try:
        user = update.effective_user
        if not user.username:
            await update.message.reply_text(
                "Please set a Telegram username in your profile to refresh your information.",
                parse_mode='Markdown'
            )
            logger.warning(f"User {user.id} has no username and cannot be refreshed.")
            return

        # Store the username and user_id
        username_lower = user.username.lower()
        user_data_store[username_lower] = user.id
        logger.info(f"User {user.id} with username '{username_lower}' refreshed their info.")

        # Save to JSON file
        save_user_data()

        await update.message.reply_text(
            "Your information has been refreshed successfully."
        )
    except Exception as e:
        logger.error(f"Error in refresh handler: {e}")
        await update.message.reply_text("An error occurred while refreshing your information. Please try again later.")

# ------------------ Mute Command Handlers ------------------

async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /mute command for Tara Team."""
    try:
        user_id = update.message.from_user.id
        roles = get_user_roles(user_id)

        # Restrict to Tara Team only
        if 'tara_team' not in roles:
            await update.message.reply_text("You are not authorized to use this command.")
            logger.warning(f"Unauthorized mute attempt by user {user_id} with roles '{roles}'.")
            return

        # Mute self or another user
        if len(context.args) == 0:
            target_user_id = user_id
        elif len(context.args) == 1:
            try:
                target_user_id = int(context.args[0])
            except ValueError:
                await update.message.reply_text("Please provide a valid user ID.")
                return
        else:
            await update.message.reply_text("Usage: /mute [user_id]")
            return

        if target_user_id in muted_users:
            if target_user_id == user_id:
                await update.message.reply_text("You are already muted.")
            else:
                await update.message.reply_text("This user is already muted.")
            logger.info(f"Attempt to mute already muted user {target_user_id} by {user_id}.")
            return

        muted_users.add(target_user_id)
        save_muted_users()

        if target_user_id == user_id:
            await update.message.reply_text("You have been muted and can no longer send messages through this bot.")
            logger.info(f"User {user_id} has muted themselves.")
        else:
            # Attempt to get the username of the target user
            target_username = None
            for uname, uid in user_data_store.items():
                if uid == target_user_id:
                    target_username = uname
                    break

            if target_username:
                await update.message.reply_text(f"User `@{target_username}` has been muted.", parse_mode='Markdown')
                logger.info(f"User {user_id} has muted user {target_user_id} (@{target_username}).")
            else:
                await update.message.reply_text(f"User ID {target_user_id} has been muted.")
                logger.info(f"User {user_id} has muted user {target_user_id}.")
    except Exception as e:
        logger.error(f"Error in mute_command handler: {e}")
        await update.message.reply_text("An error occurred while muting the user. Please try again later.")

async def mute_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /muteid command for Tara Team."""
    await mute_command(update, context)

async def unmute_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /unmuteid command for Tara Team."""
    try:
        user_id = update.message.from_user.id
        roles = get_user_roles(user_id)

        # Restrict to Tara Team only
        if 'tara_team' not in roles:
            await update.message.reply_text("You are not authorized to use this command.")
            logger.warning(f"Unauthorized unmute attempt by user {user_id} with roles '{roles}'.")
            return

        if len(context.args) != 1:
            await update.message.reply_text("Usage: /unmuteid <user_id>")
            return

        try:
            target_user_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Please provide a valid user ID.")
            return

        if target_user_id in muted_users:
            muted_users.remove(target_user_id)
            save_muted_users()

            # Attempt to get the username of the target user
            target_username = None
            for uname, uid in user_data_store.items():
                if uid == target_user_id:
                    target_username = uname
                    break

            if target_username:
                await update.message.reply_text(f"User `@{target_username}` has been unmuted.", parse_mode='Markdown')
                logger.info(f"User {user_id} has unmuted user {target_user_id} (@{target_username}).")
            else:
                await update.message.reply_text(f"User ID {target_user_id} has been unmuted.")
                logger.info(f"User {user_id} has unmuted user {target_user_id}.")
        else:
            await update.message.reply_text(f"User ID {target_user_id} is not muted.")
            logger.warning(f"Attempt to unmute user {target_user_id} who is not muted by user {user_id}.")
    except Exception as e:
        logger.error(f"Error in unmute_id_command handler: {e}")
        await update.message.reply_text("An error occurred while unmuting the user. Please try again later.")

async def list_muted_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /listmuted command for Tara Team."""
    try:
        user_id = update.message.from_user.id
        roles = get_user_roles(user_id)

        if 'tara_team' not in roles:
            await update.message.reply_text("You are not authorized to use this command.")
            logger.warning(f"Unauthorized access attempt by user {user_id} for /listmuted.")
            return

        if not muted_users:
            await update.message.reply_text("No users are currently muted.")
            return

        muted_list = []
        for uid in muted_users:
            username = None
            for uname, id_ in user_data_store.items():
                if id_ == uid:
                    username = uname
                    break
            if username:
                muted_list.append(f"@{username} (ID: {uid})")
            else:
                muted_list.append(f"ID: {uid}")

        muted_users_text = "\n".join(muted_list)
        await update.message.reply_text(f"**Muted Users:**\n{muted_users_text}", parse_mode='Markdown')
        logger.info(f"User {user_id} requested the list of muted users.")
    except Exception as e:
        logger.error(f"Error in list_muted_command handler: {e}")
        await update.message.reply_text("An error occurred while listing muted users. Please try again later.")

# ------------------ Conversation Handlers ------------------

# Define the ConversationHandler for specific user commands
specific_user_conv_handler = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex(re.compile(r'^\s*-\@([A-Za-z0-9_]{5,32})\s*$', re.IGNORECASE)), specific_user_trigger)],
    states={
        SPECIFIC_USER_MESSAGE: [MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, specific_user_message_handler)],
        CONFIRMATION: [CallbackQueryHandler(confirmation_handler, pattern='^(confirm:|cancel:).*')],
    },
    fallbacks=[CommandHandler('cancel', cancel)],
    allow_reentry=True,
)

# Define the ConversationHandler for specific team commands
specific_team_conv_handler = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex(re.compile(r'^-(w|e|mcq|d|de|mf|c)$', re.IGNORECASE)), specific_team_trigger)],
    states={
        SPECIFIC_TEAM_MESSAGE: [MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, specific_team_message_handler)],
        CONFIRMATION: [CallbackQueryHandler(confirmation_handler, pattern='^(confirm:|cancel:).*')],
    },
    fallbacks=[CommandHandler('cancel', cancel)],
    allow_reentry=True,
)

# Define the ConversationHandler for general team messages (-team)
team_conv_handler = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex(re.compile(r'^-team$', re.IGNORECASE)), team_trigger)],
    states={
        SELECT_ROLE: [CallbackQueryHandler(select_role_handler, pattern='^role:.*$|^cancel_role_selection$')],
        CONFIRMATION: [CallbackQueryHandler(confirmation_handler, pattern='^(confirm:|cancel:).*')],
    },
    fallbacks=[CommandHandler('cancel', cancel)],
    allow_reentry=True,
)

# Define the ConversationHandler for Tara team messages (-t)
tara_conv_handler = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex(re.compile(r'^-t$', re.IGNORECASE)), tara_trigger)],
    states={
        TARA_MESSAGE: [MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, tara_message_handler)],
        CONFIRMATION: [CallbackQueryHandler(confirmation_handler, pattern='^(confirm:|cancel:).*')],
    },
    fallbacks=[CommandHandler('cancel', cancel)],
    allow_reentry=True,
)

# Define the ConversationHandler for general messages
general_conv_handler = ConversationHandler(
    entry_points=[MessageHandler(
        (filters.TEXT | filters.Document.ALL) &
        ~filters.COMMAND &
        ~filters.Regex(re.compile(r'^-@')) &
        ~filters.Regex(re.compile(r'^-(w|e|mcq|d|de|mf|t|c|team)$', re.IGNORECASE)),
        handle_general_message
    )],
    states={
        SELECT_ROLE: [CallbackQueryHandler(select_role_handler, pattern='^role:.*$|^cancel_role_selection$')],
        CONFIRMATION: [CallbackQueryHandler(confirmation_handler, pattern='^(confirm:|cancel:).*')],
    },
    fallbacks=[CommandHandler('cancel', cancel)],
    allow_reentry=True,
)

# ------------------ Error Handler ------------------

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log the error and send a message to the user if necessary."""
    logger.error(f"Exception while handling an update: {context.error}", exc_info=True)
    # Optionally, notify the user about the error
    if isinstance(update, Update) and update.message:
        try:
            await update.message.reply_text("An error occurred. Please try again later.")
        except Exception as e:
            logger.error(f"Failed to send error message to user: {e}")

# ------------------ Main Function ------------------

def main():
    """Main function to start the Telegram bot."""
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is not set in environment variables.")
        return

    try:
        # Build the application
        application = ApplicationBuilder().token(BOT_TOKEN).build()

        # Initialize bot_data storage for pending media groups
        application.bot_data['pending_media_groups'] = defaultdict(list)

        # Add command handlers
        application.add_handler(CommandHandler('start', start))
        application.add_handler(CommandHandler('listusers', list_users))
        application.add_handler(CommandHandler('help', help_command))
        application.add_handler(CommandHandler('refresh', refresh))
        application.add_handler(CommandHandler('mute', mute_command))
        application.add_handler(CommandHandler('muteid', mute_id_command))
        application.add_handler(CommandHandler('unmuteid', unmute_id_command))
        application.add_handler(CommandHandler('listmuted', list_muted_command))

        # Add ConversationHandlers
        application.add_handler(specific_user_conv_handler)
        application.add_handler(specific_team_conv_handler)
        application.add_handler(team_conv_handler)
        application.add_handler(tara_conv_handler)
        application.add_handler(general_conv_handler)  # Newly added

        # Add the error handler
        application.add_error_handler(error_handler)

        # Start the Bot using long polling
        logger.info("Bot started polling...")
        application.run_polling()
    except Exception as e:
        logger.error(f"Failed to start the bot: {e}")

if __name__ == '__main__':
    main()

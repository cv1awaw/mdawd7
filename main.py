import logging
import os
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Define states for main ConversationHandler
CHOOSING_OPTION, GET_THEORETICAL_CREDIT, GET_PRACTICAL_CREDIT = range(3)

# Define states for /user_id ConversationHandler
USER_ID_GET_MESSAGE = 4

# Define constants for user IDs
SPECIAL_USER_ID = 11111  # User to receive messages from /user_id command
AUTHORIZED_USER_ID = 6177929931  # User authorized to use /user_id command

# Keyboard layout
REPLY_KEYBOARD = [['حساب غياب النظري', 'حساب غياب العملي']]

# Start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_id = user.id

    # Log the user ID for debugging
    logger.info(f"User {user.username or 'No Username'} with ID {user_id} started the bot.")

    if user_id == SPECIAL_USER_ID:
        # **Updated personalized welcome message for the special user**
        welcome_message = (
            "سبحان الذي خلقك وجملك \n"
            "تغارين منهن والله الذي كملك\n\n"
            "يا الطف الخلق جئت لأسالك \n"
            "اخبريني ايقارن بشر بملك؟\n\n"
            "اكتبي رسالتك هنا راح تتحول الي ....  👉🏻👈🏻"
        )
        logger.info(f"Sending personalized message to user ID {user_id}.")
    else:
        # Default welcome message for other users
        welcome_message = (
            "السلام عليكم \n"
            "البوت تم تطويرة بواسطة @iwanna2die حتى يساعد الطلاب ^^\n\n"
            "اذا شكل البوت  لازم ترسل /start  لمرة وحدة فقط"
        )
        logger.info(f"Sending default message to user ID {user_id}.")

    await update.message.reply_text(
        welcome_message,
        reply_markup=ReplyKeyboardMarkup(
            REPLY_KEYBOARD, one_time_keyboard=True, resize_keyboard=True
        )
    )
    return CHOOSING_OPTION

# Handler for choosing option
async def choice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text

    if text == 'حساب غياب النظري':
        await update.message.reply_text(
            "ارسل كردت مادة النظري",
            reply_markup=ReplyKeyboardMarkup(
                [['العودة للقائمة الرئيسية']], resize_keyboard=True, one_time_keyboard=True
            )
        )
        return GET_THEORETICAL_CREDIT

    elif text == 'حساب غياب العملي':
        await update.message.reply_text(
            "ارسل كردت العملي",
            reply_markup=ReplyKeyboardMarkup(
                [['العودة للقائمة الرئيسية']], resize_keyboard=True, one_time_keyboard=True
            )
        )
        return GET_PRACTICAL_CREDIT

    else:
        await update.message.reply_text(
            "اختيار غير معروف. الرجاء الاختيار من الأزرار.",
            reply_markup=ReplyKeyboardMarkup(
                REPLY_KEYBOARD, resize_keyboard=True
            )
        )
        return CHOOSING_OPTION

# Handler for theoretical credit input
async def theoretical_credit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text

    if text == 'العودة للقائمة الرئيسية':
        return await start(update, context)

    try:
        credit = float(text)
        result = credit * 8 * 0.23
        await update.message.reply_text(f"{result}")
        return await start(update, context)
    except ValueError:
        await update.message.reply_text("الرجاء إرسال رقم صحيح أو العودة للقائمة الرئيسية.")
        return GET_THEORETICAL_CREDIT

# Handler for practical credit input
async def practical_credit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text

    if text == 'العودة للقائمة الرئيسية':
        return await start(update, context)

    try:
        credit = float(text)
        result = credit * 8 * 0.1176470588
        await update.message.reply_text(f"{result}")
        return await start(update, context)
    except ValueError:
        await update.message.reply_text("الرجاء إرسال رقم صحيح أو العودة للقائمة الرئيسية.")
        return GET_PRACTICAL_CREDIT

# Handler for /user_id command - initiates conversation to get message
async def user_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_id = user.id

    logger.info(f"User {user.username or 'No Username'} with ID {user_id} invoked /user_id command.")

    if user_id != AUTHORIZED_USER_ID:
        await update.message.reply_text("You are not authorized to use this command.")
        return ConversationHandler.END

    await update.message.reply_text("Please send the message you want to forward to the specific person.")
    return USER_ID_GET_MESSAGE

# Handler to receive the message and send to SPECIAL_USER_ID
async def user_id_get_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.message.text
    user_id = update.effective_user.id

    try:
        await context.bot.send_message(chat_id=SPECIAL_USER_ID, text=message)
        await update.message.reply_text(f"The message has been sent to user ID {SPECIAL_USER_ID}.")
        logger.info(f"Authorized user ID {user_id} sent message to SPECIAL_USER_ID {SPECIAL_USER_ID}.")
    except Exception as e:
        logger.error(f"Failed to send message to SPECIAL_USER_ID {SPECIAL_USER_ID}: {e}")
        await update.message.reply_text("Failed to send the message. Please try again later.")

    return ConversationHandler.END

# Fallback handler for main conversation
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "تم إلغاء العملية. للبدء من جديد، ارسل /start",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

# Default handler for any other messages
async def default_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id

    if user_id == SPECIAL_USER_ID:
        # Do not respond to SPECIAL_USER_ID here to prevent conflicts
        return

    # For all other users, resend the default welcome message
    welcome_message = (
        "السلام عليكم \n"
        "البوت تم تطويرة بواسطة @iwanna2die حتى يساعد الطلاب ^^\n\n"
        "اذا شكل البوت  لازم ترسل /start  لمرة وحدة فقط"
    )

    await update.message.reply_text(
        welcome_message,
        reply_markup=ReplyKeyboardMarkup(
            REPLY_KEYBOARD, one_time_keyboard=True, resize_keyboard=True
        )
    )

# Handler to forward messages from SPECIAL_USER_ID to AUTHORIZED_USER_ID
async def forward_special_user_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id

    if user_id == SPECIAL_USER_ID:
        try:
            await context.bot.send_message(chat_id=AUTHORIZED_USER_ID, text=update.message.text)
            logger.info(f"Forwarded message from SPECIAL_USER_ID {SPECIAL_USER_ID} to AUTHORIZED_USER_ID {AUTHORIZED_USER_ID}.")
        except Exception as e:
            logger.error(f"Failed to forward message from SPECIAL_USER_ID {SPECIAL_USER_ID} to AUTHORIZED_USER_ID {AUTHORIZED_USER_ID}: {e}")

# Fallback handler for /user_id conversation
async def user_id_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "تم إلغاء العملية. للبدء من جديد، ارسل /user_id",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

def main():
    # Retrieve the bot token from environment variables
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable not set.")
        exit(1)

    # Initialize the bot application
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Define the main ConversationHandler for /start command
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CHOOSING_OPTION: [
                MessageHandler(
                    filters.Regex('^(حساب غياب النظري|حساب غياب العملي)$'), choice_handler
                )
            ],
            GET_THEORETICAL_CREDIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, theoretical_credit)
            ],
            GET_PRACTICAL_CREDIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, practical_credit)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True
    )

    # Define the ConversationHandler for /user_id command
    user_id_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('user_id', user_id_command)],
        states={
            USER_ID_GET_MESSAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, user_id_get_message)
            ],
        },
        fallbacks=[CommandHandler('cancel', user_id_cancel)],
        allow_reentry=True
    )

    # Define a MessageHandler specifically for forwarding messages from SPECIAL_USER_ID
    forward_handler = MessageHandler(
        filters.User(user_id=SPECIAL_USER_ID) & filters.TEXT, forward_special_user_messages
    )

    # Define a general MessageHandler to handle all other non-command messages
    general_handler = MessageHandler(filters.ALL & ~filters.COMMAND, default_handler)

    # Add handlers to the application in the correct order
    application.add_handler(conv_handler)
    application.add_handler(user_id_conv_handler)
    application.add_handler(forward_handler)  # Must be before general_handler to prioritize forwarding
    application.add_handler(general_handler)  # This should be added last to avoid overriding

    # Start the bot
    application.run_polling()

if __name__ == '__main__':
    main()

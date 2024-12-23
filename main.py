import logging
import os
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Define the /delete command handler
async def delete_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Removes the custom keyboard from the user by sending a ReplyKeyboardRemove.
    """
    try:
        await update.message.reply_text(
            "تم إزالة القائمة.", 
            reply_markup=ReplyKeyboardRemove()
        )
        logger.info(f"Removed custom keyboard for user ID {update.effective_user.id}.")
    except Exception as e:
        logger.error(f"Error removing keyboard: {e}")
        await update.message.reply_text(
            "حدث خطأ أثناء محاولة إزالة القائمة. حاول مرة أخرى."
        )

def main():
    # Retrieve the bot token from environment variables
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable not set.")
        exit(1)

    # Initialize the bot application
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Define the /delete command handler
    delete_handler = CommandHandler('delete', delete_menu)

    # Add the handler to the application
    application.add_handler(delete_handler)

    # Start the bot
    logger.info("Starting the bot...")
    application.run_polling()

if __name__ == '__main__':
    main()

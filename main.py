import os
import datetime
from flask import Flask, request
from telegram import Bot, Update, ChatPermissions
from telegram.ext import Dispatcher, MessageHandler, Filters
from sqlalchemy import create_engine, Column, Integer, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base
app = Flask(name)
# Get the bot token from environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("No BOT_TOKEN provided. Set the BOT_TOKEN environment variable.")
bot = Bot(token=BOT_TOKEN)
# Set up the dispatcher for handling updates
dispatcher = Dispatcher(bot=bot, update_queue=None, workers=0)
# Database setup
engine = create_engine('sqlite:///warnings.db', connect_args={'check_same_thread': False})
Session = sessionmaker(bind=engine)
session = Session()
Base = declarative_base()
class UserWarning(Base):
    tablename = 'user_warnings'
    user_id = Column(Integer, primary_key=True)
    warning_count = Column(Integer, default=0)
    mute_until = Column(DateTime, nullable=True)
Base.metadata.create_all(engine)
# Function to detect Arabic messages
def detect_arabic(update, context):
    message = update.effective_message
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if message.text:
        # Check if the message contains Arabic characters
        if any('\u0600' <= c <= '\u06FF' or '\u0750' <= c <= '\u077F' or '\u08A0' <= c <= '\u08FF' for c in message.text):
            # Fetch or create a user warning record
            user_warning = session.query(UserWarning).filter_by(user_id=user_id).first()
            if not user_warning:
                user_warning = UserWarning(user_id=user_id)
                session.add(user_warning)
            # Check if user is currently muted
            now = datetime.datetime.utcnow()
            if user_warning.mute_until and user_warning.mute_until > now:
                # User is muted, delete their message
                message.delete()
                return
            # Increment warning count
            user_warning.warning_count += 1
            # Determine mute duration based on warning count
            if user_warning.warning_count == 1:
                mute_duration = datetime.timedelta(days=1)
                ban_message = (
                    "1- Primary warning sent to the student and he/she will be banned from sending messages for ONE DAY."
                )
            elif user_warning.warning_count == 2:
                mute_duration = datetime.timedelta(days=7)
                ban_message = (
                    "2- Second warning sent to the student and he/she will be banned from sending messages for SEVEN DAYS."
                )
            else:
                mute_duration = None  # Indefinite mute
                ban_message = (
                    "3- Third warning sent to the student and he/she will be banned from sending messages and may be addressed to DISCIPLINARY COMMITTEE."
                )
            # Set mute_until time
            if mute_duration:
                user_warning.mute_until = now + mute_duration
            else:
                user_warning.mute_until = datetime.datetime.max  # Indefinite mute
            session.commit()
            # Mute the user in the group
            permissions = ChatPermissions(can_send_messages=False)
            bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=permissions,
                until_date=user_warning.mute_until
            )
            # Send private warning message to the user
            warning_text = (
                "Communication Channels Regulation\n"
                "The Official Groups and channels have been created to facilitate the communication between the students and the officials, therefore we hereby list the regulation for the groups:\n"
"• The official language of the group is ENGLISH ONLY\n"
                "• Avoid any side discussion by any means.\n"
                "• When having a general request or question it should be sent to the group and the student should tag the related official (TARA or other officials).\n"
                "• The messages should be sent in the official working hours (8:00 AM to 5:00 PM) and only important questions and inquiries should be sent after the mentioned time.\n\n"
                "Please note that not complying with the above-mentioned regulation will result in:\n"
                f"{ban_message}"
            )
            bot.send_message(chat_id=user_id, text=warning_text)
            # Delete the original message
            message.delete()
# Add the handler to the dispatcher
dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), detect_arabic))
# Route for Telegram webhook
@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return 'OK'
# Home route
@app.route('/')
def index():
    return 'Bot is running.'
if name == 'main':
    # For local testing; in production, Koyeb will handle the server run
    app.run(port=8443)

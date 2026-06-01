import logging
import os
import time
import asyncio
import math
import uuid
import requests
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ExtBot
from flask import Flask, request
from pymongo import MongoClient

# --- CONFIG & LOGGING ---
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("BOT_TOKEN")
LOG_GROUP_ID = os.getenv("LOG_GROUP_ID") 
MONGO_URI = os.getenv("MONGO_URI")

# MongoDB Setup
mongo_client = MongoClient(MONGO_URI)
db = mongo_client['TelegramBotDB']
users_collection = db['users']

CHANNELS = {
    "1": os.getenv("CH_1"),
    "2": os.getenv("CH_2"),
    "3": os.getenv("CH_3"),
    "4": os.getenv("CH_4"),
    "5": os.getenv("CH_5"),
}

user_data = {}

# --- BOT LOGIC FUNCTIONS ---
async def start_with_text(update: Update, bot: ExtBot, text_message: str):
    if not update.message:
        return
    
    user = update.effective_user
    user_id = int(user.id)
    parts = text_message.split()
    raw_arg = parts[1] if len(parts) > 1 else ""

    if not raw_arg:
        await bot.send_message(chat_id=update.message.chat_id, text="👋 Welcome! Bot active hai.")
        return

    # --- MONGODB VERIFICATION CHECK ---
    # Database me user ko find karein aur check karein ki wo verified hai ya nahi
    db_user = users_collection.find_one({"user_id": user_id})
    
    # Maan rahe hain ki aapke DB me verified users ke liye {"status": "verified"} ya {"verified": True} hoga.
    # Aap is condition ko apne DB structure ke hisab se badal sakte hain.
    if not db_user or not db_user.get("verified", False):
        await bot.send_message(
            chat_id=update.message.chat_id, 
            text="❌ **Aap verified nahi hain!** Kripya pehle verify karein."
        )
        return

    # Agar user verified hai, toh video processing suru hogi:
    extracted_args = raw_arg.split('_') if "_" in raw_arg else [raw_arg]
    if len(extracted_args) == 2:
        file_id, ch_num = extracted_args
        video_list = [int(file_id)]
        target_ch = CHANNELS.get(str(ch_num))
        batch_size = 1
    elif len(extracted_args) == 4:
        start_id, end_id, ch_num, total_parts = map(int, extracted_args)
        video_list = list(range(start_id, end_id + 1))
        target_ch = CHANNELS.get(str(ch_num))
        batch_size = math.ceil(len(video_list) / total_parts)
    else:
        return

    user_data[user_id] = {
        "videos": video_list,
        "channel": target_ch,
        "batch_size": batch_size,
        "current_index": 0
    }
    
    # Monetag step hata kar seedha video deliver kar rahe hain
    await process_video_delivery(update, bot, user_id, user)

async def process_video_delivery(update, bot: ExtBot, user_id, user):
    # Chat ID nikalne ke liye backup check (message ya callback)
    chat_id = update.message.chat_id if update.message else update.callback_query.message.chat_id
    
    data = user_data.get(user_id)
    if not data:
        return
        
    start_idx = data['current_index']
    end_idx = start_idx + data['batch_size']
    current_batch = data['videos'][start_idx:end_idx]
    
    videos_sent_successfully = False
    for msg_id in current_batch:
        try:
            await bot.copy_message(chat_id=chat_id, from_chat_id=data['channel'], message_id=msg_id)
            videos_sent_successfully = True
            await asyncio.sleep(0.5)
        except Exception as e: 
            logging.error(e)

    # LOG CHANNEL LOGIC
    if videos_sent_successfully and LOG_GROUP_ID:
        try:
            first_name = user.first_name or "User"
            username = f"@{user.username}" if user.username else "No Username"
            log_message = (
                f"📤 **Video Received Successfully!**\n\n"
                f"👤 **User:** {first_name}\n"
                f"🆔 **ID:** `{user_id}`\n"
                f"🌐 **Username:** {username}\n"
                f"📦 **Batch:** {start_idx + 1} to {min(end_idx, len(data['videos']))}\n"
                f"⏰ **Time:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
            )
            await bot.send_message(chat_id=LOG_GROUP_ID, text=log_message, parse_mode="Markdown")
        except Exception as log_err:
            logging.error(f"Log Channel Error: {log_err}")

    user_data[user_id]['current_index'] = end_idx
    
    # Agar abhi aur videos baaki hain batch me
    if end_idx < len(data['videos']):
        # Kisi ad step ke bina seedha agla batch bhejenge
        await process_video_delivery(update, bot, user_id, user)
    else:
        await bot.send_message(chat_id=chat_id, text="🎉 Saari videos complete ho gayi hain!")
        if user_id in user_data:
            del user_data[user_id]

# --- FLASK SERVER & WEBHOOK ---
app = Flask(__name__)

@app.route('/')
def home(): return "Bot is Active!"

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == "POST":
        try:
            update_json = request.get_json(force=True)
            bot = ExtBot(token=TOKEN)
            update = Update.de_json(update_json, bot)
            
            if update.message and update.message.text:
                if update.message.text.startswith('/start'):
                    asyncio.run(start_with_text(update, bot, update.message.text))
            
            # Note: Callback query logic hata diya hai kyunki buttons ab use nahi ho rahe hain.
            return "OK", 200
        except Exception as e:
            logging.error(f"Webhook Error: {e}")
            return "OK", 200
    return "Invalid Request", 400

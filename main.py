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
MONETAG_LINK = os.getenv("MONETAG_DIRECT_LINK") or "https://google.com"
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

    # In-memory session setup
    user_data[user_id] = {
        "videos": video_list,
        "channel": target_ch,
        "batch_size": batch_size,
        "current_index": 0,
        "click_time": 0,
        "ad_clicked": False
    }

    # 🔍 MONGO CHECK: Kya user pehle se verified hai database me?
    existing_user = users_collection.find_one({"user_id": user_id})
    
    if existing_user and existing_user.get("is_verified", False):
        # Agar MongoDB me data hai, to direct video bypass karke bhej do
        await process_video_delivery(update, bot, user_id, user, is_callback=False)
    else:
        # Agar MongoDB me data nahi hai (Aapne delete kar diya), to ad step dikhao
        await send_ad_step_fixed(update, bot, user_id)

async def send_ad_step_fixed(update, bot: ExtBot, user_id):
    if user_id not in user_data:
        return
    
    keyboard = [
        [InlineKeyboardButton("📺 Watch Ad (Start Timer)", callback_data="click_ad")],
        [InlineKeyboardButton("✅ Verify & Get Videos", callback_data="verify_batch")]
    ]
    
    msg_text = (
        "⚠️ **Ad Verification Required!**\n\n"
        "1. Pehle **'📺 Watch Ad (Start Timer)'** button par click karein.\n"
        "2. Ad khulne ke baad **30 Seconds** tak wait karein.\n"
        "3. Wapas aakar **'✅ Verify & Get Videos'** par click karke apni video lein."
    )
    
    chat_id = update.message.chat_id if update.message else update.callback_query.message.chat_id
    await bot.send_message(chat_id=chat_id, text=msg_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def button_callback_fixed(update: Update, bot: ExtBot):
    query = update.callback_query
    user_id = int(query.from_user.id)
    user = query.from_user
    
    if user_id not in user_data:
        await query.answer("❌ Session expired. Please try again.", show_alert=True)
        return

    if query.data == "click_ad":
        user_data[user_id]['click_time'] = time.time()
        user_data[user_id]['ad_clicked'] = True
        
        await query.answer("⏱️ Timer Started! Khulne wale page par 30 seconds rukiye.", show_alert=True)
        
        updated_keyboard = [
            [InlineKeyboardButton("🔗 Open Ad Link Now", url=MONETAG_LINK)],
            [InlineKeyboardButton("✅ Verify & Get Videos", callback_data="verify_batch")]
        ]
        try:
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(updated_keyboard))
        except:
            pass
        return

    if query.data == "verify_batch":
        if not user_data[user_id].get('ad_clicked', False):
            await query.answer("❌ Pehle 'Watch Ad (Start Timer)' button par click karein!", show_alert=True)
            return

        click_time = user_data[user_id].get('click_time', 0)
        gap = time.time() - click_time
        
        if gap < 30:
            await query.answer(f"❌ Ad verification incomplete! Abhi bhi {int(30 - gap)}s baaki hain.", show_alert=True)
            return
        
        # 💾 MONGO SAVE: Verification successful toh DB me save karo
        users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"is_verified": True, "verified_at": datetime.utcnow()}},
            upsert=True
        )

        await query.answer("✅ Verification Successful!")
        await process_video_delivery(update, bot, user_id, user, is_callback=True)

async def process_video_delivery(update, bot: ExtBot, user_id, user, is_callback=True):
    # Chat ID handle karne ke liye checks (Message ya Callback dono ke liye)
    if is_callback:
        chat_id = update.callback_query.message.chat_id
    else:
        chat_id = update.message.chat_id

    data = user_data[user_id]
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
    if end_idx < len(data['videos']):
        user_data[user_id]['click_time'] = 0
        user_data[user_id]['ad_clicked'] = False
        await send_ad_step_fixed(update, bot, user_id)
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
            elif update.callback_query:
                asyncio.run(button_callback_fixed(update, bot))
                
            return "OK", 200
        except Exception as e:
            logging.error(f"Webhook Error: {e}")
            return "OK", 200
    return "Invalid Request", 400

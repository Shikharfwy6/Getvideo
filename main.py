import logging
import os
import time
import asyncio
import math
import uuid
import requests
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
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

CHANNEL_URL_IDS = {
    "1": "3952628014",
    "2": "3758252316",
    "3": "3736158308",
    "4": "3195006898",
    "5": "3307449853"
}

user_data = {}

API_CONFIGS = [
    {"name": "arolinks", "url": "https://arolinks.com/api?api=f4617908b561110a219cd2b65bc255c2c2c6ff8a&url={url}"},
    {"name": "vplink", "url": "https://vplink.in/api?api=017ab25e4402465d00047e8e2897f3c6b38afbd9&url={url}"},
    {"name": "instantlinks", "url": "https://instantlinks.co/api?api=323c4585c0d0b8bc04a170cd57a2e6a74ac6d8aa&url={url}"}
]

# --- HELPER FUNCTIONS ---
def get_short_link(api_template, destination_url):
    try:
        formatted_url = api_template.format(url=destination_url)
        response = requests.get(formatted_url, timeout=10)
        if response.status_code == 200:
            res_data = response.text.strip()
            if "shortenedUrl" in res_data or "shortlink" in res_data:
                import json
                try:
                    js = json.loads(res_data)
                    return js.get("shortenedUrl") or js.get("shortlink") or destination_url
                except:
                    return res_data
            return res_data
    except Exception as e:
        logging.error(f"Shortener API Error: {e}")
    return destination_url

def check_verification(user_id):
    user = users_collection.find_one({"_id": int(user_id)})
    if user:
        expiry = user.get("expiry")
        if expiry and datetime.utcnow() < expiry:
            if user.get("status") == "verify":
                return True
    return False

def get_next_api_index(user_id):
    user = users_collection.find_one({"_id": int(user_id)})
    if user:
        return user.get("current_api_idx", 0) % len(API_CONFIGS)
    return 0

# --- BOT LOGIC FUNCTIONS ---
async def start_with_text(update: Update, bot: ExtBot, text_message: str):
    if not update.message:
        return
    
    user = update.effective_user
    user_id = int(user.id)
    parts = text_message.split()
    
    raw_arg = parts[1] if len(parts) > 1 else ""

    if raw_arg.startswith("v_"):
        token_parts = raw_arg.split("_")
        if len(token_parts) == 3:
            _, target_uid, unique_token = token_parts
            if str(user_id) == str(target_uid):
                db_user = users_collection.find_one({"_id": user_id})
                if db_user and db_user.get("pending_token") == unique_token:
                    next_idx = (db_user.get("current_api_idx", 0) + 1) % len(API_CONFIGS)
                    
                    users_collection.update_one(
                        {"_id": user_id},
                        {
                            "$set": {
                                "status": "verify",
                                "expiry": datetime.utcnow() + timedelta(hours=8),
                                "current_api_idx": next_idx
                            },
                            "$unset": {"pending_token": ""}
                        },
                        upsert=True
                    )
                    await bot.send_message(chat_id=update.message.chat_id, text="✅ **Verification Successful!** Aapki verification agle 8 ghanto ke liye valid hai.")
                    
                    if user_id in user_data and "saved_arg" in user_data[user_id]:
                        raw_arg = user_data[user_id]["saved_arg"]
                    else:
                        return
                else:
                    await bot.send_message(chat_id=update.message.chat_id, text="❌ **Verification link invalid ya expired!**")
                    return
            else:
                await bot.send_message(chat_id=update.message.chat_id, text="❌ Yeh link kisi aur user ke liye hai.")
                return

    if not raw_arg:
        await bot.send_message(chat_id=update.message.chat_id, text="👋 Welcome! Bot active hai.")
        return

    is_verified = check_verification(user_id)
    if not is_verified:
        unique_token = str(uuid.uuid4())[:12]
        
        users_collection.update_one(
            {"_id": user_id},
            {"$set": {"pending_token": unique_token}},
            upsert=True
        )
        
        bot_username = (await bot.get_me()).username
        verification_dest_url = f"https://t.me/{bot_username}?start=v_{user_id}_{unique_token}"
        
        api_idx = get_next_api_index(user_id)
        selected_api = API_CONFIGS[api_idx]
        shortened_verify_url = get_short_link(selected_api["url"], verification_dest_url)
        
        user_data[user_id] = {"saved_arg": raw_arg}
        
        keyboard = [[InlineKeyboardButton("🔗 Complete Verification", url=shortened_verify_url)]]
        await bot.send_message(
            chat_id=update.message.chat_id,
            text=f"⚠️ **Verification Required!**\n\nAapko 8 ghante ke liye verify karna hoga.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
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

    user_data[user_id] = {
        "videos": video_list,
        "channel": target_ch,
        "batch_size": batch_size,
        "current_index": 0,
        "click_time": 0
    }
    await send_ad_step_fixed(update, bot, user_id)

async def send_ad_step_fixed(update, bot: ExtBot, user_id):
    if user_id not in user_data:
        return
    
    # 2 Buttons Fix: 1st Button acts as both redirect & timer start using web_app feature.
    keyboard = [
        [InlineKeyboardButton("📺 Watch Ad & Start Timer", web_app=WebAppInfo(url=MONETAG_LINK))],
        [InlineKeyboardButton("✅ Verify & Get Videos", callback_data="verify_batch")]
    ]
    
    # Jaise hi user Ad button dabayega, hmare system ko instant message milega and timer back-end me automatic run hona suru ho jayega.
    user_data[user_id]['click_time'] = time.time()
    
    msg_text = "⚠️ **Ad Verification**\n\n1. **Watch Ad** wale button par click karein.\n2. **30 Seconds** tak page par wait karein.\n3. Uske baad **Verify & Get Videos** par click karein."
    chat_id = update.message.chat_id if update.message else update.callback_query.message.chat_id
    await bot.send_message(chat_id=chat_id, text=msg_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def button_callback_fixed(update: Update, bot: ExtBot):
    query = update.callback_query
    user_id = int(query.from_user.id)
    user = query.from_user
    
    if user_id not in user_data:
        await query.answer("❌ Session expired.", show_alert=True)
        return

    if query.data == "verify_batch":
        click_time = user_data[user_id].get('click_time', 0)
        
        # 30 second time check
        gap = time.time() - click_time
        if gap < 30:
            await query.answer(f"❌ Ad verification complete nahi hui! Aur {int(30 - gap)}s baaki hain.", show_alert=True)
            return
        
        await query.answer("✅ Ad Verified! Sending Videos...")
        
        data = user_data[user_id]
        start_idx = data['current_index']
        end_idx = start_idx + data['batch_size']
        current_batch = data['videos'][start_idx:end_idx]
        
        videos_sent_successfully = False
        for msg_id in current_batch:
            try:
                await bot.copy_message(chat_id=query.message.chat_id, from_chat_id=data['channel'], message_id=msg_id)
                videos_sent_successfully = True
                await asyncio.sleep(0.5)
            except Exception as e: 
                logging.error(e)

        # FIX 1: LOG CHANNELS NOTIFICATION (Srif jab user ko video receive ho chuki ho)
        if videos_sent_successfully and LOG_GROUP_ID:
            try:
                first_name = user.first_name or "User"
                username = f"@{user.username}" if user.username else "No Username"
                log_message = (
                    f"📤 **Video Received Successfully!**\n\n"
                    f"👤 **User:** {first_name}\n"
                    f"🆔 **ID:** `{user_id}`\n"
                    f"🌐 **Username:** {username}\n"
                    f"📦 **Batch Range:** {start_idx + 1} to {min(end_idx, len(data['videos']))}\n"
                    f"⏰ **Time:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
                )
                await bot.send_message(chat_id=LOG_GROUP_ID, text=log_message, parse_mode="Markdown")
            except Exception as log_err:
                logging.error(f"Error sending to Log Channel: {log_err}")

        user_data[user_id]['current_index'] = end_idx
        if end_idx < len(data['videos']):
            # Next part ke liye timer clear karke fir se generate karenge
            user_data[user_id]['click_time'] = 0
            await send_ad_step_fixed(update, bot, user_id)
        else:
            await bot.send_message(chat_id=query.message.chat_id, text="🎉 Saari videos complete ho gayi hain!")
            del user_data[user_id]

# --- FLASK SERVER & WEBHOOK ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Active!"

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == "POST":
        try:
            update_json = request.get_json(force=True)
            bot = ExtBot(token=TOKEN)
            update = Update.de_json(update_json, bot)
            
            if update.message and update.message.text:
                text = update.message.text
                if text.startswith('/start'):
                    asyncio.run(start_with_text(update, bot, text))
                    
            elif update.callback_query:
                asyncio.run(button_callback_fixed(update, bot))
                
            return "OK", 200
        except Exception as e:
            logging.error(f"Webhook Execution Error: {e}")
            return "OK", 200
    return "Invalid Request", 400

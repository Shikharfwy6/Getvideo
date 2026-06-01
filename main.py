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

# Aapke bataye gaye private channels ki IDs ka mapping
CHANNEL_CHAT_IDS = {
    "1": "3952628014",
    "2": "3758252316",
    "3": "3736158308",
    "4": "3195006898",
    "5": "3307449853"
}

user_data = {}

# 3 API loop configs (Index: 0=arolinks, 1=vplink, 2=instantlinks)
API_CONFIGS = [
    {"name": "Arolinks", "url": "https://arolinks.com/api?api=f4617908b561110a219cd2b65bc255c2c2c6ff8a&url={url}"},
    {"name": "Vplink", "url": "https://vplink.in/api?api=017ab25e4402465d00047e8e2897f3c6b38afbd9&url={url}"},
    {"name": "Instantlinks", "url": "https://instantlinks.co/api?api=323c4585c0d0b8bc04a170cd57a2e6a74ac6d8aa&url={url}"}
]

# --- HELPER FUNCTIONS ---
def check_verification(user_id):
    """Checks if the user is currently verified and within the 8-hour window."""
    user = users_collection.find_one({"_id": int(user_id)})
    if user:
        expiry = user.get("expiry")
        if expiry and datetime.utcnow() < expiry:
            if user.get("status") == "verify":
                return True
    return False

def get_shortlink(api_index, destination_url):
    """Generates shortlink dynamically based on current API rotation index."""
    try:
        config = API_CONFIGS[api_index]
        api_url = config["url"].format(url=destination_url)
        response = requests.get(api_url).json()
        
        if response.get("status") == "success":
            return response.get("shortenedUrl")
        elif "shortenedUrl" in response:
            return response["shortenedUrl"]
    except Exception as e:
        logging.error(f"Error generating shortlink from {API_CONFIGS[api_index]['name']}: {e}")
    return destination_url

# --- BOT LOGIC FUNCTIONS ---
async def start_with_text(update: Update, bot: ExtBot, text_message: str):
    if not update.message:
        return
    
    user = update.effective_user
    user_id = int(user.id)
    chat_id = update.message.chat_id
    
    parts = text_message.split()
    raw_arg = parts[1] if len(parts) > 1 else ""

    bot_username = (await bot.get_me()).username

    # CASE 1: Normal Start without any arguments
    if not raw_arg:
        await bot.send_message(chat_id=chat_id, text="👋 Welcome! Kuch download karne ke liye link par click karein.")
        return

    # CASE 2: User successfully verified hokar shortlink se wapas aaya hai
    if raw_arg.startswith("verify_"):
        token = raw_arg.split("_")[1]
        
        db_user = users_collection.find_one({"_id": user_id, "current_token": token})
        if db_user:
            now = datetime.utcnow()
            expiry_time = now + timedelta(hours=8)
            
            current_index = db_user.get("api_index", 0)
            next_index = (current_index + 1) % len(API_CONFIGS)
            
            users_collection.update_one(
                {"_id": user_id},
                {
                    "$set": {
                        "status": "verify",
                        "expiry": expiry_time,
                        "api_index": next_index,
                        "time_log": now.strftime("%H:%M:%S")
                    },
                    "$unset": {"current_token": ""}
                }
            )
            
            saved_arg = db_user.get("pending_arg")
            if saved_arg:
                await start_with_text(update, bot, f"/start {saved_arg}")
            else:
                await bot.send_message(chat_id=chat_id, text="✅ Verification Successful! Aap agle 8 ghante ke liye verified hain.")
        else:
            await bot.send_message(chat_id=chat_id, text="❌ Invalid ya Expired Verification Link! Kripya dobara try karein.")
        return

    # CASE 3: User ne video file query hit ki hai (?start=8607_2 ya batch link)
    extracted_args = raw_arg.split('_') if "_" in raw_arg else [raw_arg]
    if len(extracted_args) == 2 or len(extracted_args) == 4:
        if len(extracted_args) == 2:
            file_id, ch_num = extracted_args
            video_list = [int(file_id)]
            target_ch = CHANNELS.get(str(ch_num))
            batch_size = 1
        else:
            start_id, end_id, ch_num, total_parts = map(int, extracted_args)
            video_list = list(range(start_id, end_id + 1))
            target_ch = CHANNELS.get(str(ch_num))
            batch_size = math.ceil(len(video_list) / total_parts)

        # 'ch_num' aur 'file_id' ko session me store kiya direct link ke liye
        user_data[user_id] = {
            "videos": video_list,
            "channel": target_ch,
            "batch_size": batch_size,
            "current_index": 0,
            "ch_num": str(ch_num),
            "video_id": str(video_list[0]) # Batch link me pehle video ka link dikhega
        }

        is_verified = check_verification(user_id)
        
        if is_verified:
            await process_video_delivery(update, bot, user_id, user)
        else:
            db_user = users_collection.find_one({"_id": user_id})
            api_index = db_user.get("api_index", 0) if db_user else 0
            
            secure_token = uuid.uuid4().hex[:12]
            
            users_collection.update_one(
                {"_id": user_id},
                {
                    "$set": {
                        "status": "unverified",
                        "current_token": secure_token,
                        "pending_arg": raw_arg,
                        "api_index": api_index
                    }
                },
                upsert=True
            )
            
            destination_link = f"https://t.me/{bot_username}?start=verify_{secure_token}"
            short_link = get_shortlink(api_index, destination_link)
            
            api_name = API_CONFIGS[api_index]["name"]
            keyboard = [
                [InlineKeyboardButton(f"🔐 Verify via {api_name}", url=short_link)]
            ]
            
            msg_text = (
                "⚠️ **⚠️ सत्यापन आवश्यक Verification Required!**\n\n"
                f"आपका वेरिफिकेशन सेशन समाप्त (expire) हो चुका है या आप एक नए यूजर हैं। "
                f"अपनी पसंदीदा वीडियो बिना किसी रुकावट के देखने के लिए, कृपया नीचे दिए गए लिंक पर क्लिक करके **{api_name}** सत्यापित (verify) करें। "
                "वेरीफाई करने के बाद आपको 8 घंटे तक विज्ञापन-मुक्त (ad-free) अनुभव मिलेगा, जिससे आप बिना किसी रुकावट के अपनी वीडियो देख पाएंगे।"
            )
            await bot.send_message(chat_id=chat_id, text=msg_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def process_video_delivery(update, bot: ExtBot, user_id, user):
    if user_id not in user_data:
        return

    data = user_data[user_id]
    chat_id = update.message.chat_id if update.message else update.callback_query.message.chat_id
    
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

    # LOG CHANNEL LOGIC WITH DIRECT PRIVATE CHANNEL LINK
    if videos_sent_successfully and LOG_GROUP_ID:
        try:
            ch_num = data.get("ch_num", "")
            video_id = data.get("video_id", "")
            
            # Channel number ke base par private channel ki ID fetch karein
            channel_chat_id = CHANNEL_CHAT_IDS.get(ch_num)
            
            if channel_chat_id and video_id:
                # Private channel ka direct link format generate kiya
                direct_video_link = f"https://t.me/c/{channel_chat_id}/{video_id}"
            else:
                direct_video_link = "N/A"
            
            first_name = user.first_name or "User"
            username = f"@{user.username}" if user.username else "No Username"
            log_message = (
                f"📤 **Video Received Successfully!**\n\n"
                f"👤 **User:** {first_name}\n"
                f"🆔 **ID:** `{user_id}`\n"
                f"🌐 **Username:** {username}\n"
                f"📦 **Batch:** {start_idx + 1} to {min(end_idx, len(data['videos']))}\n"
                f"🔗 **Direct Video Link:** [Click Here]({direct_video_link})\n"
                f"⏰ **Time:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
            )
            await bot.send_message(chat_id=LOG_GROUP_ID, text=log_message, parse_mode="Markdown", disable_web_page_preview=True)
        except Exception as log_err:
            logging.error(f"Log Channel Error: {log_err}")

    user_data[user_id]['current_index'] = end_idx
    if end_idx < len(data['videos']):
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
            return "OK", 200
        except Exception as e:
            logging.error(f"Webhook Error: {e}")
            return "OK", 200
    return "Invalid Request", 400

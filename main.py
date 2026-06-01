import logging
import os
import time
import asyncio
import math
import secrets
import string
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

# MongoDB Connection
client = MongoClient(MONGO_URI)
db = client['tg_bot_db']
users_collection = db['verified_users']

# TTL Index (8 ghante baad data automatic delete ho jayega)
users_collection.create_index("expire_at", expireAfterSeconds=0)

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

# Video tracking memory session
active_video_sessions = {}

# --- HELPER FUNCTIONS ---
def generate_random_token():
    allowed_chars = string.ascii_letters + string.digits
    return "vrf_" + "".join(secrets.choice(allowed_chars) for _ in range(12))

def get_short_link(user_id, bot_username, token):
    import requests
    destination_url = f"https://t.me/{bot_username}?start={token}"
    
    user_db = users_collection.find_one({"_id": user_id})
    loop_count = user_db.get("loop_count", 0) if user_db else 0
    
    # 8-8 Ghante ka loop track sequence
    if loop_count % 3 == 0:
        api_url = f"https://arolinks.com/api?api=f4617908b561110a219cd2b65bc255c2c2c6ff8a&url={destination_url}&format=text"
    elif loop_count % 3 == 1:
        api_url = f"https://vplink.in/api?api=017ab25e4402465d00047e8e2897f3c6b38afbd9&url={destination_url}&format=text"
    else:
        api_url = f"https://instantlinks.co/api?api=323c4585c0d0b8bc04a170cd57a2e6a74ac6d8aa&url={destination_url}&format=text"
        
    try:
        res = requests.get(api_url, timeout=10)
        if res.status_code == 200 and res.text.strip():
            return res.text.strip()
    except Exception as e:
        logging.error(f"Shortener API Request Failed: {e}")
    
    return destination_url

async def send_all_videos(bot: ExtBot, chat_id, user_id):
    """User ko instantly sari videos copy karke dene ka function"""
    if user_id not in active_video_sessions:
        return
        
    data = active_video_sessions[user_id]
    videos = data['videos']
    channel = data['channel']
    
    # Send videos looping
    for msg_id in videos:
        try:
            await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=channel,
                message_id=msg_id
            )
            await asyncio.sleep(0.5)
        except Exception as e:
            logging.error(f"Error transferring video {msg_id}: {e}")
            
    # --- LOG TO GROUP ONLY AFTER SUCCESSFUL DELIVERY ---
    if LOG_GROUP_ID:
        try:
            # User details nikalne ke liye dummy update variable handle na karke direct call
            chat_member = await bot.get_chat(chat_id)
            first_name = chat_member.first_name.replace("<", "&lt;").replace(">", "&gt;") if chat_member.first_name else "User"
            username = f"@{chat_member.username}" if chat_member.username else "No Username"
            
            log_msg = (
                f"✅ <b>User Passed Shortener & Got Video</b>\n\n"
                f"• <b>Name:</b> {first_name}\n"
                f"• <b>User ID:</b> <code>{user_id}</code>\n"
                f"• <b>Username:</b> {username}\n"
                f"• <b>Channel no.</b> {data['ch_num']}\n"
                f"   {data['video_link_str']}"
            )
            await bot.send_message(chat_id=LOG_GROUP_ID, text=log_msg, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:
            logging.error(f"Group notification failed: {e}")
            
    # Message complete hone par session delete
    del active_video_sessions[user_id]
    await bot.send_message(chat_id=chat_id, text="🎉 **Aapki saari videos successfully send kar di gayi hain!**")

# --- BOT LOGIC FUNCTIONS ---
async def start_with_text(update: Update, bot: ExtBot, text_message: str):
    if not update.message or not update.effective_user:
        return
    
    user_id = update.effective_user.id
    chat_id = update.message.chat_id
    parts = text_message.split()
    bot_info = await bot.get_me()
    bot_username = bot_info.username

    # STEP 1: DB me ID check karo
    user_db = users_collection.find_one({"_id": user_id})
    
    # STEP 2: Agar nahi hai to unverified data insert karo
    if not user_db:
        user_db = {
            "_id": user_id,
            "status": "unverified",
            "loop_count": 0,
            "pending_token": None
        }
        users_collection.insert_one(user_db)

    if len(parts) <= 1:
        await bot.send_message(chat_id=chat_id, text="👋 Welcome! Bot active hai. Kisi video link par click karke aao.")
        return

    raw_arg = parts[1]

    # CASE A: User shortener solve karke return aaya hai token ke sath
    if raw_arg.startswith("vrf_"):
        if user_db.get("pending_token") == raw_arg:
            current_loop = user_db.get("loop_count", 0)
            expire_time = datetime.utcnow() + timedelta(hours=8)
            
            # DB verify status update
            users_collection.update_one(
                {"_id": user_id},
                {
                    "$set": {
                        "status": "verify",
                        "expire_at": expire_time,
                        "loop_count": current_loop + 1,
                        "pending_token": None
                    }
                }
            )
            await bot.send_message(chat_id=chat_id, text="✅ Verification Successful! Aapka 8 ghante ka access active ho gaya hai.")
            
            # Instant sari video send karo jo memory session me ruki thi
            if user_id in active_video_sessions:
                await send_all_videos(bot, chat_id, user_id)
            return
        else:
            await bot.send_message(chat_id=chat_id, text="❌ Invalid Token ya link expire ho chuka hai. Dubara try karein.")
            return

    # CASE B: User normal/bulk video links ke sath aaya hai (e.g. 8607_2)
    extracted_args = raw_arg.split('_') if "_" in raw_arg else [raw_arg]
    ch_num = "Unknown"
    video_link_str = ""
    video_list = []

    if len(extracted_args) == 2:
        try:
            file_id, ch_num = extracted_args
            video_list = [int(file_id)]
            target_ch = CHANNELS.get(str(ch_num))
            url_id = CHANNEL_URL_IDS.get(str(ch_num))
            if url_id:
                video_link_str = f"https://t.me/c/{url_id}/{file_id}"
        except ValueError:
            await bot.send_message(chat_id=chat_id, text="❌ Invalid Format.")
            return
    
    elif len(extracted_args) == 4:
        try:
            start_id, end_id, ch_num, total_parts = map(int, extracted_args)
            video_list = list(range(start_id, end_id + 1))
            target_ch = CHANNELS.get(str(ch_num))
            url_id = CHANNEL_URL_IDS.get(str(ch_num))
            if url_id:
                video_link_str = f"https://t.me/c/{url_id}/{start_id}"
        except ValueError:
            await bot.send_message(chat_id=chat_id, text="❌ Invalid parameters value.")
            return
    else:
        await bot.send_message(chat_id=chat_id, text="❌ Invalid Param strings.")
        return

    if not target_ch:
        await bot.send_message(chat_id=chat_id, text="❌ Channel config missing.")
        return

    # Video records session memory track me dalo
    active_video_sessions[user_id] = {
        "videos": video_list,
        "channel": target_ch,
        "video_link_str": video_link_str,
        "ch_num": ch_num
    }

    # STEP 3: Check Verify Status. Agar verified nahi hai to Shortener link do
    if user_db.get("status") != "verify":
        token = generate_random_token()
        users_collection.update_one({"_id": user_id}, {"$set": {"pending_token": token}})
        
        status_msg = await bot.send_message(chat_id=chat_id, text="⏳ Generating secure shortener link...")
        short_link = get_short_link(user_id, bot_username, token)
        
        try:
            await bot.delete_message(chat_id=chat_id, message_id=status_msg.message_id)
        except Exception:
            pass
            
        keyboard = [[InlineKeyboardButton("🔗 Click Here to Verify (8 Hours)", url=short_link)]]
        await bot.send_message(
            chat_id=chat_id,
            text="⚠️ **Verification Required!**\n\nVideos unlock karne ke liye niche diye link par click karke open karein. Ek baar verify karne par 8 ghante tak koi link nahi aayega.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return

    # STEP 4: Agar already verified hai, to INSTANT saari videos copy karke de do
    await send_all_videos(bot, chat_id, user_id)


# --- FLASK SERVER ROUTING PIPELINES ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Active without Monetag!"

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
                    
            return "OK", 200
        except Exception as e:
            logging.error(f"Global webhook error: {e}")
            return "OK", 200
            
    return "Bad Request", 400

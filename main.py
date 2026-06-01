import logging
import os
import asyncio
import math
import uuid
import requests
import traceback
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ExtBot
from flask import Flask, request, Response
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

# --- FIXED CHANNELS MATRIX ---
CHANNELS = {
    "1": "-1003952628014",
    "2": "-1003758252316",
    "3": "-1003736158308",
    "4": "-1003195006898",
    "5": "-1003307449853"
}

CHANNEL_CHAT_IDS = {
    "1": "3952628014",
    "2": "3758252316",
    "3": "3736158308",
    "4": "3195006898",
    "5": "3307449853"
}

API_CONFIGS = [
    {"name": "Arolinks", "url": "https://arolinks.com/api?api=f4617908b561110a219cd2b65bc255c2c2c6ff8a&url={url}"},
    {"name": "Vplink", "url": "https://vplink.in/api?api=017ab25e4402465d00047e8e2897f3c6b38afbd9&url={url}"},
    {"name": "Instantlinks", "url": "https://instantlinks.co/api?api=323c4585c0d0b8bc04a170cd57a2e6a74ac6d8aa&url={url}"}
]

# --- HELPER FUNCTIONS ---
def check_verification(user_id):
    try:
        user = users_collection.find_one({"_id": int(user_id)})
        if user:
            expiry = user.get("expiry")
            if expiry and datetime.utcnow() < expiry:
                if user.get("status") == "verify":
                    return True
    except Exception as e:
        logging.error(f"Database check error: {e}")
    return False

def get_shortlink(api_index, destination_url):
    try:
        config = API_CONFIGS[api_index]
        api_url = config["url"].format(url=destination_url)
        response = requests.get(api_url, timeout=7).json()
        if response.get("status") == "success":
            return response.get("shortenedUrl")
        elif "shortenedUrl" in response:
            return response["shortenedUrl"]
    except Exception as e:
        logging.error(f"Shortener API failed for {API_CONFIGS[api_index]['name']}: {e}")
    return destination_url

# --- BOT LOGIC FUNCTIONS ---
async def start_with_text(update: Update, bot: ExtBot, text_message: str):
    user = update.effective_user
    user_id = int(user.id) if user else 0
    chat_id = update.message.chat_id if update.message else 0
    
    try:
        if not update.message:
            return
        
        parts = text_message.split()
        raw_arg = parts[1] if len(parts) > 1 else ""
        
        try:
            bot_info = await bot.get_me()
            bot_username = bot_info.username
        except Exception as e:
            logging.error(f"Failed to get bot info: {e}")
            bot_username = "Getvideo81827_bot"

        if not raw_arg:
            await bot.send_message(chat_id=chat_id, text="👋 Welcome! Kuch download karne ke liye link par click karein.")
            return

        # CASE 1: Verification Callback Handling
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
                    await bot.send_message(chat_id=chat_id, text="✅ Verification Successful! Videos send ho rahi hain...")
                    await start_with_text(update, bot, f"/start {saved_arg}")
                else:
                    await bot.send_message(chat_id=chat_id, text="✅ Verification Successful! Aap agle 8 ghante ke liye verified hain.")
            else:
                await bot.send_message(chat_id=chat_id, text="❌ Invalid ya Expired Verification Link! Kripya dobara try karein.")
            return

        # CASE 2: Video Query Processing System
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

            if not target_ch:
                await bot.send_message(chat_id=chat_id, text=f"❌ Configuration Error: CH_{ch_num} galat hai ya found nahi hua!")
                return

            is_verified = check_verification(user_id)
            
            if is_verified:
                await process_video_delivery_sync(chat_id, bot, user_id, user, video_list, target_ch, batch_size, ch_num)
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
                
                keyboard = [[InlineKeyboardButton(f"🔐 Verify via {api_name}", url=short_link)]]
                msg_text = (
                    "⚠️ **सत्यापन आवश्यक Verification Required!**\n\n"
                    f"आपका वेरिफिकेशन सेशन समाप्त हो चुका है। "
                    f"वीडियो पाने के लिए नीचे दिए गए बटन पर击 करके **{api_name}** से वेरीफाई करें। "
                    "यह सिर्फ 8 घंटे के लिए मान्य रहेगा।"
                )
                await bot.send_message(chat_id=chat_id, text=msg_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    except Exception as start_err:
        logging.error(f"Error in start_with_text: {start_err}")
        if LOG_GROUP_ID:
            try:
                err_trace = traceback.format_exc()[-1500:]  # Limit to avoid telegram length limit
                err_msg = (
                    f"🚨 **CRITICAL ERROR IN START LOGIC!**\n\n"
                    f"👤 **User:** `{user_id}`\n"
                    f"💬 **Command:** `{text_message}`\n\n"
                    f"⚠️ **Traceback:**\n`{err_trace}`"
                )
                await bot.send_message(chat_id=LOG_GROUP_ID, text=err_msg, parse_mode="Markdown")
            except: pass

async def process_video_delivery_sync(chat_id, bot: ExtBot, user_id, user, video_list, target_ch, batch_size, ch_num):
    current_index = 0
    video_id_first = str(video_list[0])
    
    while current_index < len(video_list):
        start_idx = current_index
        end_idx = start_idx + batch_size
        current_batch = video_list[start_idx:end_idx]
        
        videos_sent_successfully = False
        for msg_id in current_batch:
            try:
                await bot.copy_message(chat_id=chat_id, from_chat_id=target_ch, message_id=msg_id)
                videos_sent_successfully = True
                await asyncio.sleep(0.8) 
            except Exception as telegram_error: 
                logging.error(f"Copy message failed: {telegram_error}")
                if LOG_GROUP_ID:
                    try:
                        err_message = (
                            f"❌ **VIDEO DELIVERY FAILED!**\n\n"
                            f"👤 **User:** {user.first_name} (`{user_id}`)\n"
                            f"📁 **Source Channel:** `{target_ch}`\n"
                            f"🆔 **Message ID:** `{msg_id}`\n"
                            f"⚠️ **Error Details:** `{str(telegram_error)}`"
                        )
                        await bot.send_message(chat_id=LOG_GROUP_ID, text=err_message, parse_mode="Markdown")
                    except: pass

        if videos_sent_successfully and LOG_GROUP_ID:
            try:
                channel_chat_id = CHANNEL_CHAT_IDS.get(str(ch_num))
                direct_video_link = f"https://t.me/c/{channel_chat_id}/{video_id_first}" if channel_chat_id else "N/A"
                
                first_name = user.first_name or "User"
                username = f"@{user.username}" if user.username else "No Username"
                log_message = (
                    f"📤 **Video Received Successfully!**\n\n"
                    f"👤 **User:** {first_name}\n"
                    f"🆔 **ID:** `{user_id}`\n"
                    f"🌐 **Username:** {username}\n"
                    f"📦 **Batch:** {start_idx + 1} to {min(end_idx, len(video_list))}\n"
                    f"🔗 **Direct Link:** [Click Here]({direct_video_link})\n"
                    f"⏰ **Time:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
                )
                await bot.send_message(chat_id=LOG_GROUP_ID, text=log_message, parse_mode="Markdown", disable_web_page_preview=True)
            except Exception as log_err:
                logging.error(f"Log Channel Error: {log_err}")

        current_index = end_idx
        await asyncio.sleep(1.5) 

    try:
        await bot.send_message(chat_id=chat_id, text="🎉 Saari videos complete ho gayi hain!")
    except: pass

# --- FLASK SERVER & WEBHOOK (VERCEL OPTIMIZED + AUTO LOGGING) ---
app = Flask(__name__)

@app.route('/')
def home(): 
    return "Bot is Active with Full Features & Rotation Matrix!"

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == "POST":
        bot = ExtBot(token=TOKEN)
        try:
            update_json = request.get_json(force=True)
            update = Update.de_json(update_json, bot)
            
            if update and update.message and update.message.text:
                if update.message.text.startswith('/start'):
                    # Vercel engine ke liye clean standalone run
                    asyncio.run(start_with_text(update, bot, update.message.text))
            
            return "OK", 200
        except Exception as main_err:
            logging.error(f"Global Webhook Crash: {main_err}")
            if LOG_GROUP_ID:
                try:
                    full_trace = traceback.format_exc()[-1500:]
                    alert_msg = (
                        f"💥 **WEBHOOK GLOBAL CRASH ALERT!**\n\n"
                        f"⚠️ **Error Message:** `{str(main_err)}`\n\n"
                        f"📊 **Full Stack Trace:**\n`{full_trace}`"
                    )
                    # Sync message delivery to channel during emergency crash
                    asyncio.run(bot.send_message(chat_id=LOG_GROUP_ID, text=alert_msg, parse_mode="Markdown"))
                except Exception as log_send_err:
                    logging.error(f"Failed to send alert to log channel: {log_send_err}")
            
            # 200 OK dena zaroori hai taaki loop block na ho
            return "OK", 200
            
    return "Method Not Allowed", 405

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

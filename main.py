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
MONETAG_LINK = os.getenv("MONETAG_DIRECT_LINK")
LOG_GROUP_ID = os.getenv("LOG_GROUP_ID") 
MONGO_URI = os.getenv("MONGO_URI")

# MongoDB Connection
client = MongoClient(MONGO_URI)
db = client['tg_bot_db']
users_collection = db['verified_users']

# TTL Index (8 hours automatically data wipe handles from here)
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

# Global in-memory user sessions for parameters storage
user_sessions = {}

# --- HELPER FUNCTIONS ---
def generate_random_token():
    allowed_chars = string.ascii_letters + string.digits
    return "vrf_" + "".join(secrets.choice(allowed_chars) for _ in range(12))

def get_short_link(user_id, bot_username, token):
    import requests
    destination_url = f"https://t.me/{bot_username}?start={token}"
    
    user_db = users_collection.find_one({"_id": user_id})
    loop_count = user_db.get("loop_count", 0) if user_db else 0
    
    # 8-8 Ghante ke loop badalne ka API sequence tracker
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

# --- BOT LOGIC FUNCTIONS ---
async def start_with_text(update: Update, bot: ExtBot, text_message: str):
    if not update.message:
        return
    
    user = update.effective_user
    user_id = user.id
    chat_id = update.message.chat_id
    parts = text_message.split()
    
    bot_info = await bot.get_me()
    bot_username = bot_info.username

    # ------------------ AAPKA LOGIC FIX ------------------
    # STEP 1: Sabse pehle check karo user database me hai ya nahi
    user_db = users_collection.find_one({"_id": user_id})
    
    # STEP 2: Agar user database me nahi hai, to uska naya poora data generate karo
    if not user_db:
        user_db = {
            "_id": user_id,
            "status": "unverified",
            "loop_count": 0
        }
        users_collection.insert_one(user_db)
        logging.info(f"New User {user_id} generated and saved to MongoDB as unverified.")
    # -----------------------------------------------------

    # Simple Check without arguments
    if len(parts) <= 1:
        await bot.send_message(chat_id=chat_id, text="👋 Welcome! Bot active hai. Kisi video link par click karke aao.")
        return

    raw_arg = parts[1]

    # CASE A: User shortener completely solve karke return aaya hai token lekar
    if raw_arg.startswith("vrf_"):
        session = user_sessions.get(user_id)
        if session and session.get("expected_token") == raw_arg:
            current_loop = user_db.get("loop_count", 0)
            expire_time = datetime.utcnow() + timedelta(hours=8)
            
            # DB entry modify dynamically (Status set to verified for 8 hours)
            users_collection.update_one(
                {"_id": user_id},
                {
                    "$set": {
                        "status": "verify",
                        "expire_at": expire_time,
                        "loop_count": current_loop + 1
                    }
                }
            )
            await bot.send_message(chat_id=chat_id, text="✅ Verification Successful! Aapka 8 ghante ka session active ho gaya hai.")
            
            # Agar session storage me videos backup records hain to direct move on to ad
            if "videos" in session and session["videos"]:
                await send_ad_step_fixed(update, bot, user_id, is_next_part=False)
            return
        else:
            await bot.send_message(chat_id=chat_id, text="❌ Invalid Token ya dynamic link expire ho chuka hai. Dubara koshish karein.")
            return

    # CASE B: User video links ke sath aaya hai (Jaise 8607_2 ya bulk lines)
    extracted_args = raw_arg.split('_') if "_" in raw_arg else [raw_arg]
    ch_num = "Unknown"
    video_link_str = ""
    video_list = []
    batch_size = 1

    if len(extracted_args) == 2:
        try:
            file_id, ch_num = extracted_args
            video_list = [int(file_id)]
            target_ch = CHANNELS.get(str(ch_num))
            url_id = CHANNEL_URL_IDS.get(str(ch_num))
            if url_id:
                video_link_str = f"https://t.me/c/{url_id}/{file_id}"
        except ValueError:
            await bot.send_message(chat_id=chat_id, text="❌ Invalid Format parameters.")
            return
    
    elif len(extracted_args) == 4:
        try:
            start_id, end_id, ch_num, total_parts = map(int, extracted_args)
            video_list = list(range(start_id, end_id + 1))
            target_ch = CHANNELS.get(str(ch_num))
            total_videos = len(video_list)
            batch_size = math.ceil(total_videos / (total_parts if total_parts > 0 else 1))
            url_id = CHANNEL_URL_IDS.get(str(ch_num))
            if url_id:
                video_link_str = f"https://t.me/c/{url_id}/{start_id}"
        except ValueError:
            await bot.send_message(chat_id=chat_id, text="❌ Parameters validation values error.")
            return
    else:
        await bot.send_message(chat_id=chat_id, text="❌ Param strings verification mismatch error.")
        return

    if not target_ch:
        await bot.send_message(chat_id=chat_id, text="❌ Channel setting configurations missing.")
        return

    # Store user core queue settings inside memory session
    user_sessions[user_id] = {
        "videos": video_list,
        "channel": target_ch,
        "batch_size": batch_size,
        "current_index": 0,
        "click_time": 0,
        "video_link_str": video_link_str,
        "ch_num": ch_num
    }

    # STEP 3: Ab check karo ki status 'verify' hai ya nahi.
    # Naya user hoga to uska status 'unverified' hoga, isliye woh is if condition ke andar chala jayega aur block ho jayega!
    if user_db.get("status") != "verify":
        token = generate_random_token()
        user_sessions[user_id]["expected_token"] = token
        
        status_msg = await bot.send_message(chat_id=chat_id, text="⏳ Generating secure 8-hour gateway url pass...")
        short_link = get_short_link(user_id, bot_username, token)
        
        try:
            await bot.delete_message(chat_id=chat_id, message_id=status_msg.message_id)
        except Exception:
            pass
            
        keyboard = [[InlineKeyboardButton("🔗 Click Here to Verify (8 Hours)", url=short_link)]]
        await bot.send_message(
            chat_id=chat_id,
            text="⚠️ **Verification Required!**\n\nAapka 8-ghante ka bypass token active nahi hai ya expire ho chuka hai. Niche diye link par click karke verify karein tabhi content unlock hoga.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return

    # Agar user already verified hai tabhi ad step dikhega
    await send_ad_step_fixed(update, bot, user_id, is_next_part=False)


async def send_ad_step_fixed(update, bot: ExtBot, user_id, is_next_part=False):
    if user_id not in user_sessions:
        return
    
    keyboard = [
        [InlineKeyboardButton("📺 Watch Ad (30 Sec)", url=MONETAG_LINK or "https://google.com")],
        [InlineKeyboardButton("✅ Verify & Get Videos", callback_data="verify_batch")]
    ]
    
    if is_next_part:
        msg_text = "✨ अगला पार्ट तैयार है!\n\nइसी सीरीज़ के और वीडियो ke liye dubara verify karein.\nपहले **Watch Ad** link kholin, phir 30 second baad niche wale verify button par check lagayein."
    else:
        msg_text = "⚠️ **Ad Watch Verification Required!**\n\nVideos fetch karne ke liye niche wale **Watch Ad** par click karke 30s check karein, uske baad verification button confirm karein."
    
    try:
        chat_id = update.message.chat_id if update.message else update.callback_query.message.chat_id
        await bot.send_message(chat_id=chat_id, text=msg_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Error sending monetag menu interface layouts: {e}")


async def button_callback_fixed(update: Update, bot: ExtBot):
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in user_sessions:
        try:
            await bot.answer_callback_query(callback_query_id=query.id, text="❌ Session record reset. Please refresh content url via channel link.", show_alert=True)
        except Exception:
            pass
        return

    if query.data == "verify_batch":
        click_time = user_sessions[user_id].get('click_time', 0)
        
        # Timer strict validation tracker
        if click_time == 0:
            user_sessions[user_id]['click_time'] = time.time()
            try:
                await bot.answer_callback_query(
                    callback_query_id=query.id, 
                    text="⏳ Timer Locked! Pehle exact 30 seconds tak ad dekhein, uske baad is button ko dubara dabayein tabhi video copy hogi.", 
                    show_alert=True
                )
            except Exception:
                pass
            return
            
        gap = time.time() - click_time
        if gap < 30:
            try:
                await bot.answer_callback_query(callback_query_id=query.id, text=f"❌ Wait karein! Abhi bhi {int(30 - gap)}s bache huye hain.", show_alert=True)
            except Exception:
                pass
            return
        
        try:
            await bot.answer_callback_query(callback_query_id=query.id, text="✅ Video Verified!")
            await bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
        except Exception:
            pass
        
        data = user_sessions[user_id]
        start_idx = data['current_index']
        end_idx = start_idx + data['batch_size']
        current_batch = data['videos'][start_idx:end_idx]
        
        # Process forwarding task
        for msg_id in current_batch:
            try:
                await bot.copy_message(
                    chat_id=query.message.chat_id,
                    from_chat_id=data['channel'],
                    message_id=msg_id
                )
                await asyncio.sleep(0.5)
            except Exception as e:
                logging.error(f"Error transferring database records keys entries: {e}")

        # LOG FOR CHANNELS TRACK: Sirf video deliver hone ke baad notification release hoga
        if LOG_GROUP_ID and start_idx == 0:
            user = query.from_user
            first_name = user.first_name.replace("<", "&lt;").replace(">", "&gt;") if user.first_name else "User"
            username = f"@{user.username}" if user.username else "No Username"
            log_msg = (
                f"💰 <b>User Watched Ad & Got Video</b>\n\n"
                f"• <b>Name:</b> {first_name}\n"
                f"• <b>User ID:</b> <code>{user_id}</code>\n"
                f"• <b>Username:</b> {username}\n"
                f"• <b>Channel no.</b> {data['ch_num']}\n"
                f"   {data['video_link_str']}"
            )
            try:
                await bot.send_message(chat_id=LOG_GROUP_ID, text=log_msg, parse_mode="HTML", disable_web_page_preview=True)
            except Exception as e:
                logging.error(f"Group notification pipe mismatch: {e}")

        user_sessions[user_id]['current_index'] = end_idx
        user_sessions[user_id]['click_time'] = 0 # Reset state
        
        if end_idx < len(data['videos']):
            await send_ad_step_fixed(update, bot, user_id, is_next_part=True)
        else:
            await bot.send_message(chat_id=query.message.chat_id, text="🎉 **Sari videos successfully deliver ho chuki hain!**")
            if user_id in user_sessions: 
                del user_sessions[user_id]


# --- FLASK SERVER ROUTING PIPELINES ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Core Engines are Active!"

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
            logging.error(f"Global routing exception errors catch: {e}")
            return "OK", 200
            
    return "Bad Request", 400

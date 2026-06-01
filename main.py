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

# MongoDB Setup
client = MongoClient(MONGO_URI)
db = client['tg_bot_db']
users_collection = db['verified_users']

# TTL Index: Jo entries 8 ghante baad expire_at par aayengi, unhe MongoDB auto-delete nahi karega, 
# balki hum script se unka status unverified karenge ya TTL handle karenge. 
# Free tier ke liye best hai ki expire_at aate hi document delete ho jaye, naya aane par fir se unverified banega.
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
    
    # Sequence: 0 -> Arolinks, 1 -> Vplink, 2 -> Instantlinks
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
        logging.error(f"Shortener API Error: {e}")
    
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

    # Database query check
    user_db = users_collection.find_one({"_id": user_id})
    
    # FIX: Agar user DB me bilkul naya hai, to pehle use unverified status ke sath insert karo
    if not user_db:
        user_db = {
            "_id": user_id,
            "status": "unverified",
            "loop_count": 0
        }
        users_collection.insert_one(user_db)

    # Case 1: Direct start without arguments
    if len(parts) <= 1:
        await bot.send_message(chat_id=chat_id, text="👋 Welcome! Bot active hai. Kisi video link par click karke aayein.")
        return

    raw_arg = parts[1]

    # Case 2: User short link pass karke token ke saath wapas aaya hai
    if raw_arg.startswith("vrf_"):
        session = user_sessions.get(user_id)
        if session and session.get("expected_token") == raw_arg:
            current_loop = user_db.get("loop_count", 0)
            expire_time = datetime.utcnow() + timedelta(hours=8)
            
            # Ab status ko "verify" karo aur 8 ghante ka TTL expiry lagao
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
            await bot.send_message(chat_id=chat_id, text="✅ Verification Successful! Aapka access agle 8 ghante ke liye active ho gaya hai.")
            
            # Agar session me videos pending thi to direct monetag ad step par bhejo
            if "videos" in session and session["videos"]:
                await send_ad_step_fixed(update, bot, user_id, is_next_part=False)
            return
        else:
            await bot.send_message(chat_id=chat_id, text="❌ Invalid ya Expired verification link. Kripya naye link se koshish karein.")
            return

    # Case 3: Video parameters handling (e.g. 146_1 ya bulk)
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
            await bot.send_message(chat_id=chat_id, text="❌ Invalid Format.")
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
            await bot.send_message(chat_id=chat_id, text="❌ Invalid Numbers.")
            return
    else:
        await bot.send_message(chat_id=chat_id, text="❌ Invalid URL Parameters.")
        return

    if not target_ch:
        await bot.send_message(chat_id=chat_id, text="❌ Channel ID configuration missing.")
        return

    # Save details in temporary session memory
    user_sessions[user_id] = {
        "videos": video_list,
        "channel": target_ch,
        "batch_size": batch_size,
        "current_index": 0,
        "click_time": 0,
        "video_link_str": video_link_str,
        "ch_num": ch_num
    }

    # STRICT CHECK: Agar status "verify" nahi hai (yaani unverified hai ya 8 ghante baad entry delete ho chuki hai)
    if user_db.get("status") != "verify":
        token = generate_random_token()
        user_sessions[user_id]["expected_token"] = token
        
        status_msg = await bot.send_message(chat_id=chat_id, text="⏳ Generating your unique verification link...")
        short_link = get_short_link(user_id, bot_username, token)
        
        try:
            await bot.delete_message(chat_id=chat_id, message_id=status_msg.message_id)
        except Exception:
            pass
            
        keyboard = [[InlineKeyboardButton("🔗 Click Here to Verify (8 Hours)", url=short_link)]]
        await bot.send_message(
            chat_id=chat_id,
            text="⚠️ **Verification Required!**\n\nAapka 8-ghante ka access active nahi hai. Videos unlock karne ke liye niche diye gaye link ko open karke verify karein.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return

    # Agar user already successfully verified hai, to direct Monetag wale step par bhejo
    await send_ad_step_fixed(update, bot, user_id, is_next_part=False)


async def send_ad_step_fixed(update, bot: ExtBot, user_id, is_next_part=False):
    if user_id not in user_sessions:
        return
    
    keyboard = [
        [InlineKeyboardButton("📺 Watch Ad (30 Sec)", url=MONETAG_LINK or "https://google.com"),
         InlineKeyboardButton("✅ Verify & Get Videos", callback_data="verify_batch")]
    ]
    
    if is_next_part:
        msg_text = "✨ अगला पार्ट तैयार है!\n\nइसी सीरीज़ के और वीडियो के लिए वेरिफाई करें।\nपहले 'Watch Ad' बटन par click karein, phir 30 second baad niche wale button se verify karein."
    else:
        msg_text = "⚠️ **Ad Verification Required!**\n\nVideos unlock karne ke liye pehle **Watch Ad** button par click karke 30 second tak ad dekhein, phir niche diye gaye button se verify karein."
    
    try:
        chat_id = update.message.chat_id if update.message else update.callback_query.message.chat_id
        await bot.send_message(chat_id=chat_id, text=msg_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Error sending ad message: {e}")


async def button_callback_fixed(update: Update, bot: ExtBot):
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in user_sessions:
        try:
            await bot.answer_callback_query(callback_query_id=query.id, text="❌ Session expired. Dubara link par click karein.", show_alert=True)
        except Exception:
            pass
        return

    if query.data == "verify_batch":
        click_time = user_sessions[user_id].get('click_time', 0)
        
        # Strict Ad Click validation
        if click_time == 0:
            try:
                # Timer start kar rahe hain jab user bina click kiye verify dabadeta hai
                user_sessions[user_id]['click_time'] = time.time()
                await bot.answer_callback_query(
                    callback_query_id=query.id, 
                    text="⏳ Timer Started! Pehle 'Watch Ad' button par click karein aur 30 seconds tak ad dekhein, uske baad hi yeh button kaam karega.", 
                    show_alert=True
                )
            except Exception:
                pass
            return
            
        gap = time.time() - click_time
        if gap < 30:
            try:
                await bot.answer_callback_query(callback_query_id=query.id, text=f"❌ Ruhein! Abhi bhi {int(30 - gap)}s baaki hain.", show_alert=True)
            except Exception:
                pass
            return
        
        try:
            await bot.answer_callback_query(callback_query_id=query.id, text="✅ Verified!")
            await bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
        except Exception:
            pass
        
        data = user_sessions[user_id]
        start_idx = data['current_index']
        end_idx = start_idx + data['batch_size']
        current_batch = data['videos'][start_idx:end_idx]
        
        # Copying batch videos to user chat
        for msg_id in current_batch:
            try:
                await bot.copy_message(
                    chat_id=query.message.chat_id,
                    from_chat_id=data['channel'],
                    message_id=msg_id
                )
                await asyncio.sleep(0.5)
            except Exception as e:
                logging.error(f"Error copying video {msg_id}: {e}")

        # --- LOG TO GROUP ONLY AFTER VIDEO DELIVERY ---
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
                logging.error(f"Error sending log to group: {e}")

        user_sessions[user_id]['current_index'] = end_idx
        user_sessions[user_id]['click_time'] = 0 # Reset timer for next part calculation
        
        if end_idx < len(data['videos']):
            await send_ad_step_fixed(update, bot, user_id, is_next_part=True)
        else:
            await bot.send_message(chat_id=query.message.chat_id, text="🎉 **Sari videos complete ho gayi hain!**")
            if user_id in user_sessions: 
                del user_sessions[user_id]


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
                user_id = update.callback_query.from_user.id
                
                # Strict Ad Hack bypass handling
                if update.callback_query.data == "verify_batch" and user_id in user_sessions:
                    if user_sessions[user_id].get('click_time', 0) == 0:
                        user_sessions[user_id]['click_time'] = time.time()
                        asyncio.run(bot.answer_callback_query(
                            callback_query_id=update.callback_query.id, 
                            text="⏳ Timer Started! Pehle Ad dekhna jaruri hai. Ab se 30 seconds baad button dubara click karein.", 
                            show_alert=True
                        ))
                        return "OK", 200
                        
                asyncio.run(button_callback_fixed(update, bot))
                
            return "OK", 200
        except Exception as e:
            logging.error(f"Webhook Execution Error: {e}")
            return "OK", 200
            
    return "Invalid Request", 400

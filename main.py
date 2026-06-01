import logging
import os
import asyncio
import math
from datetime import datetime
from telegram import Update
from telegram.ext import ExtBot
from flask import Flask, request

# --- CONFIG & LOGGING ---
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("BOT_TOKEN")
LOG_GROUP_ID = os.getenv("LOG_GROUP_ID") 

CHANNELS = {
    "1": os.getenv("CH_1"),
    "2": os.getenv("CH_2"),
    "3": os.getenv("CH_3"),
    "4": os.getenv("CH_4"),
    "5": os.getenv("CH_5"),
}

CHANNEL_CHAT_IDS = {
    "1": "3952628014",
    "2": "3758252316",
    "3": "3736158308",
    "4": "3195006898",
    "5": "3307449853"
}

user_data = {}

# --- BOT LOGIC FUNCTIONS ---
async def start_with_text(update: Update, bot: ExtBot, text_message: str):
    if not update.message:
        return
    
    user = update.effective_user
    user_id = int(user.id)
    chat_id = update.message.chat_id
    
    parts = text_message.split()
    raw_arg = parts[1] if len(parts) > 1 else ""

    if not raw_arg:
        await bot.send_message(chat_id=chat_id, text="👋 Welcome! Kisi video link par click karke aayein.")
        return

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

        # 🛑 ERROR LOGGING TO LOG CHANNEL (If channel key is missing in Env)
        if not target_ch:
            error_msg = f"❌ **ENV ERROR:**\nUser `{user_id}` requested `CH_{ch_num}`, but `CH_{ch_num}` is **NOT SET** in Vercel Environment Variables!"
            try:
                await bot.send_message(chat_id=LOG_GROUP_ID, text=error_msg, parse_mode="Markdown")
            except: pass
            await bot.send_message(chat_id=chat_id, text="❌ Technical issue (Config Missing). Admin has been notified.")
            return

        if not str(target_ch).startswith("-100"):
            target_ch = f"-100{target_ch}"

        user_data[user_id] = {
            "videos": video_list,
            "channel": target_ch,
            "batch_size": batch_size,
            "current_index": 0,
            "ch_num": str(ch_num),
            "video_id": str(video_list[0])
        }

        asyncio.create_task(process_video_delivery(chat_id, bot, user_id, user))

async def process_video_delivery(chat_id, bot: ExtBot, user_id, user):
    if user_id not in user_data:
        return

    data = user_data[user_id]
    
    while data['current_index'] < len(data['videos']):
        start_idx = data['current_index']
        end_idx = start_idx + data['batch_size']
        current_batch = data['videos'][start_idx:end_idx]
        
        videos_sent_successfully = False
        for msg_id in current_batch:
            try:
                await bot.copy_message(chat_id=chat_id, from_chat_id=data['channel'], message_id=msg_id)
                videos_sent_successfully = True
                await asyncio.sleep(0.6)
            except Exception as telegram_error: 
                logging.error(f"Error copying message {msg_id}: {telegram_error}")
                
                # 🛑 CRITICAL ERROR LOGGING TO LOG CHANNEL
                # Agar video copy fail hoti hai, toh direct log channel par batayega kyun fail hua
                try:
                    err_message = (
                        f"❌ **VIDEO DELIVERY FAILED!**\n\n"
                        f"👤 **User:** {user.first_name} (`{user_id}`)\n"
                        f"📁 **Source Channel:** `{data['channel']}`\n"
                        f"🆔 **Target Message ID:** `{msg_id}`\n"
                        f"⚠️ **Exact Telegram Error:** `{str(telegram_error)}`"
                    )
                    await bot.send_message(chat_id=LOG_GROUP_ID, text=err_message, parse_mode="Markdown")
                except Exception as log_send_err:
                    logging.error(f"Could not send error log: {log_send_err}")

        if videos_sent_successfully and LOG_GROUP_ID:
            try:
                ch_num = data.get("ch_num", "")
                video_id = data.get("video_id", "")
                channel_chat_id = CHANNEL_CHAT_IDS.get(ch_num)
                direct_video_link = f"https://t.me/c/{channel_chat_id}/{video_id}" if channel_chat_id else "N/A"
                
                first_name = user.first_name or "User"
                username = f"@{user.username}" if user.username else "No Username"
                log_message = (
                    f"📤 **Video Received Successfully!**\n\n"
                    f"👤 **User:** {first_name}\n"
                    f"🆔 **ID:** `{user_id}`\n"
                    f"🌐 **Username:** {username}\n"
                    f"📦 **Batch:** {start_idx + 1} to {min(end_idx, len(data['videos']))}\n"
                    f"🔗 **Direct Link:** [Click Here]({direct_video_link})\n"
                    f"⏰ **Time:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
                )
                await bot.send_message(chat_id=LOG_GROUP_ID, text=log_message, parse_mode="Markdown", disable_web_page_preview=True)
            except Exception as log_err:
                logging.error(f"Log Channel Error: {log_err}")

        data['current_index'] = end_idx
        await asyncio.sleep(1)

    try:
        await bot.send_message(chat_id=chat_id, text="🎉 Saari videos complete ho gayi hain!")
    except:
        pass
        
    if user_id in user_data:
        del user_data[user_id]

# --- FLASK SERVER & WEBHOOK ---
app = Flask(__name__)

@app.route('/')
def home(): return "Bot is Active! Debug Mode ON."

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

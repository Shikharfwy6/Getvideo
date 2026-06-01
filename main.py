import logging
import os
import asyncio
import math
from datetime import datetime
from telegram import Update
from telegram.ext import ExtBot
from flask import Flask, request, Response

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

        # Log Channel configuration check
        if not target_ch:
            err_msg = f"❌ **ENV ERROR:**\nUser `{user_id}` requested `CH_{ch_num}`, but it's **NOT SET** in Vercel!"
            if LOG_GROUP_ID:
                await bot.send_message(chat_id=LOG_GROUP_ID, text=err_msg, parse_mode="Markdown")
            await bot.send_message(chat_id=chat_id, text="❌ Configuration Error. Admin notified.")
            return

        if not str(target_ch).startswith("-100"):
            target_ch = f"-100{target_ch}"

        # **Direct Synchronous Processing to force Vercel to stay alive**
        await process_video_delivery_sync(chat_id, bot, user_id, user, video_list, target_ch, batch_size, ch_num)

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
                await asyncio.sleep(0.8) # Anti-flood delay
            except Exception as telegram_error: 
                logging.error(f"Copy message failed: {telegram_error}")
                if LOG_GROUP_ID:
                    try:
                        err_message = (
                            f"❌ **VIDEO DELIVERY FAILED!**\n\n"
                            f"👤 **User:** {user.first_name} (`{user_id}`)\n"
                            f"📁 **Source Channel:** `{target_ch}`\n"
                            f"🆔 **Message ID:** `{msg_id}`\n"
                            f"⚠️ **Error:** `{str(telegram_error)}`"
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
        await asyncio.sleep(1)

    try:
        await bot.send_message(chat_id=chat_id, text="🎉 Saari videos complete ho gayi hain!")
    except: pass

# --- FLASK SERVER & WEBHOOK ---
app = Flask(__name__)

@app.route('/')
def home(): return "Bot is Active! Sync Mode ON."

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == "POST":
        update_json = request.get_json(force=True)
        
        # Streaming response framework jo Vercel server ko alive rakhega
        def generate():
            try:
                bot = ExtBot(token=TOKEN)
                update = Update.de_json(update_json, bot)
                
                if update.message and update.message.text:
                    if update.message.text.startswith('/start'):
                        # Run blocking task smoothly inside string generator
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(start_with_text(update, bot, update.message.text))
                        loop.close()
            except Exception as e:
                logging.error(f"Execution Error: {e}")
            yield "OK"

        return Response(generate(), mimetype="text/plain")
    return "Invalid Request", 400

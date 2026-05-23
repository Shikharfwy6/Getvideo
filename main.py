import logging
import os
import time
import asyncio
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
from flask import Flask, request

# --- CONFIG & LOGGING ---
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("BOT_TOKEN")
MONETAG_LINK = os.getenv("MONETAG_DIRECT_LINK")

# एनवायरनमेंट वेरिएबल्स को सुरक्षित तरीके से लोड करना
CHANNELS = {
    "1": os.getenv("CH_1"),
    "2": os.getenv("CH_2"),
    "3": os.getenv("CH_3"),
    "4": os.getenv("CH_4"),
    "5": os.getenv("CH_5"),
}

user_data = {}

# --- BOT LOGIC FUNCTIONS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    args = context.args
    user_id = update.effective_user.id
    
    if not args:
        return await update.message.reply_text("👋 Welcome! Bot active hai.")

    extracted_args = args[0].split('_') if len(args) == 1 and "_" in args[0] else args

    if len(extracted_args) == 2:
        try:
            file_id, ch_num = extracted_args
            video_list = [int(file_id)]
            target_ch = CHANNELS.get(str(ch_num))
            batch_size = 1
        except ValueError:
            return await update.message.reply_text("❌ Invalid Format.")
    
    elif len(extracted_args) == 4:
        try:
            start_id, end_id, ch_num, total_parts = map(int, extracted_args)
            video_list = list(range(start_id, end_id + 1))
            target_ch = CHANNELS.get(str(ch_num))
            
            total_videos = len(video_list)
            if total_parts <= 0:
                total_parts = 1
            batch_size = math.ceil(total_videos / total_parts)
            
        except ValueError:
            return await update.message.reply_text("❌ Invalid Numbers.")
    else:
        return await update.message.reply_text("❌ Invalid URL.")

    if not target_ch:
        return await update.message.reply_text(f"❌ Channel ID set nahi hai.")

    user_data[user_id] = {
        "videos": video_list,
        "channel": target_ch,
        "batch_size": batch_size,
        "current_index": 0,
        "click_time": 0
    }

    await send_ad_step(update, user_id, is_next_part=False)

async def send_ad_step(update, user_id, is_next_part=False):
    if user_id not in user_data:
        return
    user_data[user_id]['click_time'] = time.time()
    
    keyboard = [
        [InlineKeyboardButton("📺 Watch Ad (30 Sec)", url=MONETAG_LINK or "https://google.com")],
        [InlineKeyboardButton("✅ Verify & Get Videos", callback_data="verify_batch")]
    ]
    
    if is_next_part:
        msg_text = "✨ अगला पार्ट तैयार है!\n\nइसी सीरीज़ के और वीडियो के लिए वेरिफाई करें।\n30 सेकंड का विज्ञापन देखें और नीचे दिए गए बटन पर क्लिक करें।"
    else:
        msg_text = "⚠️ **Verification Required!**\n\nVideos unlock karne ke liye 30 second ad dekhein aur niche button par click karein."
    
    try:
        if update.message:
            await update.message.reply_text(msg_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            await update.callback_query.message.reply_text(msg_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Error sending message: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in user_data:
        return await query.answer("❌ Session expired.", show_alert=True)

    if query.data == "verify_batch":
        gap = time.time() - user_data[user_id]['click_time']
        
        if gap < 30:
            return await query.answer(f"❌ {int(30 - gap)}s baaki hain!", show_alert=True)
        
        await query.answer("✅ Verified!")
        try:
            await query.message.delete()
        except Exception:
            pass
        
        data = user_data[user_id]
        start_idx = data['current_index']
        end_idx = start_idx + data['batch_size']
        current_batch = data['videos'][start_idx:end_idx]
        
        for msg_id in current_batch:
            try:
                await context.bot.copy_message(
                    chat_id=query.message.chat_id,
                    from_chat_id=data['channel'],
                    message_id=msg_id
                )
                await asyncio.sleep(0.5)
            except Exception as e:
                logging.error(f"Copy message failed: {e}")
                await context.bot.send_message(chat_id=query.message.chat_id, text=f"❌ Error: Video {msg_id} nahi mila.")

        user_data[user_id]['current_index'] = end_idx
        
        if end_idx < len(data['videos']):
            await send_ad_step(update, user_id, is_next_part=True)
        else:
            await context.bot.send_message(chat_id=query.message.chat_id, text="🎉 **Sari videos complete ho gayi hain!**")
            if user_id in user_data: del user_data[user_id]

# --- FLASK SERVER & WEBHOOK ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Active!"

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == "POST":
        try:
            # टेलीग्राम ऐप को हर रिक्वेस्ट पर फ्रेश बिल्ड करना सर्वरलेस के लिए बेस्ट है
            tg_app = ApplicationBuilder().token(TOKEN).build()
            tg_app.add_handler(CommandHandler("start", start))
            tg_app.add_handler(CallbackQueryHandler(button_callback))
            
            update_json = request.get_json(force=True)
            update = Update.de_json(update_json, tg_app.bot)
            
            async def process():
                if not tg_app.initialized:
                    await tg_app.initialize()
                await tg_app.process_update(update)

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(process())
            loop.close()
            
            return "OK", 200
        except Exception as e:
            logging.error(f"CRITICAL ERROR in webhook: {e}")
            return "OK", 200  # यहाँ 200 भेजने से टेलीग्राम बार-बार फेल रिक्वेस्ट नहीं भेजेगा
            
    return "Invalid Request", 400

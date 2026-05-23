import logging
import os
import time
import asyncio
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, CallbackQueryHandler, CallbackContext, ExtBot
from flask import Flask, request

# --- CONFIG & LOGGING ---
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("BOT_TOKEN")
MONETAG_LINK = os.getenv("MONETAG_DIRECT_LINK")

CHANNELS = {
    "1": os.getenv("CH_1"),
    "2": os.getenv("CH_2"),
    "3": os.getenv("CH_3"),
    "4": os.getenv("CH_4"),
    "5": os.getenv("CH_5"),
}

user_data = {}

# --- BOT LOGIC FUNCTIONS ---
async def start(update: Update, context: CallbackContext):
    if not update.message:
        return
    
    args = context.args
    user_id = update.effective_user.id
    
    # अगर कोई आर्गुमेंट नहीं है (सिर्फ सीधा /start भेजा है)
    if not args or len(args) == 0:
        return await update.message.reply_text("👋 Welcome! Bot active hai.")

    # आर्गुमेंट्स को ठीक से निकालना
    extracted_args = args[0].split('_') if "_" in args[0] else args

    # Case 1: Single Video -> 249_1
    if len(extracted_args) == 2:
        try:
            file_id, ch_num = extracted_args
            video_list = [int(file_id)]
            target_ch = CHANNELS.get(str(ch_num))
            batch_size = 1
        except ValueError:
            return await update.message.reply_text("❌ Invalid Format.")
    
    # Case 2: Bulk Videos -> 249_251_2_1
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
        return await update.message.reply_text("❌ Invalid URL parameters.")

    if not target_ch:
        return await update.message.reply_text(f"❌ Channel ID set nahi hai.")

    # डेटा सेव करना
    user_data[user_id] = {
        "videos": video_list,
        "channel": target_ch,
        "batch_size": batch_size,
        "current_index": 0,
        "click_time": 0
    }

    # एडवर्टाइजमेंट स्टेप पर भेजें
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

async def button_callback(update: Update, context: CallbackContext):
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
            update_json = request.get_json(force=True)
            bot = ExtBot(token=TOKEN)
            update = Update.de_json(update_json, bot)
            context = CallbackContext.from_update(update, bot)
            
            if update.message and update.message.text:
                text = update.message.text
                if text.startswith('/start'):
                    # मजबूत और फुल-प्रूफ स्ट्रिंग स्प्लिट लॉजिक
                    parts = text.split()
                    if len(parts) > 1:
                        context._args = [parts[1]]  # यह आपके '249_251_2_1' को एकदम सही पकड़ेगा
                    else:
                        context._args = []
                        
                    asyncio.run(start(update, context))
                    
            elif update.callback_query:
                asyncio.run(button_callback(update, context))
                
            return "OK", 200
        except Exception as e:
            logging.error(f"Error in execution: {e}")
            return "OK", 200
            
    return "Invalid Request", 400

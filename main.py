import logging
import os
import time
import asyncio
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ExtBot
from flask import Flask, request

# --- CONFIG & LOGGING ---
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("BOT_TOKEN")
MONETAG_LINK = os.getenv("MONETAG_DIRECT_LINK")
LOG_GROUP_ID = os.getenv("LOG_GROUP_ID") 

CHANNELS = {
    "1": os.getenv("CH_1"),
    "2": os.getenv("CH_2"),
    "3": os.getenv("CH_3"),
    "4": os.getenv("CH_4"),
    "5": os.getenv("CH_5"),
}

user_data = {}

# --- BOT LOGIC FUNCTIONS ---
async def start_with_text(update: Update, bot: ExtBot, text_message: str):
    if not update.message:
        return
    
    user = update.effective_user
    user_id = user.id
    # HTML सेफ बनाने के लिए नाम को क्लीन कर रहे हैं
    first_name = user.first_name.replace("<", "&lt;").replace(">", "&gt;") if user.first_name else "User"
    username = f"@{user.username}" if user.username else "No Username"
    parts = text_message.split()
    
    # अगर कोई आर्गुमेंट नहीं है (सिर्फ सीधा /start भेजा है)
    if len(parts) <= 1:
        await bot.send_message(chat_id=update.message.chat_id, text="👋 Welcome! Bot active hai.")
        
        # ग्रुप में लॉग भेजना (बिना लिंक वाला स्टार्ट)
        if LOG_GROUP_ID:
            log_msg = (
                f"👤 <b>New User Started Bot (Direct)</b>\n\n"
                f"• <b>Name:</b> {first_name}\n"
                f"• <b>User ID:</b> <code>{user_id}</code>\n"
                f"• <b>Username:</b> {username}"
            )
            try:
                await bot.send_message(chat_id=LOG_GROUP_ID, text=log_msg, parse_mode="HTML")
            except Exception as e:
                logging.error(f"Error sending log to group: {e}")
        return

    # /start के आगे का हिस्सा निकालना (जैसे: 249_251_2_1)
    raw_arg = parts[1]
    extracted_args = raw_arg.split('_') if "_" in raw_arg else [raw_arg]

    # --- ग्रुप में लॉग भेजना (लिंक के साथ स्टार्ट) ---
    if LOG_GROUP_ID:
        log_msg = (
            f"🚀 <b>User Started Bot via Link</b>\n\n"
            f"• <b>Name:</b> {first_name}\n"
            f"• <b>User ID:</b> <code>{user_id}</code>\n"
            f"• <b>Username:</b> {username}\n"
            f"• <b>Start Parameter/Link:</b> <code>{raw_arg}</code>"
        )
        try:
            # HTML parse mode ज़्यादा सुरक्षित होता है क्रैश होने से बचाने के लिए
            await bot.send_message(chat_id=LOG_GROUP_ID, text=log_msg, parse_mode="HTML")
        except Exception as e:
            logging.error(f"Error sending log to group: {e}")

    # Case 1: Single Video -> 146_1
    if len(extracted_args) == 2:
        try:
            file_id, ch_num = extracted_args
            video_list = [int(file_id)]
            target_ch = CHANNELS.get(str(ch_num))
            batch_size = 1
        except ValueError:
            await bot.send_message(chat_id=update.message.chat_id, text="❌ Invalid Format.")
            return
    
    # Case 2: Bulk Videos -> 107_240_3_4
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
            await bot.send_message(chat_id=update.message.chat_id, text="❌ Invalid Numbers.")
            return
    else:
        await bot.send_message(chat_id=update.message.chat_id, text="❌ Invalid URL Parameters.")
        return

    if not target_ch:
        await bot.send_message(chat_id=update.message.chat_id, text="❌ Channel ID set nahi hai.")
        return

    # यूज़र का डेटा सेशन सेव करना
    user_data[user_id] = {
        "videos": video_list,
        "channel": target_ch,
        "batch_size": batch_size,
        "current_index": 0,
        "click_time": 0
    }

    # विज्ञापन वाला बटन भेजना
    await send_ad_step_fixed(update, bot, user_id, is_next_part=False)


async def send_ad_step_fixed(update, bot: ExtBot, user_id, is_next_part=False):
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
        chat_id = update.message.chat_id if update.message else update.callback_query.message.chat_id
        await bot.send_message(chat_id=chat_id, text=msg_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Error sending ad message: {e}")


async def button_callback_fixed(update: Update, bot: ExtBot):
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in user_data:
        try:
            await bot.answer_callback_query(callback_query_id=query.id, text="❌ Session expired.", show_alert=True)
        except Exception:
            pass
        return

    if query.data == "verify_batch":
        gap = time.time() - user_data[user_id]['click_time']
        
        if gap < 30:
            try:
                await bot.answer_callback_query(callback_query_id=query.id, text=f"❌ {int(30 - gap)}s baaki hain!", show_alert=True)
            except Exception:
                pass
            return
        
        try:
            await bot.answer_callback_query(callback_query_id=query.id, text="✅ Verified!")
            await bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
        except Exception:
            pass
        
        data = user_data[user_id]
        start_idx = data['current_index']
        end_idx = start_idx + data['batch_size']
        current_batch = data['videos'][start_idx:end_idx]
        
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
                await bot.send_message(chat_id=query.message.chat_id, text=f"❌ Error: Video {msg_id} nahi mila.")

        user_data[user_id]['current_index'] = end_idx
        
        if end_idx < len(data['videos']):
            await send_ad_step_fixed(update, bot, user_id, is_next_part=True)
        else:
            await bot.send_message(chat_id=query.message.chat_id, text="🎉 **Sari videos complete ho gayi hain!**")
            if user_id in user_data: 
                del user_data[user_id]


# --- FLASK SERVER & WEBHOOK FOR VERCEL ---
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

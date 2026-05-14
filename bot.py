import logging
import os
import time
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
from flask import Flask
from threading import Thread

# --- FLASK SERVER ---
app_flask = Flask('')
@app_flask.route('/')
def home(): return "Bot is Active!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host='0.0.0.0', port=port)

# --- CONFIG ---
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            start_id, end_id, ch_num, b_size = map(int, extracted_args)
            video_list = list(range(start_id, end_id + 1))
            target_ch = CHANNELS.get(str(ch_num))
            batch_size = b_size
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

    # Pehli baar normal message
    await send_ad_step(update, user_id, is_next_part=False)

async def send_ad_step(update, user_id, is_next_part=False):
    user_data[user_id]['click_time'] = time.time()
    
    keyboard = [
        [InlineKeyboardButton("📺 Watch Ad (30 Sec)", url=MONETAG_LINK)],
        [InlineKeyboardButton("✅ Verify & Get Videos", callback_data="verify_batch")]
    ]
    
    # Yaha change kiya hai: Agar agla part hai to alag message dikhega
    if is_next_part:
        msg_text = "✨ **Agla Part Taiyar Hai!🫦💦🍌👙**\n\n**Isi series ka aur video ka liya verify kara.🫦👙👠💦🍌👅💦👠👙🫦**\n30 second ad dekhein aur niche button par click karein."
    else:
        msg_text = "⚠️ **Verification Required!**\n\nVideos unlock karne ke liye 30 second ad dekhein aur niche button par click karein."
    
    if update.message:
        await update.message.reply_text(msg_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.callback_query.message.reply_text(msg_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

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
        await query.message.delete()
        
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
            except Exception:
                await context.bot.send_message(chat_id=query.message.chat_id, text=f"❌ Error: Video {msg_id} nahi mila.")

        user_data[user_id]['current_index'] = end_idx
        
        if end_idx < len(data['videos']):
            # Yaha next part ke liye true pass kar rahe hain
            await send_ad_step(update, user_id, is_next_part=True)
        else:
            await context.bot.send_message(chat_id=query.message.chat_id, text="🎉 **Sari videos complete ho gayi hain!**")
            if user_id in user_data: del user_data[user_id]

if __name__ == '__main__':
    Thread(target=run_flask).start()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.run_polling()

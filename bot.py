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

# Channels Mapping
CHANNELS = {
    "1": os.getenv("CH_1"),
    "2": os.getenv("CH_2"),
    "3": os.getenv("CH_3"),
    "4": os.getenv("CH_4"),
    "5": os.getenv("CH_5"),
}

# User state management
user_data = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    user_id = update.effective_user.id
    
    if not args:
        return await update.message.reply_text("👋 Welcome! Bot active hai.")

    # Case 1: Single Video (/start 146 1)
    if len(args) == 2:
        file_id, ch_num = args
        video_list = [int(file_id)]
        target_ch = CHANNELS.get(ch_num)
        batch_size = 1
    
    # Case 2: Bulk Videos (/start 146 150 2 2)
    elif len(args) == 4:
        start_id, end_id, ch_num, batch_size = map(int, args)
        video_list = list(range(start_id, end_id + 1))
        target_ch = CHANNELS.get(str(ch_num))
        batch_size = int(batch_size)
    
    else:
        return await update.message.reply_text("❌ Invalid URL Format.")

    if not target_ch:
        return await update.message.reply_text("❌ Channel ID nahi mili.")

    # Store state
    user_data[user_id] = {
        "videos": video_list,
        "channel": target_ch,
        "batch_size": batch_size,
        "current_index": 0,
        "click_time": 0
    }

    await send_ad_step(update, user_id)

async def send_ad_step(update, user_id):
    user_data[user_id]['click_time'] = time.time()
    
    keyboard = [
        [InlineKeyboardButton("📺 Watch Ad to Unlock Videos", url=MONETAG_LINK)],
        [InlineKeyboardButton("✅ Verify & Get Videos", callback_data="verify_batch")]
    ]
    
    msg_text = "⚠️ **Verification Required!**\n\nAglo videos ke liye 30 second ad dekhein aur Verify par click karein."
    
    if update.message:
        await update.message.reply_text(msg_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.callback_query.message.reply_text(msg_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in user_data:
        return await query.answer("❌ Session expired. Start again.", show_alert=True)

    if query.data == "verify_batch":
        gap = time.time() - user_data[user_id]['click_time']
        
        if gap < 30:
            return await query.answer(f"❌ {int(30 - gap)}s baaki hain!", show_alert=True)
        
        await query.answer("✅ Verified!")
        await query.message.delete()
        
        # Process Batch
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
                await asyncio.sleep(0.5) # Flood protection
            except Exception:
                await context.bot.send_message(chat_id=query.message.chat_id, text=f"❌ Video {msg_id} nahi mila.")

        # Update index
        user_data[user_id]['current_index'] = end_idx
        
        # Check if more videos left
        if end_idx < len(data['videos']):
            await send_ad_step(update, user_id)
        else:
            await context.bot.send_message(chat_id=query.message.chat_id, text="✅ **Saare videos complete ho gaye!**")
            del user_data[user_id]

if __name__ == '__main__':
    Thread(target=run_flask).start()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    print("🚀 Advanced Multi-Channel Bot Live...")
    app.run_polling()

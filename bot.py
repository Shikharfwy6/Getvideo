import logging
import os
import time
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
CHANNEL_ID = os.getenv("CHANNEL_ID")
MONETAG_LINK = os.getenv("MONETAG_DIRECT_LINK")

# User clicking time store karne ke liye
user_clicks = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        file_id = context.args[0]
        user_id = update.effective_user.id
        
        # User ko pehle ad dikhana hai, video nahi dena
        keyboard = [
            [InlineKeyboardButton("📺 Watch Ad (30 Sec)", url=MONETAG_LINK)],
            [InlineKeyboardButton("✅ Verify & Get Video", callback_data=f"verify_{file_id}")]
        ]
        
        # Click karne ka time note kar lo jab user /start par aaya
        user_clicks[user_id] = time.time()
        
        await update.message.reply_text(
            "⚠️ **Video Ready Hai!**\n\nLekin pehle aapko upar waale link par click karke **30 second** tak ad dekhna hoga.\nUske baad 'Verify' button par click karein.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("👋 Welcome! Daily surprise videos ke liye description check karein.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if data.startswith("verify_"):
        file_id = data.split("_")[1]
        start_time = user_clicks.get(user_id, 0)
        current_time = time.time()
        
        # Time gap calculate karein
        gap = current_time - start_time

        if gap < 30:
            remaining = int(30 - gap)
            await query.answer(f"❌ Abhi {remaining} second baaki hain! Ad poora dekhein.", show_alert=True)
        else:
            await query.answer("✅ Verification Successful!")
            await query.message.delete() # Purana message hata do
            
            # Ab video deliver karo
            try:
                await context.bot.copy_message(
                    chat_id=query.message.chat_id,
                    from_chat_id=int(CHANNEL_ID),
                    message_id=int(file_id),
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Next Video Ad", url=MONETAG_LINK)]])
                )
            except Exception as e:
                await context.bot.send_message(chat_id=query.message.chat_id, text="❌ Error: File nahi mil saki.")

if __name__ == '__main__':
    Thread(target=run_flask).start()
    
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    print("🚀 Verification Bot Live...")
    app.run_polling()

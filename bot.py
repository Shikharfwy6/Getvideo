import logging
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- LOGGING SETUP ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- CONFIGURATION (Environment Variables) ---
# Render par "Environment Variables" section mein ye names add karein
TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        file_id = context.args[0]
        
        if not CHANNEL_ID:
            await update.message.reply_text("❌ Configuration Error: CHANNEL_ID environment variable set nahi hai.")
            return

        try:
            # Channel se message copy karke user ko bhejna
            await context.bot.copy_message(
                chat_id=update.effective_chat.id,
                from_chat_id=int(CHANNEL_ID), # String ko integer mein convert karna zaroori hai
                message_id=int(file_id)
            )
        except Exception as e:
            logging.error(f"Error copying message: {e}")
            await update.message.reply_text("❌ File nahi mili ya Bot channel mein admin nahi hai.")
    else:
        await update.message.reply_text(
            "👋 Welcome!\n\n"
            "Main ek File Store bot hoon. Link par click karke apni file download karein."
        )

if __name__ == '__main__':
    if not TOKEN:
        print("❌ ERROR: BOT_TOKEN nahi mila! Environment variable check karein.")
        exit(1)

    app = ApplicationBuilder().token(TOKEN).build()
    
    # Sirf Start handler rakha hai kyunki setchannel ki ab zaroorat nahi
    app.add_handler(CommandHandler("start", start))

    print("🚀 Bot is running...")
    # Render ke liye polling sahi hai, lekin agar bot band ho jaye to Webhook use karna padta hai
    app.run_polling()

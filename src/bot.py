"""Phidias Telegram bot v0.1 — photo in, STL out. Payment layer comes next."""
import os, subprocess, logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, MessageHandler, CallbackQueryHandler,
                          CommandHandler, ContextTypes, filters)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
logging.basicConfig(level=logging.INFO)      # prints activity to the terminal

os.makedirs("input", exist_ok=True)
os.makedirs("output", exist_ok=True)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "I am Phidias. Send me a photograph — a flower, a pattern, a carving — "
        "and I will return a 3D-printable relief of it.")

async def got_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]                     # largest size Telegram offers
    f = await photo.get_file()
    path = f"input/tg_{update.message.from_user.id}_{photo.file_unique_id}.jpg"
    await f.download_to_drive(path)
    ctx.user_data["image_path"] = path                   # remember it for the button press
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Photo of a 3D object", callback_data="depth"),
        InlineKeyboardButton("Flat artwork/pattern", callback_data="luminance_inv"),
    ]])
    await update.message.reply_text("What am I looking at?", reply_markup=kb)

async def mode_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    path = ctx.user_data.get("image_path")
    if not path:
        await q.edit_message_text("Please send the photo again.")
        return
    mode = q.data                                         # "depth" or "luminance_inv"
    await q.edit_message_text("Sculpting... this takes under a minute.")
    cmd = ["python", "src/relief2.py", path, "--mode",
           "luminance" if mode == "luminance_inv" else mode]
    if mode == "luminance_inv":
        cmd.append("--invert")
    r = subprocess.run(cmd, capture_output=True, text=True)   # run the pipeline
    if r.returncode != 0:
        logging.error(r.stderr)
        await q.edit_message_text("Something went wrong with that image. Try another?")
        return
    name = os.path.splitext(os.path.basename(path))[0]
    stl = f"output/{name}_{'luminance_inv' if mode=='luminance_inv' else mode}.stl".replace("luminance_inv", "luminance_inv")
    # relief2.py names files as {name}_{mode}[_inv].stl — reconstruct:
    stl = f"output/{name}_luminance_inv.stl" if mode == "luminance_inv" else f"output/{name}_depth.stl"
    if not os.path.exists(stl):
        await q.edit_message_text("Generation finished but file missing — tell Ram.")
        return
    await q.edit_message_text("Done. Your file:")
    with open(stl, "rb") as fh:
        await ctx.bot.send_document(chat_id=q.message.chat_id, document=fh,
                                    filename=os.path.basename(stl))

app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.PHOTO, got_photo))
app.add_handler(CallbackQueryHandler(mode_chosen))
print("Phidias bot running. Ctrl+C to stop.")
app.run_polling()

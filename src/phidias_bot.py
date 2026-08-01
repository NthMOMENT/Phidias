"""Phidias v1.2 — integrated agent: Telegram bot + payment monitor + pipeline worker + cNFT receipt.
Photo in -> order -> USDC payment on Solana devnet -> STL out -> cNFT receipt minted. No human in the loop.
Run: python src/phidias_bot.py  (inside tmux)"""
import asyncio, hashlib, json, os, random, subprocess, logging, time
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Finalized
from spl.token.instructions import get_associated_token_address
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, MessageHandler, CallbackQueryHandler,
                          CommandHandler, ContextTypes, filters)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
RPC = os.getenv("SOLANA_RPC", "https://api.devnet.solana.com")
USDC_MINT = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"
ORDERS_FILE = "orders.json"
POLL_SECONDS = 10
ORDER_TIMEOUT = 30 * 60
PRICES = {"depth": 1.0, "luminance_inv": 1.0}
BASE_DIR = "/home/phidias/phidias"

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler("phidias.log"), logging.StreamHandler()])
log = logging.getLogger("phidias")

kp = Keypair.from_base58_string(open(".wallet_secret").read().strip())
ME = kp.pubkey()
ATA = get_associated_token_address(ME, Pubkey.from_string(USDC_MINT))
os.makedirs("input", exist_ok=True)
os.makedirs("output", exist_ok=True)

# ---------------- order book ----------------
def load_orders():
    return json.load(open(ORDERS_FILE)) if os.path.exists(ORDERS_FILE) else {}

def save_orders(o):
    json.dump(o, open(ORDERS_FILE, "w"), indent=2)

def new_order(chat_id, image_path, mode):
    orders = load_orders()
    memo = f"PHD-{random.randint(1000, 9999)}"
    while memo in orders:
        memo = f"PHD-{random.randint(1000, 9999)}"
    open_amts = {od["amount"] for od in orders.values()
                 if od["status"] == "awaiting_payment"}
    while True:
        amount = round(PRICES[mode] + random.randint(1, 99) / 1000, 3)
        if amount not in open_amts:
            break
    orders[memo] = {"amount": amount, "status": "awaiting_payment",
                    "created": time.time(), "chat_id": chat_id,
                    "image": image_path, "mode": mode}
    save_orders(orders)
    return memo, amount

# ---------------- telegram handlers ----------------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "I am Phidias, an autonomous sculptor. Send me a photograph — a flower, "
        "a pattern, a carving — and I will return a 3D-printable relief. "
        "Payment in USDC on Solana devnet.\n\n"
        "Commands:\n/start — show this message\n/cancel — cancel your open order")

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    orders = load_orders()
    cancelled = []
    for m, od in orders.items():
        if od.get("chat_id") == chat_id and od["status"] == "awaiting_payment":
            od["status"] = "cancelled"
            cancelled.append(m)
    if cancelled:
        save_orders(orders)
        log.info(f"cancelled orders: {', '.join(cancelled)} by chat {chat_id}")
        await update.message.reply_text(
            f"Order {', '.join(cancelled)} cancelled. "
            f"Send a new photo whenever you're ready.")
    else:
        await update.message.reply_text("No open orders to cancel.")

async def got_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    f = await photo.get_file()
    path = f"input/tg_{update.message.from_user.id}_{photo.file_unique_id}.jpg"
    await f.download_to_drive(path)
    ctx.user_data["image_path"] = path
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
    memo, amount = new_order(q.message.chat_id, path, q.data)
    log.info(f"order {memo} created: {amount} USDC, mode={q.data}")
    await q.edit_message_text(
        f"Order {memo}\n"
        f"Price: exactly {amount} USDC (Solana devnet)\n"
        f"Pay to:\n{ME}\n\n"
        f"Send the EXACT amount — that's how I match your payment. "
        f"If your wallet supports memos, add: {memo}\n"
        f"Order expires in 30 minutes. I start sculpting the moment payment lands.\n\n"
        f"To cancel: /cancel")

# ---------------- payment scan ----------------
async def scan_once(client, seen):
    sigs = (await client.get_signatures_for_address(ATA, limit=20)).value
    found = []
    for s in sigs:
        sig = str(s.signature)
        if sig in seen or s.err is not None:
            continue
        seen.add(sig)
        tx = (await client.get_transaction(
            s.signature, max_supported_transaction_version=0)).value
        if tx is None:
            continue
        meta = tx.transaction.meta
        memo = None
        for lg in (meta.log_messages or []):
            if "Memo" in lg and '"' in lg:
                memo = lg.split('"')[1]
        pre = {b.account_index: b for b in (meta.pre_token_balances or [])}
        recv = 0.0
        for b in (meta.post_token_balances or []):
            if str(b.mint) == USDC_MINT and str(b.owner) == str(ME):
                before = pre.get(b.account_index)
                b0 = float(before.ui_token_amount.ui_amount or 0) if before else 0.0
                recv = float(b.ui_token_amount.ui_amount or 0) - b0
        if recv > 0:
            found.append((memo, recv, sig))
    return found

def match_order(orders, memo, amount):
    o = orders.get(memo)
    if o and o["status"] == "awaiting_payment" and amount >= o["amount"]:
        return memo
    for m, od in orders.items():
        if od["status"] == "awaiting_payment" and abs(amount - od["amount"]) < 0.0001:
            return m
    return None

# ---------------- cNFT receipt ----------------
async def mint_receipt(order_id, file_hash, chat_id):
    r = await asyncio.to_thread(
        subprocess.run,
        ["node", "mint/mint_receipt.mjs", order_id, file_hash, str(chat_id)],
        capture_output=True, text=True, cwd=BASE_DIR)
    if "RECEIPT_OK" in r.stdout:
        log.info(f"receipt minted for {order_id} hash={file_hash[:16]}...")
        return True
    else:
        log.error(f"receipt failed for {order_id}: {r.stderr[-300:]}")
        return False

# ---------------- background loops ----------------
async def payment_loop(app):
    seen = set()
    async with AsyncClient(RPC, commitment=Finalized) as client:
        boot = (await client.get_signatures_for_address(ATA, limit=50)).value
        for s in boot:
            seen.add(str(s.signature))
        log.info(f"payment loop live, ignoring {len(boot)} historical txs")
        while True:
            try:
                for memo, amount, sig in await scan_once(client, seen):
                    orders = load_orders()
                    matched = match_order(orders, memo, amount)
                    if matched:
                        orders[matched]["status"] = "paid"
                        orders[matched]["tx"] = sig
                        save_orders(orders)
                        log.info(f"PAID {matched} {amount} USDC {sig[:16]}")
                        await app.bot.send_message(orders[matched]["chat_id"],
                            f"Payment received for {matched}. Sculpting now...")
                    else:
                        log.info(f"unmatched payment {amount} USDC memo={memo}")
                orders = load_orders(); changed = False
                for m, od in orders.items():
                    if od["status"] == "awaiting_payment" and time.time() - od["created"] > ORDER_TIMEOUT:
                        od["status"] = "expired"; changed = True
                        log.info(f"order {m} expired")
                if changed:
                    save_orders(orders)
            except Exception as e:
                log.error(f"payment loop error: {e}")
                await asyncio.sleep(30)
            await asyncio.sleep(POLL_SECONDS)

async def worker_loop(app):
    while True:
        try:
            orders = load_orders()
            for m, od in orders.items():
                if od["status"] != "paid":
                    continue
                od["status"] = "processing"; save_orders(orders)
                log.info(f"processing {m}")
                mode = od["mode"]
                cmd = [f"{BASE_DIR}/venv/bin/python", "src/relief2.py", od["image"],
                       "--mode", "luminance" if mode == "luminance_inv" else mode]
                if mode == "luminance_inv":
                    cmd.append("--invert")
                r = await asyncio.to_thread(
                    subprocess.run, cmd, capture_output=True, text=True)
                name = os.path.splitext(os.path.basename(od["image"]))[0]
                stl = f"output/{name}_luminance_inv.stl" if mode == "luminance_inv" \
                      else f"output/{name}_depth.stl"
                orders = load_orders()
                if r.returncode != 0 or not os.path.exists(stl):
                    orders[m]["status"] = "failed"; save_orders(orders)
                    log.error(f"{m} pipeline failed: {r.stderr[-500:]}")
                    await app.bot.send_message(od["chat_id"],
                        f"Order {m}: something went wrong with that image. "
                        f"Please try again.")
                    continue
                # deliver STL
                with open(stl, "rb") as fh:
                    await app.bot.send_document(od["chat_id"], fh,
                        filename=os.path.basename(stl),
                        caption=f"Order {m} complete. Print-ready STL, watertight verified.")
                orders[m]["status"] = "delivered"; save_orders(orders)
                log.info(f"delivered {m}")
                # mint cNFT receipt
                file_hash = hashlib.sha256(open(stl, "rb").read()).hexdigest()
                ok = await mint_receipt(m, file_hash, od["chat_id"])
                if ok:
                    await app.bot.send_message(od["chat_id"],
                        f"Receipt minted on Solana.\n"
                        f"File hash: {file_hash[:32]}...\n"
                        f"Proof that this exact file was delivered for order {m}.")
        except Exception as e:
            log.error(f"worker loop error: {e}")
        await asyncio.sleep(5)

# ---------------- main ----------------
async def post_init(app):
    asyncio.create_task(payment_loop(app))
    asyncio.create_task(worker_loop(app))

app = Application.builder().token(TOKEN).post_init(post_init).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("cancel", cancel))
app.add_handler(MessageHandler(filters.PHOTO, got_photo))
app.add_handler(CallbackQueryHandler(mode_chosen))
log.info("Phidias v1.2 starting")
app.run_polling()

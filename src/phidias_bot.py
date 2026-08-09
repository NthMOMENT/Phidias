"""Phidias v1.3 — autonomous relief sculptor agent.
Additions over v1.2:
- Background removal (rembg) wired into pipeline preprocessing
- Image size guard (resize to max 1500px before processing)
- Shared merkle tree (created once at startup, reused for all receipts)
- Treasury sweep automation (every 6 hours if balance > 5 USDC)
- /status command
- /history command
- Claude API intent parsing (suggests depth vs luminance from image)
"""
import asyncio, base64, hashlib, json, os, random, subprocess, logging, time
from pathlib import Path
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Finalized
from spl.token.instructions import get_associated_token_address
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, MessageHandler, CallbackQueryHandler,
                          CommandHandler, ContextTypes, filters)
import httpx
from PIL import Image
import io

load_dotenv()
TOKEN        = os.getenv("TELEGRAM_TOKEN")
RPC          = os.getenv("SOLANA_RPC", "https://api.devnet.solana.com")
CLAUDE_KEY   = os.getenv("ANTHROPIC_API_KEY")
USDC_MINT    = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"
ORDERS_FILE  = "orders.json"
TREE_FILE    = "merkle_tree.txt"
POLL_SECONDS = 10
ORDER_TIMEOUT        = 30 * 60
TREASURY_SWEEP_HOURS = 6
TREASURY_THRESHOLD   = 5.0
TREASURY_ADDRESS     = os.getenv("TREASURY_ADDRESS", "")
PRICES       = {"depth": 1.0, "luminance_inv": 1.0}
BASE_DIR     = "/home/phidias/phidias"
MAX_IMAGE_PX = 1500

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler("phidias.log"), logging.StreamHandler()])
log = logging.getLogger("phidias")

kp  = Keypair.from_base58_string(open(".wallet_secret").read().strip())
ME  = kp.pubkey()
ATA = get_associated_token_address(ME, Pubkey.from_string(USDC_MINT))
os.makedirs("input",  exist_ok=True)
os.makedirs("output", exist_ok=True)

# ── shared merkle tree ────────────────────────────────────────────────────────
SHARED_TREE = None

async def ensure_merkle_tree():
    global SHARED_TREE
    if os.path.exists(TREE_FILE):
        SHARED_TREE = open(TREE_FILE).read().strip()
        log.info(f"loaded existing merkle tree: {SHARED_TREE}")
        return
    log.info("creating shared merkle tree (one-time setup ~30s)...")
    r = await asyncio.to_thread(
        subprocess.run,
        ["node", "mint/create_tree.mjs"],
        capture_output=True, text=True, cwd=BASE_DIR)
    for line in r.stdout.splitlines():
        if line.startswith("TREE:"):
            SHARED_TREE = line.split("TREE:")[1].strip()
            open(TREE_FILE, "w").write(SHARED_TREE)
            log.info(f"shared merkle tree created: {SHARED_TREE}")
            return
    log.error(f"tree creation failed: {r.stderr[-300:]}")

# ── order book ────────────────────────────────────────────────────────────────
def load_orders():
    return json.load(open(ORDERS_FILE)) if os.path.exists(ORDERS_FILE) else {}

def save_orders(o):
    json.dump(o, open(ORDERS_FILE, "w"), indent=2)

def new_order(chat_id, image_path, mode):
    orders = load_orders()
    memo   = f"PHD-{random.randint(1000, 9999)}"
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

def user_orders(chat_id):
    orders = load_orders()
    return {m: od for m, od in orders.items() if od.get("chat_id") == chat_id}

# ── image preprocessing ───────────────────────────────────────────────────────
def preprocess_image(src_path: str) -> str:
    img = Image.open(src_path).convert("RGBA")
    w, h = img.size
    if max(w, h) > MAX_IMAGE_PX:
        scale = MAX_IMAGE_PX / max(w, h)
        img   = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        log.info(f"resized {w}x{h} → {img.size}")
    try:
        from rembg import remove
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        result    = remove(img_bytes.getvalue())
        img       = Image.open(io.BytesIO(result)).convert("RGBA")
        bg        = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img       = bg.convert("RGB")
        log.info("background removed")
    except Exception as e:
        log.warning(f"rembg failed ({e}), using original")
        img = img.convert("RGB")
    out = src_path.replace(".jpg", "_proc.png").replace(".jpeg", "_proc.png")
    if not out.endswith(".png"):
        out += "_proc.png"
    img.save(out)
    return out

# ── Claude intent parsing ─────────────────────────────────────────────────────
async def claude_suggest_mode(image_path: str) -> tuple[str, str]:
    if not CLAUDE_KEY:
        return "depth", "default"
    try:
        img_bytes = open(image_path, "rb").read()
        b64       = base64.standard_b64encode(img_bytes).decode()
        ext       = Path(image_path).suffix.lower().replace(".", "")
        media     = f"image/{'jpeg' if ext in ('jpg','jpeg') else 'png'}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": CLAUDE_KEY,
                         "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": "claude-haiku-4-5",
                      "max_tokens": 100,
                      "system": [{"type": "text",
                                  "text": "You choose a 3D relief processing mode from an image. "
                                          "Reply with exactly: MODE: depth OR MODE: luminance_inv\n"
                                          "depth = physically 3D subjects (flowers, objects, carvings, jewellery).\n"
                                          "luminance_inv = flat artwork, logos, drawings, patterns, text.\n"
                                          "Then: REASON: one short sentence.",
                                  "cache_control": {"type": "ephemeral"}}],
                      "messages": [{"role": "user", "content": [
                          {"type": "image", "source": {
                              "type": "base64", "media_type": media, "data": b64}},
                          {"type": "text", "text": "Which mode for this image?"}]}]})
        text   = resp.json()["content"][0]["text"]
        lines  = text.strip().splitlines()
        mode   = "depth"
        reason = "physical subject detected"
        for line in lines:
            if line.startswith("MODE:"):
                m = line.split("MODE:")[1].strip()
                if m in ("depth", "luminance_inv"):
                    mode = m
            if line.startswith("REASON:"):
                reason = line.split("REASON:")[1].strip()
        log.info(f"Claude mode: {mode} — {reason}")
        return mode, reason
    except Exception as e:
        log.warning(f"Claude intent parsing failed ({e}), defaulting to depth")
        return "depth", "default"

# ── telegram handlers ─────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "I am Phidias, an autonomous sculptor.\n\n"
        "Send me a photograph — a flower, a leaf, a carved pattern, flat artwork — "
        "and I will return a 3D-printable relief file. "
        "Payment in USDC on Solana devnet.\n\n"
        "Commands:\n"
        "/start — this message\n"
        "/status — check your current order\n"
        "/history — your past orders\n"
        "/cancel — cancel your open order")

async def status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    orders  = user_orders(chat_id)
    active  = {m: od for m, od in orders.items()
               if od["status"] not in ("delivered", "cancelled", "expired", "failed")}
    if not active:
        await update.message.reply_text("No active orders. Send a photo to start.")
        return
    lines = []
    for m, od in active.items():
        age = int((time.time() - od["created"]) / 60)
        lines.append(f"• {m} — {od['status']} — {age}m ago — {od['amount']} USDC")
    await update.message.reply_text("Your active orders:\n" + "\n".join(lines))

async def history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    orders  = user_orders(chat_id)
    if not orders:
        await update.message.reply_text("No order history found.")
        return
    lines = []
    for m, od in sorted(orders.items(),
                        key=lambda x: x[1].get("created", 0), reverse=True)[:10]:
        lines.append(f"• {m} — {od['status']} — {od['amount']} USDC")
    await update.message.reply_text("Your last orders:\n" + "\n".join(lines))

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id   = update.message.chat_id
    orders    = load_orders()
    cancelled = []
    for m, od in orders.items():
        if od.get("chat_id") == chat_id and od["status"] == "awaiting_payment":
            od["status"] = "cancelled"
            cancelled.append(m)
    if cancelled:
        save_orders(orders)
        log.info(f"cancelled: {', '.join(cancelled)}")
        await update.message.reply_text(
            f"Order {', '.join(cancelled)} cancelled. Send a new photo whenever you're ready.")
    else:
        await update.message.reply_text("No open orders to cancel.")

async def got_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    f     = await photo.get_file()
    path  = f"input/tg_{update.message.from_user.id}_{photo.file_unique_id}.jpg"
    await f.download_to_drive(path)
    await update.message.reply_text("Analysing your image...")
    mode, reason = await claude_suggest_mode(path)
    ctx.user_data["image_path"] = path
    mode_label  = "Photo of a 3D object" if mode == "depth" else "Flat artwork/pattern"
    other_mode  = "luminance_inv" if mode == "depth" else "depth"
    other_label = "Flat artwork/pattern" if mode == "depth" else "Photo of a 3D object"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"✓ {mode_label} (suggested)", callback_data=mode),
        InlineKeyboardButton(other_label, callback_data=other_mode),
    ]])
    await update.message.reply_text(
        f"I see: {reason}\nSuggested mode: {mode_label}.\nConfirm or choose differently:",
        reply_markup=kb)

async def mode_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
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
        f"To cancel: /cancel | To check status: /status")

# ── payment scan ──────────────────────────────────────────────────────────────
async def scan_once(client, seen):
    sigs  = (await client.get_signatures_for_address(ATA, limit=20)).value
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
        pre  = {b.account_index: b for b in (meta.pre_token_balances or [])}
        recv = 0.0
        for b in (meta.post_token_balances or []):
            if str(b.mint) == USDC_MINT and str(b.owner) == str(ME):
                before = pre.get(b.account_index)
                b0     = float(before.ui_token_amount.ui_amount or 0) if before else 0.0
                recv   = float(b.ui_token_amount.ui_amount or 0) - b0
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

# ── cNFT receipt ──────────────────────────────────────────────────────────────
async def mint_receipt(order_id, file_hash, chat_id):
    if not SHARED_TREE:
        log.error("no shared merkle tree available")
        return False
    r = await asyncio.to_thread(
        subprocess.run,
        ["node", "mint/mint_receipt.mjs", order_id, file_hash,
         str(chat_id), SHARED_TREE],
        capture_output=True, text=True, cwd=BASE_DIR)
    if "RECEIPT_OK" in r.stdout:
        log.info(f"receipt minted for {order_id} hash={file_hash[:16]}...")
        return True
    log.error(f"receipt failed for {order_id}: {r.stderr[-300:]}")
    return False

# ── treasury sweep ────────────────────────────────────────────────────────────
async def treasury_sweep(client):
    if not TREASURY_ADDRESS:
        return
    try:
        from solana.rpc.types import TokenAccountOpts
        resp = await client.get_token_accounts_by_owner_json_parsed(
            ME, TokenAccountOpts(mint=Pubkey.from_string(USDC_MINT)))
        if not resp.value:
            return
        bal = float(resp.value[0].account.data.parsed
                    ["info"]["tokenAmount"]["uiAmount"] or 0)
        if bal <= TREASURY_THRESHOLD:
            log.info(f"sweep skipped — balance {bal} USDC ≤ threshold {TREASURY_THRESHOLD}")
            return
        sweep_amt = round(bal - 1.0, 3)
        log.info(f"sweeping {sweep_amt} USDC to treasury {TREASURY_ADDRESS}")
        r = await asyncio.to_thread(
            subprocess.run,
            [f"{BASE_DIR}/venv/bin/python", "src/send_usdc.py",
             TREASURY_ADDRESS, str(sweep_amt)],
            capture_output=True, text=True, cwd=BASE_DIR)
        if r.returncode == 0:
            log.info(f"sweep complete: {sweep_amt} USDC → {TREASURY_ADDRESS}")
        else:
            log.error(f"sweep failed: {r.stderr[-200:]}")
    except Exception as e:
        log.error(f"treasury sweep error: {e}")

# ── background loops ──────────────────────────────────────────────────────────
async def payment_loop(app):
    seen       = set()
    last_sweep = time.time()
    async with AsyncClient(RPC, commitment=Finalized) as client:
        boot = (await client.get_signatures_for_address(ATA, limit=50)).value
        for s in boot:
            seen.add(str(s.signature))
        log.info(f"payment loop live, ignoring {len(boot)} historical txs")
        while True:
            try:
                for memo, amount, sig in await scan_once(client, seen):
                    orders  = load_orders()
                    matched = match_order(orders, memo, amount)
                    if matched:
                        orders[matched]["status"] = "paid"
                        orders[matched]["tx"]     = sig
                        save_orders(orders)
                        log.info(f"PAID {matched} {amount} USDC {sig[:16]}")
                        await app.bot.send_message(orders[matched]["chat_id"],
                            f"Payment received for {matched}. Sculpting now...")
                    else:
                        log.info(f"unmatched payment {amount} USDC memo={memo}")
                orders  = load_orders(); changed = False
                for m, od in orders.items():
                    if (od["status"] == "awaiting_payment"
                            and time.time() - od["created"] > ORDER_TIMEOUT):
                        od["status"] = "expired"; changed = True
                        log.info(f"order {m} expired")
                if changed:
                    save_orders(orders)
                if time.time() - last_sweep > TREASURY_SWEEP_HOURS * 3600:
                    await treasury_sweep(client)
                    last_sweep = time.time()
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
                try:
                    proc_image = await asyncio.to_thread(preprocess_image, od["image"])
                except Exception as e:
                    log.warning(f"preprocessing failed ({e}), using original")
                    proc_image = od["image"]
                cmd = [f"{BASE_DIR}/venv/bin/python", "src/relief2.py", proc_image,
                       "--mode", "luminance" if mode == "luminance_inv" else mode]
                if mode == "luminance_inv":
                    cmd.append("--invert")
                r = await asyncio.to_thread(
                    subprocess.run, cmd, capture_output=True, text=True)
                name = os.path.splitext(os.path.basename(proc_image))[0]
                stl  = (f"output/{name}_luminance_inv.stl" if mode == "luminance_inv"
                        else f"output/{name}_depth.stl")
                orders = load_orders()
                if r.returncode != 0 or not os.path.exists(stl):
                    orders[m]["status"] = "failed"; save_orders(orders)
                    log.error(f"{m} pipeline failed: {r.stderr[-500:]}")
                    await app.bot.send_message(od["chat_id"],
                        f"Order {m}: something went wrong. Please try again.")
                    continue
                with open(stl, "rb") as fh:
                    await app.bot.send_document(od["chat_id"], fh,
                        filename=os.path.basename(stl),
                        caption=f"Order {m} complete. Print-ready STL, watertight verified.")
                orders[m]["status"] = "delivered"; save_orders(orders)
                log.info(f"delivered {m}")
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

# ── main ──────────────────────────────────────────────────────────────────────
async def post_init(app):
    await ensure_merkle_tree()
    asyncio.create_task(payment_loop(app))
    asyncio.create_task(worker_loop(app))

app = Application.builder().token(TOKEN).post_init(post_init).build()
app.add_handler(CommandHandler("start",   start))
app.add_handler(CommandHandler("status",  status))
app.add_handler(CommandHandler("history", history))
app.add_handler(CommandHandler("cancel",  cancel))
app.add_handler(MessageHandler(filters.PHOTO, got_photo))
app.add_handler(CallbackQueryHandler(mode_chosen))
log.info("Phidias v1.3 starting")
app.run_polling()

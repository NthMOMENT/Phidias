"""Phidias payment monitor v0.3 — watches the hot wallet's USDC token account
(ATA) for finalized payments on Solana devnet. Matches orders by memo first,
then by unique amount (fallback for wallets that can't attach memos)."""
import asyncio, json, os
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Finalized
from spl.token.instructions import get_associated_token_address
from dotenv import load_dotenv

load_dotenv()
RPC = os.getenv("SOLANA_RPC", "https://api.devnet.solana.com")
USDC_MINT = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"
ORDERS_FILE = "orders.json"          # order book: {memo: {amount, status, created}}
POLL_SECONDS = 10

kp = Keypair.from_base58_string(open(".wallet_secret").read().strip())
ME = kp.pubkey()
ATA = get_associated_token_address(ME, Pubkey.from_string(USDC_MINT))

def load_orders():
    return json.load(open(ORDERS_FILE)) if os.path.exists(ORDERS_FILE) else {}

def save_orders(o):
    json.dump(o, open(ORDERS_FILE, "w"), indent=2)

async def scan_once(client, seen):
    """Return list of (memo, usdc_amount, signature) for new inbound payments."""
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
        for log in (meta.log_messages or []):
            if "Memo" in log and '"' in log:
                memo = log.split('"')[1]
        pre = {b.account_index: b for b in (meta.pre_token_balances or [])}
        recv = 0.0
        for b in (meta.post_token_balances or []):
            if str(b.mint) == USDC_MINT and str(b.owner) == str(ME):
                before = pre.get(b.account_index)
                before_amt = float(before.ui_token_amount.ui_amount or 0) if before else 0.0
                after_amt = float(b.ui_token_amount.ui_amount or 0)
                recv = after_amt - before_amt
        if recv > 0:
            found.append((memo, recv, sig))
    return found

def match_order(orders, memo, amount):
    """Memo match first; else unique-amount fallback. Returns order key or None."""
    o = orders.get(memo)
    if o and o["status"] == "awaiting_payment" and amount >= o["amount"]:
        return memo
    for m, od in orders.items():
        if od["status"] == "awaiting_payment" and abs(amount - od["amount"]) < 0.0001:
            return m
    return None

async def main():
    seen = set()
    async with AsyncClient(RPC, commitment=Finalized) as client:
        boot = (await client.get_signatures_for_address(ATA, limit=50)).value
        for s in boot:
            seen.add(str(s.signature))
        print(f"Wallet : {ME}")
        print(f"ATA    : {ATA}")
        print(f"Ignoring {len(boot)} historical transactions; watching for new ones.")
        print("Monitoring for USDC payments. Ctrl+C to stop.")
        while True:
            try:
                for memo, amount, sig in await scan_once(client, seen):
                    orders = load_orders()
                    matched = match_order(orders, memo, amount)
                    if matched:
                        orders[matched]["status"] = "paid"
                        orders[matched]["tx"] = sig
                        save_orders(orders)
                        print(f"PAID: order {matched} — {amount} USDC — tx {sig[:16]}...")
                    else:
                        print(f"Payment seen ({amount} USDC, memo={memo}) but no matching open order.")
            except Exception as e:
                print("scan error (will retry):", e)
                await asyncio.sleep(30)
            await asyncio.sleep(POLL_SECONDS)

asyncio.run(main())

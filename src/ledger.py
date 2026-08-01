"""Full reconciliation: decode every recent tx into a signed USDC delta + memo.
Produces the actual ledger of Phidias's wallet."""
import asyncio, os
from solders.keypair import Keypair
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Finalized
from dotenv import load_dotenv
load_dotenv()
RPC = os.getenv("SOLANA_RPC", "https://api.devnet.solana.com")
USDC_MINT = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"

async def main():
    kp = Keypair.from_base58_string(open(".wallet_secret").read().strip())
    me = str(kp.pubkey())
    async with AsyncClient(RPC, commitment=Finalized) as c:
        from solders.pubkey import Pubkey
        ATA = Pubkey.from_string("D8nHWsEy5eyH7T4kLRj8Fid9XzUCFXMmJAtsj4yp81iZ")
        sigs = (await c.get_signatures_for_address(ATA, limit=20)).value
        print(f"{'delta USDC':>12}  {'memo':<12} signature")
        print("-" * 70)
        total = 0.0
        for s in reversed(sigs):                      # oldest first, like a passbook
            tx = (await c.get_transaction(
                s.signature, max_supported_transaction_version=0)).value
            if tx is None:
                print(f"{'?':>12}  {'':<12} {str(s.signature)[:24]}... (not returned)")
                continue
            meta = tx.transaction.meta
            pre  = {b.account_index: b for b in (meta.pre_token_balances or [])}
            delta = 0.0
            for b in (meta.post_token_balances or []):
                if str(b.mint) == USDC_MINT and str(b.owner) == me:
                    before = pre.get(b.account_index)
                    b0 = float(before.ui_token_amount.ui_amount or 0) if before else 0.0
                    delta += float(b.ui_token_amount.ui_amount or 0) - b0
            # catch closed/emptied accounts too: account present pre but not post
            for i, b in pre.items():
                if str(b.mint) == USDC_MINT and str(b.owner) == me:
                    if not any(pb.account_index == i for pb in (meta.post_token_balances or [])):
                        delta -= float(b.ui_token_amount.ui_amount or 0)
            memo = ""
            for log in (meta.log_messages or []):
                if "Memo" in log and '"' in log:
                    memo = log.split('"')[1]
            total += delta
            print(f"{delta:>+12.4f}  {memo:<12} {str(s.signature)[:24]}...")
        print("-" * 70)
        print(f"{total:>+12.4f}  computed balance from ledger")

asyncio.run(main())

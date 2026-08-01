"""Reconciliation: check the sweep tx status + list recent finalized activity."""
import asyncio, os
from solders.signature import Signature
from solders.keypair import Keypair
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Finalized
from dotenv import load_dotenv
load_dotenv()
RPC = os.getenv("SOLANA_RPC", "https://api.devnet.solana.com")

SWEEP_SIG = "2R6xa1AtUoikm7btLzENi6JB2kKZayFxzhUrr4SWkPoFoamCJw1BuavW12vS8XdCF6gJQ3nJ4nFPmVZaYqrQMjsM"

async def main():
    kp = Keypair.from_base58_string(open(".wallet_secret").read().strip())
    async with AsyncClient(RPC, commitment=Finalized) as c:
        print("--- Sweep transaction status ---")
        tx = (await c.get_transaction(
            Signature.from_string(SWEEP_SIG),
            max_supported_transaction_version=0)).value
        if tx is None:
            print("NOT FOUND on finalized ledger -> the 10 USDC sweep never landed.")
        else:
            err = tx.transaction.meta.err
            print(f"Found. Error field: {err}  ({'FAILED' if err else 'SUCCEEDED'})")
        print("\n--- Last 15 finalized transactions on Phidias wallet ---")
        sigs = (await c.get_signatures_for_address(kp.pubkey(), limit=15)).value
        for s in sigs:
            status = "FAIL" if s.err else "ok"
            print(f"{status}  {str(s.signature)[:20]}...  slot {s.slot}")

asyncio.run(main())

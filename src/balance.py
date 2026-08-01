"""Check Phidias's devnet SOL and USDC balances."""
import asyncio
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient
import os
from solana.rpc.types import TokenAccountOpts
from dotenv import load_dotenv
load_dotenv()
RPC = os.getenv("SOLANA_RPC", "https://api.devnet.solana.com")

USDC_MINT = Pubkey.from_string("4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU")  # official devnet USDC

async def main():
    kp = Keypair.from_base58_string(open(".wallet_secret").read().strip())
    me = kp.pubkey()
    async with AsyncClient(RPC) as c:
        sol = (await c.get_balance(me)).value / 1e9
        print(f"Address: {me}")
        print(f"SOL    : {sol:.4f}")
        resp = await c.get_token_accounts_by_owner_json_parsed(
            me, TokenAccountOpts(mint=USDC_MINT))
        if resp.value:
            amt = resp.value[0].account.data.parsed["info"]["tokenAmount"]["uiAmount"]
            print(f"USDC   : {amt}")
        else:
            print("USDC   : no token account yet (appears after first USDC arrives)")

asyncio.run(main())

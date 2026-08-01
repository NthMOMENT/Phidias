"""Ground truth: list ALL token accounts owned by Phidias, finalized state."""
import asyncio, os
from solders.keypair import Keypair
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TokenAccountOpts
from solders.pubkey import Pubkey
from solana.rpc.commitment import Finalized
from dotenv import load_dotenv
load_dotenv()
RPC = os.getenv("SOLANA_RPC", "https://api.devnet.solana.com")
TOKEN_PROGRAM = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")

async def main():
    kp = Keypair.from_base58_string(open(".wallet_secret").read().strip())
    me = kp.pubkey()
    async with AsyncClient(RPC, commitment=Finalized) as c:
        print(f"Wallet: {me}\nRPC   : {RPC}\n")
        sol = (await c.get_balance(me)).value / 1e9
        print(f"SOL: {sol:.4f}\n")
        resp = await c.get_token_accounts_by_owner_json_parsed(
            me, TokenAccountOpts(program_id=TOKEN_PROGRAM))
        if not resp.value:
            print("No token accounts.")
        for acc in resp.value:
            info = acc.account.data.parsed["info"]
            print(f"Token account: {acc.pubkey}")
            print(f"  mint   : {info['mint']}")
            print(f"  balance: {info['tokenAmount']['uiAmount']}")
            print()

asyncio.run(main())

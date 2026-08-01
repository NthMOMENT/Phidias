"""Send USDC from Phidias's hot wallet. Usage:
   python src/send_usdc.py RECIPIENT_ADDRESS AMOUNT"""
import asyncio, sys
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient
from spl.token.async_client import AsyncToken
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.instructions import get_associated_token_address
import os
from dotenv import load_dotenv
load_dotenv()
RPC = os.getenv("SOLANA_RPC", "https://api.devnet.solana.com")

USDC_MINT = Pubkey.from_string("4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU")

async def main():
    dest = Pubkey.from_string(sys.argv[1])
    amount = float(sys.argv[2])
    payer = Keypair.from_base58_string(open(".wallet_secret").read().strip())
    async with AsyncClient(RPC) as client:
        token = AsyncToken(client, USDC_MINT, TOKEN_PROGRAM_ID, payer)
        src = get_associated_token_address(payer.pubkey(), USDC_MINT)
        dst = get_associated_token_address(dest, USDC_MINT)
        # create recipient's token account if it doesn't exist yet
        info = await client.get_account_info(dst)
        if info.value is None:
            print("Creating recipient token account...")
            await token.create_associated_token_account(dest)
        sig = await token.transfer(src, dst, payer, int(amount * 10**6))
        print(f"Sent {amount} USDC to {dest}\ntx: {sig}")

asyncio.run(main())

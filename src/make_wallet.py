"""Generate Phidias's hot wallet keypair. Run ONCE. Prints the public address."""
import os
from solders.keypair import Keypair

if os.path.exists(".wallet_secret"):
    raise SystemExit("A wallet already exists (.wallet_secret). Refusing to overwrite.")

kp = Keypair()
with open(".wallet_secret", "w") as f:
    f.write(str(kp))                    # base58-encoded secret keypair
os.chmod(".wallet_secret", 0o600)       # only root can read
print("Public address :", kp.pubkey())
print("Secret saved to .wallet_secret — never share that file's contents.")

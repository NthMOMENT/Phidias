/**
 * Phidias cNFT receipt minter v2.1 — uses shared merkle tree
 * Usage: node mint/mint_receipt.mjs <order_id> <file_hash> <chat_id> <tree_address>
 */
import { createUmi } from "@metaplex-foundation/umi-bundle-defaults";
import { keypairIdentity, publicKey } from "@metaplex-foundation/umi";
import { mplBubblegum, mintV1 } from "@metaplex-foundation/mpl-bubblegum";
import { readFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";
import bs58 from "bs58";

const __dirname = dirname(fileURLToPath(import.meta.url));
const [,, orderId, fileHash, chatId, treeAddress] = process.argv;

if (!orderId || !fileHash || !treeAddress) {
  console.error("Usage: node mint/mint_receipt.mjs <order_id> <file_hash> <chat_id> <tree_address>");
  process.exit(1);
}

const RPC    = process.env.SOLANA_RPC || "https://api.devnet.solana.com";
const umi    = createUmi(RPC).use(mplBubblegum());
const secret = readFileSync(resolve(__dirname, "../.wallet_secret"), "utf8").trim();
const bytes  = bs58.decode(secret);
const umiKp  = { publicKey: publicKey(bytes.slice(32)), secretKey: bytes };
umi.use(keypairIdentity(umiKp));

const builder = await mintV1(umi, {
  leafOwner: umiKp.publicKey,
  merkleTree: publicKey(treeAddress),
  metadata: {
    name: `Phidias Receipt — ${orderId}`,
    symbol: "PHD",
    uri: `https://phidias.art/receipts/${orderId}`,
    sellerFeeBasisPoints: 0,
    collection: { key: publicKey("11111111111111111111111111111111"), verified: false },
    creators: [{ address: umiKp.publicKey, verified: true, share: 100 }],
    isMutable: false,
  },
});

const tx  = await builder.buildAndSign(umi);
const sig = await umi.rpc.sendTransaction(tx);
await umi.rpc.confirmTransaction(sig, {
  strategy: { type: 'blockhash', ...(await umi.rpc.getLatestBlockhash()) }
});

console.log(`MINTED order=${orderId} hash=${fileHash.slice(0,16)} sig=${Buffer.from(sig).toString('hex').slice(0,16)}...`);
console.log("RECEIPT_OK");

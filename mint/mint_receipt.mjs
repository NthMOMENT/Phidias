/**
 * Phidias cNFT receipt minter v1.2
 * Usage: node mint/mint_receipt.mjs <order_id> <file_hash> <chat_id>
 */
import { createUmi } from "@metaplex-foundation/umi-bundle-defaults";
import {
  keypairIdentity,
  generateSigner,
  publicKey,
} from "@metaplex-foundation/umi";
import {
  mplBubblegum,
  createTree,
  mintV1,
} from "@metaplex-foundation/mpl-bubblegum";
import { readFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";
import bs58 from "bs58";

const __dirname = dirname(fileURLToPath(import.meta.url));
const [, , orderId, fileHash, chatId] = process.argv;

if (!orderId || !fileHash) {
  console.error("Usage: node mint/mint_receipt.mjs <order_id> <file_hash> <chat_id>");
  process.exit(1);
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

const RPC = process.env.SOLANA_RPC || "https://api.devnet.solana.com";
const umi = createUmi(RPC).use(mplBubblegum());

const secretB58 = readFileSync(
  resolve(__dirname, "../.wallet_secret"), "utf8").trim();
const fullBytes = bs58.decode(secretB58);
const umiKp = {
  publicKey: publicKey(fullBytes.slice(32)),
  secretKey: fullBytes,
};
umi.use(keypairIdentity(umiKp));

console.log(`Wallet: ${umiKp.publicKey}`);

// Create merkle tree
const merkleTree = generateSigner(umi);
console.log(`Creating merkle tree: ${merkleTree.publicKey}`);

const builder = await createTree(umi, {
  merkleTree,
  maxDepth: 3,
  maxBufferSize: 8,
});
await builder.sendAndConfirm(umi);
console.log("Merkle tree created. Waiting for account propagation...");

// Wait for account to be fully initialised on devnet
await sleep(20000);

// Mint cNFT receipt
console.log("Minting receipt...");
const { signature } = await mintV1(umi, {
  leafOwner: umiKp.publicKey,
  merkleTree: merkleTree.publicKey,
  metadata: {
    name: `Phidias Receipt — ${orderId}`,
    symbol: "PHD",
    uri: `https://phidias.art/receipts/${orderId}`,
    sellerFeeBasisPoints: 0,
    collection: { key: publicKey("11111111111111111111111111111111"), verified: false },
    creators: [{ address: umiKp.publicKey, verified: true, share: 100 }],
    isMutable: false,
  },
}).sendAndConfirm(umi);

console.log(`MINTED order=${orderId} hash=${fileHash} sig=${Buffer.from(signature).toString('hex').slice(0,16)}...`);
console.log("RECEIPT_OK");

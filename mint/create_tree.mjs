import { createUmi } from "@metaplex-foundation/umi-bundle-defaults";
import { keypairIdentity, generateSigner, publicKey } from "@metaplex-foundation/umi";
import { mplBubblegum, createTree } from "@metaplex-foundation/mpl-bubblegum";
import { readFileSync, writeFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";
import bs58 from "bs58";

const __dirname = dirname(fileURLToPath(import.meta.url));
const sleep = ms => new Promise(r => setTimeout(r, ms));
const RPC = process.env.SOLANA_RPC || "https://api.devnet.solana.com";
const umi = createUmi(RPC).use(mplBubblegum());

const secretB58 = readFileSync(resolve(__dirname, "../.wallet_secret"), "utf8").trim();
const fullBytes  = bs58.decode(secretB58);
const umiKp      = { publicKey: publicKey(fullBytes.slice(32)), secretKey: fullBytes };
umi.use(keypairIdentity(umiKp));

console.log(`Creating shared merkle tree...`);
const merkleTree = generateSigner(umi);

const builder = await createTree(umi, {
  merkleTree,
  maxDepth: 14,
  maxBufferSize: 64,
});

const tx = await builder.buildAndSign(umi);
const sig = await umi.rpc.sendTransaction(tx);
console.log(`Tree tx sent: ${Buffer.from(sig).toString('hex').slice(0,16)}...`);
console.log(`Waiting for confirmation...`);
await umi.rpc.confirmTransaction(sig, {
  strategy: { type: 'blockhash', ...(await umi.rpc.getLatestBlockhash()) }
});
console.log(`Confirmed. Waiting for propagation...`);
await sleep(20000);
console.log(`TREE:${merkleTree.publicKey}`);

# Phidias: An Autonomous Relief Sculptor

> Point your phone at anything decorative. Receive a 3D-printable or CNC-millable relief file. Pay on-chain.

Phidias is a fully autonomous AI agent on Telegram. Photograph a flower, a leaf, a pattern, a carved texture, or flat artwork, send it to the bot, pay in USDC on Solana, and receive a production ready relief STL within minutes. Ready for FDM/resin printing or CNC routing. No human touches the process.

---

## Demo

[Watch the demo video →](#) *(Week 1 submission)*

---

## What it does

1. User sends a photo to [@Phidias3DBot](https://t.me/Phidias3DBot) on Telegram
2. Bot presents output mode — physical textured subject or flat artwork
3. Bot generates a unique payment request (USDC, Solana devnet)
4. User pays the exact quoted amount
5. zkVM proof verifies payment via [Maat circuits](https://github.com/NthMOMENT/maat-circuits) *(Phase 2)*
6. Agent pipeline runs: depth estimation → heightfield → mesh generation → watertight verification → STL export
7. Bot delivers the print-ready file directly in chat
8. cNFT receipt minted on Solana *(in development)*

No human approves any step. Phidias holds his own wallet, manages his own treasury, and delivers his own files.

---

## Output modes

| Mode | Best for | Output | Machine |
|---|---|---|---|
| Relief panel | Flowers, leaves, carved patterns, textured surfaces | Watertight STL, extruded depth heightfield | FDM/resin 3D printer or CNC router |
| Flat artwork | Logos, drawings, nail art designs, signatures, mandalas | Watertight STL, luminance-based heightfield | FDM/resin 3D printer or CNC router |

Both modes produce the same file format. The customer chooses their machine — Phidias does not care.

---

## What it does not do (yet)

Phidias does not produce full volumetric 3D models from a single photograph. A photo of a car returns a relief of that car: a decorative panel, not a driveable replica. Full 3D reconstruction from a single image is marked for Phase 3.

What Phidias produces today is genuinely useful and immediately printable: a watertight, dimensionally accurate relief file verified before delivery on every order.

---

## Technical architecture

**Agentic pipeline**
- Depth estimation: Intel MiDaS DPT-Hybrid (PyTorch CPU, ~1–2s per image)
- Two heightmap modes: depth (physical textured subjects) and luminance (flat artwork)
- Gaussian smoothing and bilateral filtering for print-quality surface
- Mesh generation: trimesh with closed solid walls
- Watertight verification on every output — non-watertight meshes are repaired before delivery

**Payment layer**
- Solana devnet USDC via SPL token transfer
- Agent holds its own hot wallet; treasury sweep to cold wallet is autonomous
- Payment monitor watches the USDC associated token account (ATA) with finalized commitment only dropped transactions never trigger fulfilment
- Order matching by memo code (primary) and unique amount (fallback for wallets without memo support)
- Dedicated RPC via Helius and no public endpoint dependency

**Agent properties**
- Holds its own wallet on Solana (Arbitrum in Phase 2)
- Manages its own treasury: revenue in, API costs out, margin tracked
- Makes its own processing decisions: pipeline mode, output format, file naming
- Mints its own receipts (cNFT via Metaplex Bubblegum in development)
- Delivers its own files
- No human approves any step

---

## Stack

| Component | Technology |
|---|---|
| Bot interface | python-telegram-bot |
| Depth estimation | Intel MiDaS DPT-Hybrid (PyTorch CPU) |
| Mesh generation | trimesh, numpy-stl |
| Background removal | rembg |
| Payment monitor | solana-py, solders |
| Chain | Solana devnet (Arbitrum Sepolia — Phase 2) |
| RPC | Helius dedicated endpoint |
| Storage | VPS local (Arweave — Phase 2) |
| Receipts | Metaplex Bubblegum cNFT (in development) |
| zkVM proofs | Maat circuits — benchmarked at ~2min on CPU (Phase 2) |

---

## Hackathon submissions

| Track | Status |
|---|---|
| Solana — Colosseum | Submitted |
| Arbitrum — Agent Track | In progress |
| Arc | In progress |

---

## Roadmap

**Phase 1 (current)** Working prototype on Solana devnet. Photo → autonomous payment detection → STL delivered in chat. Watertight verified on every order.

**Phase 2** cNFT receipts via Metaplex Bubblegum, zkVM payment proofs via Maat circuits, Arbitrum payment rail, Arweave decentralised file storage, WhatsApp Business API.

**Phase 3** Full 3D reconstruction, physical fulfilment partnerships for printed output delivery, multi-chain treasury management.

---

## Setup

```bash
git clone https://github.com/NthMOMENT/Phidias
cd Phidias
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add your keys
python src/phidias_bot.py
```

**Required environment variables** (see `.env.example`):
```
TELEGRAM_TOKEN=
SOLANA_RPC=
```

---

## License

Business Source License 1.1.
Code converts to MIT on 2030-08-01. Non-commercial and personal use permitted immediately.

---

## Project

Built by [NTH MOMENT](https://github.com/NthMOMENT).
Agent named after Phidias — artistic director of the Parthenon, sculptor of the Athena Parthenos and the Zeus at Olympia. One of the Seven Wonders of the Ancient World came from his hands. This agent carries his name.

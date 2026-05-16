# NFT Detector 🕵️

Real-time NFT mint detector, scam analyzer, and collection health monitor.

## Features

- **Real-time Mint Detection** — monitors mempool for new NFT transfers/mints
- **Scam Score** — analyzes collections for rug pull indicators
- **Wash Trading Detection** — identifies artificial volume inflation
- **Holder Analysis** — checks distribution, unique holders, whale concentration
- **Floor Price Monitor** — alerts on sudden floor movements
- **Telegram Alerts** — instant notifications for new mints & suspicious activity

## Quick Start

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml
python -m nftdetector --config config.yaml
```

## Commands

```bash
# Analyze a collection
python -m nftdetector analyze 0x...

# Monitor mints in real-time
python -m nftdetector watch --contract 0x...

# Scan for suspicious collections
python -m nftdetector scan --min-mints 10 --max-score 30

# Get floor price alerts
python -m nftdetector floor --contract 0x... --threshold 5
```

## Scam Score Factors

| Factor | Weight | Description |
|--------|--------|-------------|
| Owner Concentration | 25% | Top 10 holders > 50% = suspicious |
| Mint Distribution | 20% | Few wallets minting most = bot activity |
| Royalty Missing | 15% | No creator fee = potential rug |
| Social Links | 15% | No website/twitter = higher risk |
| Contract Verified | 10% | Unverified source code |
| Transfer Pattern | 15% | Wash trading indicators |

## License

MIT

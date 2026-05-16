"""NFT Detector — CLI entry point and main daemon."""

import asyncio
import argparse
import logging
import json
import sys
from pathlib import Path

import yaml

from .scanner import MintScanner
from .analyzer import CollectionAnalyzer
from .detector import ScamDetector
from .notifier import TelegramNotifier
from .floor import FloorMonitor
from .autodetect import AutoDetector

log = logging.getLogger("nftdetector")


class NFTDetector:
    """Main detector daemon — orchestrates scanning, analysis, and alerts."""
    
    def __init__(self, config: dict):
        self.config = config
        self.scanner = MintScanner(config)
        self.analyzer = CollectionAnalyzer(config)
        self.detector = ScamDetector()
        self.notifier = TelegramNotifier(config.get("telegram", {}))
        self.floor_monitor = FloorMonitor(config)
        self.autodetect = AutoDetector(config)
        self._watched_contracts: set[str] = set(config.get("watch_contracts", []))
    
    async def start(self):
        """Start all monitoring services."""
        log.info("🕵️ NFT Detector starting...")
        
        # Load watched contracts from file if exists
        watch_file = Path(self.config.get("watch_file", "watched.json"))
        if watch_file.exists():
            data = json.loads(watch_file.read_text())
            self._watched_contracts.update(data.get("contracts", []))
            log.info(f"Loaded {len(self._watched_contracts)} watched contracts")
        
        # Start monitors concurrently
        tasks = [
            asyncio.create_task(self._scan_loop()),
            asyncio.create_task(self._floor_loop()),
        ]
        
        log.info("Monitoring active. Press Ctrl+C to stop.")
        await asyncio.gather(*tasks)
    
    async def _scan_loop(self):
        """Continuously scan for new mints."""
        while True:
            try:
                new_mints = await self.scanner.scan(self._watched_contracts)
                
                for mint in new_mints:
                    log.info(f"🆕 New mint: {mint['collection']} #{mint['tokenId']}")
                    
                    # Quick scam check
                    score = await self.detector.quick_score(mint['collection'])
                    
                    if score < 50:  # Suspicious
                        # Full analysis
                        analysis = await self.analyzer.analyze(mint['collection'])
                        await self.notifier.send_alert(mint, analysis)
                    else:
                        await self.notifier.send_mint(mint)
                
            except Exception as e:
                log.error(f"Scan error: {e}")
            
            await asyncio.sleep(self.config.get("scan_interval", 30))
    
    async def _floor_loop(self):
        """Monitor floor prices for watched collections."""
        while True:
            try:
                for contract in self._watched_contracts:
                    alert = await self.floor_monitor.check(contract)
                    if alert:
                        await self.notifier.send_floor_alert(alert)
            except Exception as e:
                log.error(f"Floor monitor error: {e}")
            
            await asyncio.sleep(self.config.get("floor_interval", 60))
    
    async def analyze(self, contract: str) -> dict:
        """Full analysis of a collection."""
        log.info(f"Analyzing {contract}...")
        
        collection = await self.analyzer.fetch_metadata(contract)
        holders = await self.analyzer.fetch_holders(contract)
        transfers = await self.analyzer.fetch_recent_transfers(contract, limit=100)
        
        scam_score = self.detector.analyze(
            collection=collection,
            holders=holders,
            transfers=transfers,
        )
        
        return {
            "contract": contract,
            "name": collection.get("name", "Unknown"),
            "floor_price": collection.get("floor_price", 0),
            "total_supply": collection.get("total_supply", 0),
            "unique_holders": len(set(h.get("address") for h in holders)),
            "scam_score": scam_score["score"],
            "risk_level": scam_score["level"],
            "warnings": scam_score["warnings"],
            "holder_breakdown": self.detector.holder_breakdown(holders),
        }
    
    async def watch(self, contract: str):
        """Add contract to watch list and monitor mints."""
        self._watched_contracts.add(contract.lower())
        self._save_watch_list()
        log.info(f"Now watching: {contract}")
        
        # Start monitoring
        while True:
            try:
                mints = await self.scanner.scan_contract(contract)
                for mint in mints:
                    await self.notifier.send_mint(mint)
            except Exception as e:
                log.error(f"Watch error: {e}")
            
            await asyncio.sleep(15)
    
    async def scan_suspicious(self, min_mints: int = 10, max_score: int = 30):
        """Scan blockchain for suspicious new collections."""
        log.info(f"Scanning for suspicious collections (min {min_mints} mints, score < {max_score})...")
        
        candidates = await self.scanner.find_new_collections(min_mints)
        
        results = []
        for contract in candidates:
            analysis = await self.analyze(contract)
            if analysis["scam_score"] < max_score:
                results.append(analysis)
                log.warning(f"⚠️ Suspicious: {analysis['name']} (score: {analysis['scam_score']})")
        
        return sorted(results, key=lambda x: x["scam_score"])
    
    def _save_watch_list(self):
        """Persist watch list to file."""
        watch_file = Path(self.config.get("watch_file", "watched.json"))
        watch_file.write_text(json.dumps({
            "contracts": list(self._watched_contracts)
        }, indent=2))


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="🕵️ NFT Detector — Real-time NFT mint detector & scam analyzer"
    )
    subparsers = parser.add_subparsers(dest="command")
    
    # analyze
    p_analyze = subparsers.add_parser("analyze", help="Analyze a collection")
    p_analyze.add_argument("contract", help="Contract address")
    p_analyze.add_argument("--json", action="store_true", help="Output JSON")
    
    # watch
    p_watch = subparsers.add_parser("watch", help="Watch a collection for mints")
    p_watch.add_argument("--contract", required=True, help="Contract to watch")
    
    # scan
    p_scan = subparsers.add_parser("scan", help="Scan for suspicious collections")
    p_scan.add_argument("--min-mints", type=int, default=10)
    p_scan.add_argument("--max-score", type=int, default=30)
    
    # floor
    p_floor = subparsers.add_parser("floor", help="Monitor floor price")
    p_floor.add_argument("--contract", required=True)
    p_floor.add_argument("--threshold", type=float, default=5.0, help="% change threshold")
    
    # monitor (daemon)
    p_monitor = subparsers.add_parser("monitor", help="Start monitoring daemon")
    
    # trending
    p_trending = subparsers.add_parser("trending", help="Show trending collections from OpenSea")
    p_trending.add_argument("--limit", type=int, default=20)
    p_trending.add_argument("--json", action="store_true")
    
    # hot-mints
    p_hot = subparsers.add_parser("hot-mints", help="Detect collections with high mint activity")
    p_hot.add_argument("--min-mints", type=int, default=5)
    p_hot.add_argument("--json", action="store_true")
    
    # whale
    p_whale = subparsers.add_parser("whale", help="Detect whale purchases")
    p_whale.add_argument("--min-value", type=float, default=5.0, help="Min ETH value")
    p_whale.add_argument("--json", action="store_true")
    
    # search
    p_search = subparsers.add_parser("search", help="Search collections by name")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--json", action="store_true")
    
    # auto
    p_auto = subparsers.add_parser("auto", help="Auto-detect trending mints & whales (daemon)")
    
    # Global
    parser.add_argument("--config", "-c", default="config.yaml")
    parser.add_argument("--verbose", "-v", action="store_true")
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    
    # Load config
    config_path = Path(args.config)
    config = {}
    if config_path.exists():
        config = yaml.safe_load(config_path.read_text()) or {}
    
    detector = NFTDetector(config)
    
    async def run():
        if args.command == "analyze":
            result = await detector.analyze(args.contract)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(f"\n🔍 Collection Analysis: {result['name']}")
                print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                print(f"  Scam Score: {result['scam_score']}/100 ({result['risk_level']})")
                print(f"  Floor Price: {result['floor_price']} ETH")
                print(f"  Supply: {result['total_supply']}")
                print(f"  Unique Holders: {result['unique_holders']}")
                if result['warnings']:
                    print(f"\n  ⚠️ Warnings:")
                    for w in result['warnings']:
                        print(f"    • {w}")
        
        elif args.command == "watch":
            await detector.watch(args.contract)
        
        elif args.command == "scan":
            results = await detector.scan_suspicious(args.min_mints, args.max_score)
            print(f"\nFound {len(results)} suspicious collections:")
            for r in results:
                print(f"  ⚠️ {r['name']}: score {r['scam_score']} ({r['risk_level']})")
        
        elif args.command == "monitor":
            await detector.start()
        
        elif args.command == "trending":
            trending = await detector.autodetect.scan_trending(limit=args.limit)
            if args.json:
                print(json.dumps(trending, indent=2))
            else:
                print(f"\n🔥 Trending NFT Collections:\n")
                for i, c in enumerate(trending[:args.limit], 1):
                    floor = f"{c['floor_price']:.3f}" if c.get('floor_price') else "—"
                    vol = f"{c['volume_24h']:.1f}" if c.get('volume_24h') else "0"
                    floor_chg = c.get('floor_price_24h_change', 0) or 0
                    chg_str = f"{floor_chg:+.1f}%" if floor_chg else ""
                    print(f"  {i:2}. {c['name']:<28} Floor: {floor:>7} ETH ({chg_str}) | Vol: {vol} ETH")
        
        elif args.command == "hot-mints":
            hot = await detector.autodetect.scan_top_gainers(limit=20)
            filtered = [h for h in hot if (h.get("floor_price_24h_change", 0) or 0) > 5]
            if args.json:
                print(json.dumps(filtered, indent=2))
            else:
                print(f"\n📈 Top Gainers (floor price ↑):\n")
                for h in filtered[:10]:
                    chg = h.get('floor_price_24h_change', 0) or 0
                    floor = f"{h['floor_price']:.3f}" if h.get('floor_price') else "—"
                    print(f"  🚀 {h['name']:<28} +{chg:.1f}% | Floor: {floor} ETH")
        
        elif args.command == "whale":
            print(f"\n🔍 Scanning for high-value collections (floor ≥ {args.min_value} ETH)...\n")
            trending = await detector.autodetect.scan_trending(sort_by="floor_price_native_desc", limit=50)
            whales = [c for c in trending if (c.get("floor_price", 0) or 0) >= args.min_value]
            
            if args.json:
                print(json.dumps(whales, indent=2))
            else:
                print(f"🐋 High-Value Collections (floor ≥ {args.min_value} ETH):\n")
                for w in whales[:10]:
                    print(f"  💰 {w['name']:<28} Floor: {w['floor_price']:.3f} ETH | MCap: {w.get('market_cap', 0):.0f} ETH")
        
        elif args.command == "search":
            results = await detector.autodetect.search_collections(args.query)
            if args.json:
                print(json.dumps(results, indent=2))
            else:
                print(f"\n🔍 Search: '{args.query}' ({len(results)} results):\n")
                for r in results[:10]:
                    floor = f"{r['floor_price']:.3f}" if r.get('floor_price') else "—"
                    print(f"  • {r['name']} ({r.get('symbol', '')})")
                    print(f"    Floor: {floor} ETH | Contract: {r['contract'][:16]}...")
        
        elif args.command == "auto":
            async def on_alert(event_type, data):
                if event_type == "floor_spike":
                    chg = data.get('change_pct', 0)
                    direction = "📈 SPIKE" if chg > 0 else "📉 DROP"
                    print(f"\n{direction}: {data['name']} ({chg:+.1f}%)")
                    await detector.notifier._send(
                        f"{direction} **Floor Price Alert**\n\n"
                        f"📦 {data['name']}\n"
                        f"📊 Change: {chg:+.1f}%\n"
                        f"💰 Floor: {data.get('floor_price', 0):.3f} ETH"
                    )
                elif event_type == "trending_update":
                    names = [c['name'] for c in data.get('collections', [])]
                    print(f"\n📊 Trending: {', '.join(names[:5])}")
            
            print("🤖 Auto-detect started — monitoring floor spikes & trending...")
            print("   Press Ctrl+C to stop\n")
            await detector.autodetect.auto_monitor(callback=on_alert)
        
        else:
            parser.print_help()
    
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n👋 NFT Detector stopped.")


if __name__ == "__main__":
    main()

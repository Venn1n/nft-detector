"""AutoDetector — Auto-detect trending and new NFT collections from OpenSea.

Monitors OpenSea for:
- New collections with sudden activity
- Trending collections by volume
- Collections with mint events
- Whale activity detection
"""

import asyncio
import json
import logging
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("nftdetector.autodetect")


@dataclass
class TrackedCollection:
    """A collection being tracked for activity."""
    contract: str
    name: str
    slug: str
    discovered_at: int = 0
    last_floor: float = 0.0
    last_volume: float = 0.0
    mint_count: int = 0
    alert_sent: bool = False


class AutoDetector:
    """Auto-detect NFT collections from OpenSea without manual watch list."""
    
    def __init__(self, config: dict):
        self.config = config
        self.api_key = config.get("opensea_api_key", "")
        self.state_file = Path(config.get("autodetect_state", "autodetect_state.json"))
        self._tracked: dict[str, TrackedCollection] = {}
        self._seen_contracts: set[str] = set()
        self._load_state()
    
    async def scan_trending(self, chain: str = "ethereum", limit: int = 50) -> list[dict]:
        """Fetch trending collections from OpenSea."""
        url = (
            f"https://api.opensea.io/api/v2/collections"
            f"?chain={chain}"
            f"&order_by=one_day_volume"
            f"&limit={limit}"
        )
        
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
        
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                
                collections = []
                for c in data.get("collections", []):
                    contract = c.get("address", "").lower()
                    if not contract:
                        continue
                    
                    info = {
                        "contract": contract,
                        "name": c.get("name", "Unknown"),
                        "slug": c.get("slug", ""),
                        "floor_price": self._parse_floor(c.get("floor_price")),
                        "total_supply": c.get("total_supply", 0),
                        "num_owners": c.get("num_owners", 0),
                        "one_day_volume": c.get("one_day_volume", 0),
                        "one_day_sales": c.get("one_day_sales", 0),
                        "one_day_change": c.get("one_day_change", 0),
                        "image_url": c.get("image_url", ""),
                        "description": c.get("description", "")[:200],
                        "external_url": c.get("external_url", ""),
                        "twitter": c.get("twitter_username", ""),
                        "discord": c.get("discord_url", ""),
                    }
                    
                    collections.append(info)
                    
                    # Track new collections
                    if contract not in self._seen_contracts:
                        self._seen_contracts.add(contract)
                        self._tracked[contract] = TrackedCollection(
                            contract=contract,
                            name=info["name"],
                            slug=info["slug"],
                            discovered_at=int(time.time()),
                            last_floor=info["floor_price"],
                            last_volume=info["one_day_volume"],
                        )
                
                return collections
        
        except Exception as e:
            log.error(f"Trending scan error: {e}")
            return []
    
    async def scan_new_collections(self, hours: int = 24, limit: int = 50) -> list[dict]:
        """Find newly created collections with activity."""
        url = (
            f"https://api.opensea.io/api/v2/collections"
            f"?order_by=created_date"
            f"&order_direction=desc"
            f"&limit={limit}"
        )
        
        headers = {"User-Agent": "Mozilla/5.0"}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
        
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                
                cutoff = int(time.time()) - (hours * 3600)
                new_collections = []
                
                for c in data.get("collections", []):
                    contract = c.get("address", "").lower()
                    if not contract:
                        continue
                    
                    # Parse created date
                    created = c.get("created_date", "")
                    
                    info = {
                        "contract": contract,
                        "name": c.get("name", "Unknown"),
                        "slug": c.get("slug", ""),
                        "created_date": created,
                        "floor_price": self._parse_floor(c.get("floor_price")),
                        "total_supply": c.get("total_supply", 0),
                        "num_owners": c.get("num_owners", 0),
                        "image_url": c.get("image_url", ""),
                    }
                    
                    new_collections.append(info)
                    
                    # Auto-track if has activity
                    if info["total_supply"] > 0 and contract not in self._seen_contracts:
                        self._seen_contracts.add(contract)
                        self._tracked[contract] = TrackedCollection(
                            contract=contract,
                            name=info["name"],
                            slug=info["slug"],
                            discovered_at=int(time.time()),
                            last_floor=info["floor_price"],
                        )
                
                return new_collections
        
        except Exception as e:
            log.error(f"New collections scan error: {e}")
            return []
    
    async def scan_hot_mints(self, limit: int = 50) -> list[dict]:
        """Find collections with high mint activity (hot mints)."""
        # Use OpenSea events API to find recent mint events
        url = (
            f"https://api.opensea.io/api/v2/events"
            f"?chain=ethereum"
            f"&event_type=transfer"
            f"&limit={limit}"
        )
        
        headers = {"User-Agent": "Mozilla/5.0"}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
        
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                
                # Group by collection
                collection_mints: dict[str, list] = {}
                
                for event in data.get("asset_events", []):
                    nft = event.get("nft", {})
                    contract = nft.get("contract", "").lower()
                    
                    if not contract:
                        continue
                    
                    # Check if mint (from is null/zero)
                    from_addr = event.get("from_address", "")
                    is_mint = not from_addr or from_addr == "0x" + "0" * 40
                    
                    if is_mint:
                        if contract not in collection_mints:
                            collection_mints[contract] = []
                        
                        collection_mints[contract].append({
                            "token_id": nft.get("identifier", ""),
                            "to": event.get("to_address", ""),
                            "timestamp": event.get("event_timestamp", ""),
                            "collection_name": nft.get("collection", "Unknown"),
                        })
                        
                        # Update tracked
                        if contract in self._tracked:
                            self._tracked[contract].mint_count += 1
                
                # Convert to sorted list (most mints first)
                hot_mints = []
                for contract, mints in collection_mints.items():
                    if len(mints) >= 3:  # At least 3 mints to be "hot"
                        hot_mints.append({
                            "contract": contract,
                            "name": mints[0].get("collection_name", "Unknown"),
                            "mint_count": len(mints),
                            "recent_mints": mints[:5],
                        })
                
                return sorted(hot_mints, key=lambda x: x["mint_count"], reverse=True)
        
        except Exception as e:
            log.error(f"Hot mints scan error: {e}")
            return []
    
    async def scan_whale_activity(self, min_value: float = 10.0) -> list[dict]:
        """Detect whale purchases (high-value transfers)."""
        url = (
            f"https://api.opensea.io/api/v2/events"
            f"?chain=ethereum"
            f"&event_type=sale"
            f"&limit=100"
        )
        
        headers = {"User-Agent": "Mozilla/5.0"}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
        
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                
                whale_activity = []
                
                for event in data.get("asset_events", []):
                    payment = event.get("payment_details", {})
                    price = float(payment.get("quantity", 0)) / (10 ** int(payment.get("decimals", 18)))
                    symbol = payment.get("symbol", "ETH")
                    
                    # Filter by minimum value
                    if price >= min_value and symbol in ["ETH", "WETH"]:
                        nft = event.get("nft", {})
                        collection = nft.get("collection", "Unknown")
                        
                        whale_activity.append({
                            "contract": nft.get("contract", "").lower(),
                            "collection": collection,
                            "token_id": nft.get("identifier", ""),
                            "price": price,
                            "symbol": symbol,
                            "buyer": event.get("to_address", ""),
                            "seller": event.get("from_address", ""),
                            "timestamp": event.get("event_timestamp", ""),
                            "tx_hash": event.get("transaction_hash", ""),
                        })
                
                return sorted(whale_activity, key=lambda x: x["price"], reverse=True)
        
        except Exception as e:
            log.error(f"Whale activity scan error: {e}")
            return []
    
    async def search_collections(self, query: str, limit: int = 20) -> list[dict]:
        """Search collections by name/keyword."""
        url = f"https://api.opensea.io/api/v2/collections?search={query}&limit={limit}"
        
        headers = {"User-Agent": "Mozilla/5.0"}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
        
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                
                results = []
                for c in data.get("collections", []):
                    results.append({
                        "contract": c.get("address", "").lower(),
                        "name": c.get("name", "Unknown"),
                        "slug": c.get("slug", ""),
                        "floor_price": self._parse_floor(c.get("floor_price")),
                        "total_supply": c.get("total_supply", 0),
                        "image_url": c.get("image_url", ""),
                    })
                
                return results
        
        except Exception as e:
            log.error(f"Search error: {e}")
            return []
    
    async def get_collection_details(self, slug: str) -> Optional[dict]:
        """Get detailed info about a collection by slug."""
        url = f"https://api.opensea.io/api/v2/collections/{slug}"
        
        headers = {"User-Agent": "Mozilla/5.0"}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
        
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                c = json.loads(resp.read())
                
                return {
                    "contract": c.get("address", "").lower(),
                    "name": c.get("name", "Unknown"),
                    "slug": c.get("slug", ""),
                    "description": c.get("description", ""),
                    "image_url": c.get("image_url", ""),
                    "banner_url": c.get("banner_image_url", ""),
                    "external_url": c.get("external_url", ""),
                    "twitter": c.get("twitter_username", ""),
                    "discord": c.get("discord_url", ""),
                    "total_supply": c.get("total_supply", 0),
                    "num_owners": c.get("num_owners", 0),
                    "floor_price": self._parse_floor(c.get("floor_price")),
                    "total_volume": c.get("total_volume", 0),
                    "total_sales": c.get("total_sales", 0),
                    "one_day_volume": c.get("one_day_volume", 0),
                    "one_day_change": c.get("one_day_change", 0),
                    "one_day_sales": c.get("one_day_sales", 0),
                    "seven_day_volume": c.get("seven_day_volume", 0),
                    "thirty_day_volume": c.get("thirty_day_volume", 0),
                    "traits": c.get("traits", []),
                }
        
        except Exception as e:
            log.error(f"Collection details error: {e}")
            return None
    
    async def auto_monitor(self, callback=None):
        """Continuous auto-monitoring loop.
        
        Scans for:
        - Trending collections (every 10 min)
        - New collections (every 30 min)
        - Hot mints (every 2 min)
        - Whale activity (every 5 min)
        """
        log.info("🤖 Auto-monitor started")
        
        counters = {
            "trending": 0,
            "new": 0,
            "hot_mints": 0,
            "whale": 0,
        }
        
        while True:
            try:
                # Hot mints every 2 minutes
                hot_mints = await self.scan_hot_mints(limit=30)
                if hot_mints and callback:
                    for mint in hot_mints[:5]:
                        if mint["mint_count"] >= 10:
                            await callback("hot_mint", mint)
                counters["hot_mints"] += 1
                
                await asyncio.sleep(120)
                
                # Whale activity every 5 minutes
                whales = await self.scan_whale_activity(min_value=5.0)
                if whales and callback:
                    for whale in whales[:3]:
                        await callback("whale", whale)
                counters["whale"] += 1
                
                await asyncio.sleep(180)
                
                # Trending every 10 minutes
                trending = await self.scan_trending(limit=20)
                counters["trending"] += 1
                
                await asyncio.sleep(420)
                
                # New collections every 30 minutes
                new_collections = await self.scan_new_collections(hours=24, limit=10)
                if new_collections and callback:
                    for c in new_collections[:3]:
                        if c["total_supply"] > 10:
                            await callback("new_collection", c)
                counters["new"] += 1
                
                await self._save_state()
                
                log.info(f"Auto-monitor cycle complete: {counters}")
                
            except Exception as e:
                log.error(f"Auto-monitor error: {e}")
                await asyncio.sleep(30)
    
    def get_tracked(self) -> list[dict]:
        """Get all tracked collections."""
        return [
            {
                "contract": tc.contract,
                "name": tc.name,
                "slug": tc.slug,
                "discovered_at": tc.discovered_at,
                "last_floor": tc.last_floor,
                "last_volume": tc.last_volume,
                "mint_count": tc.mint_count,
            }
            for tc in self._tracked.values()
        ]
    
    def get_stats(self) -> dict:
        """Get auto-detection statistics."""
        return {
            "tracked_count": len(self._tracked),
            "seen_contracts": len(self._seen_contracts),
            "total_mints_detected": sum(tc.mint_count for tc in self._tracked.values()),
        }
    
    def _parse_floor(self, floor_data) -> float:
        """Parse floor price from OpenSea response."""
        if isinstance(floor_data, dict):
            return float(floor_data.get("amount", 0))
        elif isinstance(floor_data, (int, float)):
            return float(floor_data)
        return 0.0
    
    def _load_state(self):
        """Load persisted state."""
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                self._seen_contracts = set(data.get("seen_contracts", []))
                for tc in data.get("tracked", []):
                    self._tracked[tc["contract"]] = TrackedCollection(**tc)
                log.info(f"Loaded state: {len(self._tracked)} tracked, {len(self._seen_contracts)} seen")
            except Exception as e:
                log.error(f"State load error: {e}")
    
    async def _save_state(self):
        """Persist state to disk."""
        try:
            data = {
                "seen_contracts": list(self._seen_contracts),
                "tracked": [
                    {
                        "contract": tc.contract,
                        "name": tc.name,
                        "slug": tc.slug,
                        "discovered_at": tc.discovered_at,
                        "last_floor": tc.last_floor,
                        "last_volume": tc.last_volume,
                        "mint_count": tc.mint_count,
                    }
                    for tc in self._tracked.values()
                ],
                "saved_at": int(time.time()),
            }
            self.state_file.write_text(json.dumps(data, indent=2))
        except Exception as e:
            log.error(f"State save error: {e}")

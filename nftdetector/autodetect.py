"""AutoDetector — Auto-detect NFT collections via CoinGecko & public APIs.

Monitors for:
- Trending NFT collections (by volume, floor change)
- New collections with sudden activity
- Hot mints detection
- Whale activity monitoring
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
    """Auto-detect NFT collections using CoinGecko (free endpoints)."""
    
    COINGECKO_BASE = "https://api.coingecko.com/api/v3"
    
    def __init__(self, config: dict):
        self.config = config
        self.api_key = config.get("opensea_api_key", "")
        self.state_file = Path(config.get("autodetect_state", "autodetect_state.json"))
        self._tracked: dict[str, TrackedCollection] = {}
        self._seen_contracts: set[str] = set()
        self._cache: dict = {}
        self._cache_time: float = 0
        self._load_state()
    
    def _get_headers(self) -> dict:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        if self.api_key:
            headers["x-cg-demo-api-key"] = self.api_key
        return headers
    
    async def scan_trending(self, sort_by: str = "h24_volume_native_desc", limit: int = 20) -> list[dict]:
        """Fetch trending NFT collections.
        
        Uses /nfts/markets (may require API key) or falls back to /nfts/list + cache.
        """
        # Try markets endpoint (needs API key)
        if self.api_key:
            return await self._scan_markets(sort_by, limit)
        
        # Fallback: use list + cached details
        return await self._scan_from_list(limit)
    
    async def _scan_markets(self, sort_by: str, limit: int) -> list[dict]:
        """Use /nfts/markets endpoint (requires API key)."""
        url = f"{self.COINGECKO_BASE}/nfts/markets?vs_currency=eth&order={sort_by}&per_page={limit}&page=1"
        
        try:
            req = urllib.request.Request(url, headers=self._get_headers())
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                return self._parse_markets(data)
        except Exception as e:
            log.warning(f"Markets endpoint error: {e}, falling back to list")
            return await self._scan_from_list(limit)
    
    async def _scan_from_list(self, limit: int = 10) -> list[dict]:
        """Use /nfts/list (free) + batch fetch details with rate limit handling."""
        url = f"{self.COINGECKO_BASE}/nfts/list?per_page={limit}&page=1"
        
        # Check cache (5 min)
        now = time.time()
        if self._cache.get("trending") and (now - self._cache_time) < 300:
            return self._cache["trending"]
        
        try:
            req = urllib.request.Request(url, headers=self._get_headers())
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            
            # Only fetch details for top 10 to avoid rate limits
            slugs = [c.get("id", "") for c in data[:10] if c.get("id")]
            collections = []
            
            # Sequential with delay to avoid 429
            for slug in slugs:
                detail = await self._fetch_collection_detail(slug)
                if detail:
                    collections.append(detail)
                await asyncio.sleep(1.5)  # Rate limit: ~1 req per 1.5s
            
            # Cache result
            self._cache["trending"] = collections
            self._cache_time = now
            
            return collections
        
        except Exception as e:
            log.error(f"List endpoint error: {e}")
            return []
    
    async def _fetch_collection_detail(self, slug: str, retries: int = 2) -> Optional[dict]:
        """Fetch single collection detail with retry on rate limit."""
        url = f"{self.COINGECKO_BASE}/nfts/{slug}"
        
        for attempt in range(retries + 1):
            try:
                req = urllib.request.Request(url, headers=self._get_headers())
                with urllib.request.urlopen(req, timeout=10) as resp:
                    c = json.loads(resp.read())
                    return self._parse_collection(c)
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < retries:
                    wait = 10 * (attempt + 1)
                    log.warning(f"Rate limited on {slug}, waiting {wait}s...")
                    await asyncio.sleep(wait)
                else:
                    log.debug(f"Detail fetch error for {slug}: {e}")
                    return None
            except Exception as e:
                log.debug(f"Detail fetch error for {slug}: {e}")
                return None
        
        return None
    
    def _parse_collection(self, c: dict) -> dict:
        """Parse CoinGecko collection format."""
        contract = c.get("contract_address", "").lower()
        slug = c.get("id", "")
        
        # floor_price can be a dict or number
        floor = c.get("floor_price", {})
        floor_eth = 0
        if isinstance(floor, dict):
            native = floor.get("native_currency", 0) or floor.get("native_coin", {}).get("floor_price", 0) or 0
            if isinstance(native, dict):
                native = native.get("floor_price", 0) or 0
            floor_eth = native
        elif isinstance(floor, (int, float)):
            floor_eth = floor
        
        # volume can be a dict or number  
        volume = c.get("h24_volume_native", {})
        vol_24h = 0
        if isinstance(volume, dict):
            vol_24h = volume.get("native_currency", 0) or volume.get("native_coin", 0) or 0
        elif isinstance(volume, (int, float)):
            vol_24h = volume
        vol_24h = vol_24h or 0
        
        # floor change can be a dict or number
        floor_chg_raw = c.get("floor_price_24h_percentage_change", {})
        floor_chg = 0
        if isinstance(floor_chg_raw, dict):
            floor_chg = floor_chg_raw.get("native_currency", 0) or floor_chg_raw.get("native_coin", 0) or 0
        elif isinstance(floor_chg_raw, (int, float)):
            floor_chg = floor_chg_raw
        floor_chg = floor_chg or 0
        
        # market cap
        mcap = c.get("market_cap_native", {})
        market_cap = 0
        if isinstance(mcap, dict):
            market_cap = mcap.get("floor_price_market_cap", 0) or mcap.get("native_currency", 0) or 0
        elif isinstance(mcap, (int, float)):
            market_cap = mcap
        market_cap = market_cap or 0
        
        info = {
            "contract": contract,
            "name": c.get("name", "Unknown"),
            "slug": slug,
            "symbol": c.get("symbol", ""),
            "floor_price": float(floor_eth) if floor_eth else 0,
            "floor_price_24h_change": float(floor_chg) if floor_chg else 0,
            "market_cap": float(market_cap) if market_cap else 0,
            "volume_24h": float(vol_24h) if vol_24h else 0,
            "total_supply": int(c.get("total_supply", 0) or 0),
            "num_owners": int(c.get("number_of_unique_addresses", 0) or 0),
            "image_url": c.get("image", {}).get("small", "") if isinstance(c.get("image"), dict) else (c.get("image") or ""),
            "description": (c.get("description") or "")[:200],
        }
        
        # Auto-track
        if contract and contract not in self._seen_contracts:
            self._seen_contracts.add(contract)
            self._tracked[contract] = TrackedCollection(
                contract=contract,
                name=info["name"],
                slug=slug,
                discovered_at=int(time.time()),
                last_floor=info["floor_price"],
                last_volume=info["volume_24h"],
            )
        
        return info
    
    def _parse_markets(self, data: list) -> list[dict]:
        """Parse /nfts/markets response."""
        collections = []
        for c in data:
            info = self._parse_collection(c)
            collections.append(info)
        return collections
    
    async def scan_top_gainers(self, limit: int = 20) -> list[dict]:
        """Find NFT collections with biggest floor price increase."""
        trending = await self.scan_trending(limit=50)
        return sorted(trending, key=lambda x: abs(x.get("floor_price_24h_change", 0) or 0), reverse=True)[:limit]
    
    async def scan_top_losers(self, limit: int = 20) -> list[dict]:
        """Find NFT collections with biggest floor price decrease."""
        trending = await self.scan_trending(limit=50)
        losers = [c for c in trending if (c.get("floor_price_24h_change", 0) or 0) < 0]
        return sorted(losers, key=lambda x: x.get("floor_price_24h_change", 0) or 0)[:limit]
    
    async def get_collection_details(self, slug: str) -> Optional[dict]:
        """Get detailed info about a specific collection by CoinGecko ID."""
        return await self._fetch_collection_detail(slug)
    
    async def search_collections(self, query: str, limit: int = 10) -> list[dict]:
        """Search NFT collections by name using CoinGecko."""
        # CoinGecko /nfts/list supports searching
        url = f"{self.COINGECKO_BASE}/nfts/list?per_page=100&page=1"
        
        try:
            req = urllib.request.Request(url, headers=self._get_headers())
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                
                query_lower = query.lower()
                results = []
                
                for c in data:
                    name = c.get("name", "")
                    symbol = c.get("symbol", "")
                    
                    if query_lower in name.lower() or query_lower in symbol.lower():
                        # Fetch details for matching
                        detail = await self._fetch_collection_detail(c.get("id", ""))
                        if detail:
                            results.append(detail)
                        
                        if len(results) >= limit:
                            break
                
                return results
        
        except Exception as e:
            log.error(f"Search error: {e}")
            return []
    
    async def detect_floor_spikes(self, threshold_pct: float = 10.0) -> list[dict]:
        """Detect collections with significant floor price movement."""
        trending = await self.scan_trending(sort_by="h24_floor_price_percentage_change_desc", limit=50)
        
        alerts = []
        for c in trending:
            change = abs(c.get("floor_price_24h_change", 0) or 0)
            if change >= threshold_pct:
                alerts.append({
                    **c,
                    "alert_type": "spike_up" if c.get("floor_price_24h_change", 0) > 0 else "spike_down",
                    "change_pct": c.get("floor_price_24h_change", 0),
                })
        
        return sorted(alerts, key=lambda x: abs(x["change_pct"]), reverse=True)
    
    async def auto_monitor(self, callback=None):
        """Continuous auto-monitoring loop.
        
        Monitors:
        - Trending collections (every 10 min)
        - Floor spikes (every 5 min)
        - Top gainers/losers (every 15 min)
        """
        log.info("🤖 Auto-monitor started (CoinGecko)")
        
        cycle = 0
        
        while True:
            try:
                cycle += 1
                
                # Floor spikes every 5 minutes
                spikes = await self.detect_floor_spikes(threshold_pct=10.0)
                if spikes and callback:
                    for spike in spikes[:3]:
                        await callback("floor_spike", spike)
                
                await asyncio.sleep(300)
                
                # Trending every 10 minutes
                trending = await self.scan_trending(limit=10)
                if trending and callback and cycle % 2 == 0:
                    await callback("trending_update", {"collections": trending[:5]})
                
                await asyncio.sleep(300)
                
                # Save state
                await self._save_state()
                
                log.info(f"Auto-monitor cycle {cycle} complete")
                
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
    
    def _load_state(self):
        """Load persisted state."""
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                self._seen_contracts = set(data.get("seen_contracts", []))
                for tc in data.get("tracked", []):
                    self._tracked[tc["contract"]] = TrackedCollection(**tc)
                log.info(f"Loaded state: {len(self._tracked)} tracked")
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

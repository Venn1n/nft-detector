"""Floor Monitor — Track floor price movements and send alerts."""

import json
import logging
import urllib.request
from pathlib import Path
from typing import Optional

log = logging.getLogger("nftdetector.floor")


class FloorMonitor:
    """Monitors floor prices and alerts on significant movements."""
    
    def __init__(self, config: dict):
        self.config = config
        self.threshold = config.get("floor_threshold", 5.0)  # % change
        self.history_file = Path(config.get("floor_history_file", "floor_history.json"))
        self._history: dict[str, list] = self._load_history()
        self.opensea_api_key = config.get("opensea_api_key", "")
    
    async def check(self, contract: str) -> Optional[dict]:
        """Check floor price and return alert if threshold exceeded."""
        # Fetch current floor
        current_floor = await self._fetch_floor(contract)
        
        if current_floor is None or current_floor == 0:
            return None
        
        # Get previous floor
        history = self._history.get(contract, [])
        previous_floor = history[-1]["floor"] if history else None
        
        # Record
        import time
        self._history.setdefault(contract, []).append({
            "floor": current_floor,
            "timestamp": int(time.time()),
        })
        
        # Keep last 1000 data points
        if len(self._history[contract]) > 1000:
            self._history[contract] = self._history[contract][-1000:]
        
        # Save periodically
        if len(self._history[contract]) % 10 == 0:
            self._save_history()
        
        # Check threshold
        if previous_floor and previous_floor > 0:
            change_pct = ((current_floor - previous_floor) / previous_floor) * 100
            
            if abs(change_pct) >= self.threshold:
                return {
                    "contract": contract,
                    "old_floor": previous_floor,
                    "new_floor": current_floor,
                    "change_pct": change_pct,
                }
        
        return None
    
    async def get_history(self, contract: str, hours: int = 24) -> list[dict]:
        """Get floor price history for a contract."""
        import time
        
        cutoff = int(time.time()) - (hours * 3600)
        history = self._history.get(contract, [])
        
        return [h for h in history if h["timestamp"] >= cutoff]
    
    async def get_stats(self, contract: str) -> dict:
        """Get floor price statistics."""
        history = await self.get_history(contract, hours=24)
        
        if not history:
            return {}
        
        floors = [h["floor"] for h in history]
        
        return {
            "current": floors[-1] if floors else 0,
            "min_24h": min(floors) if floors else 0,
            "max_24h": max(floors) if floors else 0,
            "avg_24h": sum(floors) / len(floors) if floors else 0,
            "samples": len(floors),
            "first_seen": history[0]["timestamp"] if history else 0,
        }
    
    async def _fetch_floor(self, contract: str) -> Optional[float]:
        """Fetch current floor price from OpenSea."""
        url = f"https://api.opensea.io/api/v2/collections/{contract}/stats"
        
        headers = {"User-Agent": "Mozilla/5.0"}
        if self.opensea_api_key:
            headers["X-API-KEY"] = self.opensea_api_key
        
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                
                # Try different response formats
                floor = data.get("total", {}).get("floor_price")
                if floor:
                    return float(floor)
                
                # Alternative format
                floor = data.get("floor_price")
                if floor:
                    if isinstance(floor, dict):
                        return float(floor.get("amount", 0))
                    return float(floor)
        
        except Exception as e:
            log.warning(f"Floor fetch error for {contract}: {e}")
        
        return None
    
    def _load_history(self) -> dict:
        """Load floor history from disk."""
        if self.history_file.exists():
            try:
                return json.loads(self.history_file.read_text())
            except:
                pass
        return {}
    
    def _save_history(self):
        """Save floor history to disk."""
        try:
            self.history_file.write_text(json.dumps(self._history, indent=2))
        except Exception as e:
            log.error(f"Failed to save floor history: {e}")

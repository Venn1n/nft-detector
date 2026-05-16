"""NFT Analyzer — Fetch and analyze collection metadata, holders, and transfers."""

import json
import logging
import urllib.request
from typing import Optional

log = logging.getLogger("nftdetector.analyzer")


class CollectionAnalyzer:
    """Analyzes NFT collections for various metrics."""
    
    def __init__(self, config: dict):
        self.config = config
        self.opensea_api_key = config.get("opensea_api_key", "")
        self.etherscan_key = config.get("etherscan_api_key", "")
    
    async def fetch_metadata(self, contract: str) -> dict:
        """Fetch collection metadata from OpenSea/block explorer."""
        # Try OpenSea API
        url = f"https://api.opensea.io/api/v2/collections?chain=ethereum&contract_addresses={contract}"
        
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        if self.opensea_api_key:
            headers["X-API-KEY"] = self.opensea_api_key
        
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                collections = data.get("collections", [])
                
                if collections:
                    c = collections[0]
                    return {
                        "name": c.get("name", "Unknown"),
                        "description": c.get("description", ""),
                        "image_url": c.get("image_url", ""),
                        "banner_url": c.get("banner_image_url", ""),
                        "external_url": c.get("external_url", ""),
                        "twitter": c.get("twitter_username", ""),
                        "discord": c.get("discord_url", ""),
                        "total_supply": c.get("total_supply", 0),
                        "floor_price": self._parse_floor(c.get("floor_price")),
                        "total_volume": c.get("total_volume", 0),
                        "num_owners": c.get("num_owners", 0),
                        "created_date": c.get("created_date", ""),
                    }
        except Exception as e:
            log.warning(f"OpenSea fetch failed: {e}")
        
        # Fallback: basic info from etherscan
        return {
            "name": f"Collection {contract[:10]}...",
            "total_supply": 0,
            "floor_price": 0,
        }
    
    async def fetch_holders(self, contract: str, limit: int = 1000) -> list[dict]:
        """Fetch token holders for a collection."""
        # Use OpenSea API for holder data
        url = f"https://api.opensea.io/api/v2/collections/{contract}/owners?limit={limit}"
        
        headers = {"User-Agent": "Mozilla/5.0"}
        if self.opensea_api_key:
            headers["X-API-KEY"] = self.opensea_api_key
        
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                
                owners = []
                for owner in data.get("owners", []):
                    addr = owner.get("address", "")
                    quantity = owner.get("quantity", 0)
                    owners.append({
                        "address": addr.lower(),
                        "quantity": int(quantity),
                    })
                
                return owners
        
        except Exception as e:
            log.warning(f"Holder fetch failed: {e}")
            return []
    
    async def fetch_recent_transfers(self, contract: str, limit: int = 100) -> list[dict]:
        """Fetch recent transfers for a collection."""
        url = f"https://api.opensea.io/api/v2/events?chain=ethereum&contract={contract}&event_type=transfer&limit={limit}"
        
        headers = {"User-Agent": "Mozilla/5.0"}
        if self.opensea_api_key:
            headers["X-API-KEY"] = self.opensea_api_key
        
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                
                transfers = []
                for event in data.get("asset_events", []):
                    transfers.append({
                        "from": event.get("from_address", "").lower(),
                        "to": event.get("to_address", "").lower(),
                        "token_id": event.get("token_id", ""),
                        "timestamp": event.get("event_timestamp", ""),
                        "tx_hash": event.get("transaction_hash", ""),
                    })
                
                return transfers
        
        except Exception as e:
            log.warning(f"Transfer fetch failed: {e}")
            return []
    
    async def fetch_contract_source(self, contract: str) -> dict:
        """Check if contract source is verified on Etherscan."""
        url = f"https://api.etherscan.io/api?module=contract&action=getsourcecode&address={contract}"
        
        if self.etherscan_key:
            url += f"&apikey={self.etherscan_key}"
        
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                
                if data.get("status") == "1" and data.get("result"):
                    result = data["result"][0]
                    return {
                        "verified": bool(result.get("SourceCode")),
                        "compiler": result.get("CompilerVersion", ""),
                        "contract_name": result.get("ContractName", ""),
                        "proxy": result.get("Proxy") == "1",
                    }
        except Exception as e:
            log.warning(f"Contract source fetch failed: {e}")
        
        return {"verified": False}
    
    def _parse_floor(self, floor_data) -> float:
        """Parse floor price from OpenSea response."""
        if isinstance(floor_data, dict):
            return float(floor_data.get("amount", 0))
        elif isinstance(floor_data, (int, float)):
            return float(floor_data)
        return 0.0

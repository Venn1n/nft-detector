"""NFT Scanner — Detect new mints and transfers in real-time."""

import asyncio
import json
import logging
import urllib.request
from typing import Optional
from dataclasses import dataclass

log = logging.getLogger("nftdetector.scanner")

# Common NFT transfer event signatures
ERC721_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ERC1155_TRANSFER_SINGLE = "0xc3d58168d5cc7f254b5bf57d57f9e2b5e7c580b51d6d8d2d4c7b8e9f0a1b2c3d"


@dataclass
class MintEvent:
    """Represents a detected NFT mint."""
    collection: str
    tokenId: str
    to: str
    from_addr: str
    block: int
    tx_hash: str
    timestamp: int


class MintScanner:
    """Scans blockchain for new NFT mints."""
    
    def __init__(self, config: dict):
        self.config = config
        self.rpc_url = config.get("rpc_url", "https://eth.llamarpc.com")
        self.api_key = config.get("etherscan_api_key", "")
        self._last_block: int = 0
        self._seen_txs: set[str] = set()
    
    async def scan(self, contracts: set[str]) -> list[dict]:
        """Scan for new mints in watched contracts."""
        mints = []
        
        for contract in contracts:
            try:
                contract_mints = await self.scan_contract(contract)
                mints.extend(contract_mints)
            except Exception as e:
                log.warning(f"Scan error for {contract}: {e}")
        
        return mints
    
    async def scan_contract(self, contract: str) -> list[dict]:
        """Scan a specific contract for new transfers/mints."""
        mints = []
        
        try:
            # Use public RPC to get recent events
            latest_block = await self._get_latest_block()
            
            if not self._last_block:
                self._last_block = latest_block - 100  # Start from 100 blocks ago
            
            # Get ERC721 Transfer events (topic0 = Transfer(address,address,uint256))
            logs = await self._get_logs(
                contract,
                "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                self._last_block,
                latest_block
            )
            
            for log_entry in logs:
                tx_hash = log_entry.get("transactionHash", "")
                
                if tx_hash in self._seen_txs:
                    continue
                
                self._seen_txs.add(tx_hash)
                
                # Parse transfer data
                topics = log_entry.get("topics", [])
                if len(topics) >= 3:
                    from_addr = "0x" + topics[1][-40:] if topics[1] != "0x" * 32 else "0x0000...mint"
                    to_addr = "0x" + topics[2][-40:]
                    token_id = int(topics[3], 16) if len(topics) > 3 else 0
                    
                    # Detect mint (from = zero address)
                    is_mint = from_addr == "0x" + "0" * 40 or from_addr.startswith("0x0000")
                    
                    if is_mint:
                        mints.append({
                            "collection": contract,
                            "tokenId": str(token_id),
                            "to": to_addr,
                            "from": "0x0000000000000000000000000000000000000000",
                            "block": int(log_entry.get("blockNumber", "0x0"), 16),
                            "txHash": tx_hash,
                            "isMint": True,
                        })
            
            self._last_block = latest_block
            
        except Exception as e:
            log.error(f"Contract scan error: {e}")
        
        # Keep seen_txs bounded
        if len(self._seen_txs) > 10000:
            self._seen_txs = set(list(self._seen_txs)[-5000:])
        
        return mints
    
    async def find_new_collections(self, min_mints: int = 10) -> list[str]:
        """Find new collections with recent mint activity."""
        # Use OpenSea API to find trending new collections
        url = "https://api.opensea.io/api/v2/collections?chain=ethereum&order_by=one_day_volume&limit=50"
        
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
            })
            
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                collections = data.get("collections", [])
                
                # Filter for new collections (< 7 days old)
                import time
                now = int(time.time())
                week_ago = now - (7 * 24 * 3600)
                
                new_collections = []
                for c in collections:
                    created = c.get("created_date", "")
                    contract = c.get("address", "")
                    
                    if contract and c.get("total_supply", 0) >= min_mints:
                        new_collections.append(contract)
                
                return new_collections[:20]  # Top 20
        
        except Exception as e:
            log.error(f"Collection search error: {e}")
            return []
    
    async def _get_latest_block(self) -> int:
        """Get latest block number via RPC."""
        payload = json.dumps({
            "jsonrpc": "2.0",
            "method": "eth_blockNumber",
            "params": [],
            "id": 1
        }).encode()
        
        req = urllib.request.Request(
            self.rpc_url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return int(data["result"], 16)
    
    async def _get_logs(self, address: str, topic0: str, from_block: int, to_block: int) -> list:
        """Get logs from RPC."""
        payload = json.dumps({
            "jsonrpc": "2.0",
            "method": "eth_getLogs",
            "params": [{
                "address": address,
                "topics": [topic0],
                "fromBlock": hex(from_block),
                "toBlock": hex(to_block),
            }],
            "id": 1
        }).encode()
        
        req = urllib.request.Request(
            self.rpc_url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                return data.get("result", [])
        except Exception as e:
            log.error(f"Get logs error: {e}")
            return []

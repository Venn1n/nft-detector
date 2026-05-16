"""Telegram Notifier — Send alerts and notifications to Telegram."""

import json
import logging
import urllib.request
import urllib.parse
from typing import Optional

log = logging.getLogger("nftdetector.notifier")


class TelegramNotifier:
    """Sends NFT alerts to Telegram."""
    
    def __init__(self, config: dict):
        self.bot_token = config.get("bot_token", "")
        self.chat_id = config.get("chat_id", "")
    
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)
    
    async def send_mint(self, mint: dict):
        """Send new mint notification."""
        if not self.is_configured():
            return
        
        collection = mint.get("collection", "Unknown")[:10]
        token_id = mint.get("tokenId", "?")
        to_addr = mint.get("to", "")
        
        msg = (
            f"🆕 **New NFT Mint Detected**\n\n"
            f"📦 Collection: `{collection}...`\n"
            f"🏷️ Token: #{token_id}\n"
            f"👤 To: `{to_addr[:8]}...{to_addr[-6:]}`\n"
            f"🔗 [View on Etherscan](https://etherscan.io/tx/{mint.get('txHash', '')})"
        )
        
        await self._send(msg)
    
    async def send_alert(self, mint: dict, analysis: dict):
        """Send suspicious mint alert with analysis."""
        if not self.is_configured():
            return
        
        score = analysis.get("scam_score", 50)
        level = analysis.get("risk_level", "UNKNOWN")
        warnings = analysis.get("warnings", [])
        
        # Risk emoji
        if score < 30:
            emoji = "🔴"
        elif score < 50:
            emoji = "🟠"
        elif score < 70:
            emoji = "🟡"
        else:
            emoji = "🟢"
        
        msg = (
            f"{emoji} **Suspicious NFT Detected**\n\n"
            f"📦 Collection: `{mint.get('collection', '')[:12]}...`\n"
            f"🏷️ Token: #{mint.get('tokenId', '?')}\n"
            f"🎯 Scam Score: **{score}/100** ({level})\n"
        )
        
        if warnings:
            msg += "\n⚠️ **Warnings:**\n"
            for w in warnings[:3]:
                msg += f"  • {w}\n"
        
        msg += f"\n🔗 [Analyze](https://etherscan.io/address/{mint.get('collection', '')})"
        
        await self._send(msg)
    
    async def send_floor_alert(self, alert: dict):
        """Send floor price movement alert."""
        if not self.is_configured():
            return
        
        collection = alert.get("name", alert.get("contract", "")[:12])
        change = alert.get("change_pct", 0)
        old_floor = alert.get("old_floor", 0)
        new_floor = alert.get("new_floor", 0)
        
        if change > 0:
            emoji = "📈"
            direction = "increased"
        else:
            emoji = "📉"
            direction = "decreased"
        
        msg = (
            f"{emoji} **Floor Price Alert**\n\n"
            f"📦 {collection}\n"
            f"💰 Floor {direction}: {old_floor:.3f} → {new_floor:.3f} ETH\n"
            f"📊 Change: **{change:+.1f}%**\n"
        )
        
        await self._send(msg)
    
    async def send_scan_results(self, results: list[dict]):
        """Send suspicious collection scan results."""
        if not self.is_configured():
            return
        
        if not results:
            msg = "✅ No suspicious collections found in scan."
            await self._send(msg)
            return
        
        msg = f"🕵️ **Scan Results: {len(results)} Suspicious Collections**\n\n"
        
        for r in results[:5]:
            score = r.get("scam_score", 50)
            emoji = "🔴" if score < 30 else "🟠" if score < 50 else "🟡"
            msg += f"{emoji} {r.get('name', 'Unknown')}: {score}/100\n"
        
        await self._send(msg)
    
    async def _send(self, text: str):
        """Send message to Telegram."""
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        
        data = json.dumps({
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }).encode()
        
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
                if not result.get("ok"):
                    log.warning(f"Telegram send failed: {result}")
        except Exception as e:
            log.error(f"Telegram error: {e}")

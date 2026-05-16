"""Scam Detector — Analyzes NFT collections for rug pull indicators."""

import logging
from collections import Counter
from typing import Optional

log = logging.getLogger("nftdetector.detector")


class ScamDetector:
    """Detects potential scams and rug pulls in NFT collections."""
    
    # Scoring weights (total = 100)
    WEIGHTS = {
        "holder_concentration": 25,
        "mint_distribution": 20,
        "royalty_missing": 15,
        "social_links": 15,
        "contract_verified": 10,
        "transfer_pattern": 15,
    }
    
    def analyze(
        self,
        collection: dict,
        holders: list[dict],
        transfers: list[dict],
    ) -> dict:
        """Full scam analysis. Returns score (0-100, higher = safer) and warnings."""
        
        warnings = []
        scores = {}
        
        # 1. Holder Concentration
        holder_score = self._check_holder_concentration(holders, warnings)
        scores["holder_concentration"] = holder_score
        
        # 2. Mint Distribution
        mint_score = self._check_mint_distribution(holders, warnings)
        scores["mint_distribution"] = mint_score
        
        # 3. Royalty/Social presence
        social_score = self._check_social_links(collection, warnings)
        scores["social_links"] = social_score
        scores["royalty_missing"] = 50 if collection.get("seller_fee_bps", 0) > 0 else 0
        
        # 4. Contract verification (if available)
        scores["contract_verified"] = 100  # Default to verified, updated if checked
        
        # 5. Transfer pattern (wash trading)
        transfer_score = self._check_transfer_pattern(transfers, warnings)
        scores["transfer_pattern"] = transfer_score
        
        # Calculate weighted total
        total_score = 0
        total_weight = 0
        for factor, weight in self.WEIGHTS.items():
            total_score += scores.get(factor, 50) * weight
            total_weight += weight
        
        final_score = int(total_score / total_weight) if total_weight else 50
        
        # Determine risk level
        if final_score >= 70:
            level = "LOW RISK"
        elif final_score >= 50:
            level = "MEDIUM RISK"
        elif final_score >= 30:
            level = "HIGH RISK"
        else:
            level = "CRITICAL"
        
        return {
            "score": final_score,
            "level": level,
            "warnings": warnings,
            "breakdown": scores,
        }
    
    def quick_score(self, holders: list[dict] = None, transfers: list[dict] = None) -> int:
        """Quick scoring with minimal data."""
        score = 50  # Start neutral
        
        if holders:
            unique = len(set(h.get("address") for h in holders))
            total = sum(h.get("quantity", 1) for h in holders)
            
            if total > 0:
                concentration = max(h.get("quantity", 0) for h in holders) / total
                if concentration > 0.3:
                    score -= 20  # High concentration
                elif concentration < 0.1:
                    score += 10  # Good distribution
        
        return max(0, min(100, score))
    
    def _check_holder_concentration(self, holders: list[dict], warnings: list) -> int:
        """Check if holdings are concentrated among few wallets."""
        if not holders:
            return 50  # Unknown
        
        # Sort by quantity
        sorted_holders = sorted(holders, key=lambda h: h.get("quantity", 0), reverse=True)
        total_tokens = sum(h.get("quantity", 1) for h in holders)
        
        if total_tokens == 0:
            return 50
        
        # Top 10 holder percentage
        top_10 = sum(h.get("quantity", 0) for h in sorted_holders[:10])
        top_10_pct = (top_10 / total_tokens) * 100
        
        if top_10_pct > 70:
            warnings.append(f"Top 10 wallets hold {top_10_pct:.1f}% of supply")
            return 10
        elif top_10_pct > 50:
            warnings.append(f"Top 10 wallets hold {top_10_pct:.1f}% of supply")
            return 30
        elif top_10_pct > 30:
            return 60
        else:
            return 90
    
    def _check_mint_distribution(self, holders: list[dict], warnings: list) -> int:
        """Check if mints are distributed or concentrated (bot activity)."""
        if not holders:
            return 50
        
        # Calculate distribution metrics
        quantities = [h.get("quantity", 0) for h in holders]
        if not quantities:
            return 50
        
        unique_holders = len(holders)
        total_supply = sum(quantities)
        
        if total_supply == 0:
            return 50
        
        # Average tokens per holder
        avg = total_supply / unique_holders if unique_holders else 0
        
        # Check for many holders with exactly same amount (bot pattern)
        distribution = Counter(quantities)
        most_common_count = distribution.most_common(1)[0][1] if distribution else 0
        bot_ratio = most_common_count / unique_holders if unique_holders else 0
        
        if bot_ratio > 0.5 and unique_holders > 100:
            warnings.append(f"Possible bot minting pattern ({bot_ratio:.0%} holders have same amount)")
            return 20
        elif avg > 20:
            warnings.append(f"High average tokens per holder ({avg:.1f})")
            return 40
        else:
            return 80
    
    def _check_social_links(self, collection: dict, warnings: list) -> int:
        """Check for social presence and legitimacy indicators."""
        score = 0
        
        # External website
        if collection.get("external_url"):
            score += 30
        else:
            warnings.append("No website linked")
        
        # Twitter
        if collection.get("twitter"):
            score += 30
        else:
            warnings.append("No Twitter linked")
        
        # Discord
        if collection.get("discord"):
            score += 20
        
        # Description
        if collection.get("description") and len(collection["description"]) > 50:
            score += 20
        else:
            warnings.append("Minimal or no description")
        
        return min(100, score)
    
    def _check_transfer_pattern(self, transfers: list[dict], warnings: list) -> int:
        """Detect wash trading and suspicious transfer patterns."""
        if not transfers or len(transfers) < 5:
            return 50  # Not enough data
        
        # Check for circular transfers (A→B→A)
        transfer_pairs = set()
        circular_count = 0
        
        for t in transfers:
            fr = t.get("from", "").lower()
            to = t.get("to", "").lower()
            
            if fr and to:
                pair = (fr, to)
                reverse = (to, fr)
                
                if reverse in transfer_pairs:
                    circular_count += 1
                
                transfer_pairs.add(pair)
        
        # Check for same wallet doing many transfers
        from_counts = Counter(t.get("from", "") for t in transfers)
        max_from = max(from_counts.values()) if from_counts else 0
        
        # Scoring
        score = 100
        
        if circular_count > len(transfers) * 0.2:
            warnings.append(f"High circular transfer rate ({circular_count} detected)")
            score -= 40
        
        if max_from > len(transfers) * 0.3:
            warnings.append(f"One wallet initiated {max_from} transfers")
            score -= 30
        
        return max(0, score)
    
    def holder_breakdown(self, holders: list[dict]) -> dict:
        """Generate holder distribution breakdown."""
        if not holders:
            return {}
        
        quantities = [h.get("quantity", 0) for h in holders]
        total = sum(quantities)
        
        if total == 0:
            return {}
        
        sorted_q = sorted(quantities, reverse=True)
        
        return {
            "total_holders": len(holders),
            "total_tokens": total,
            "avg_per_holder": total / len(holders),
            "top_holder_pct": (sorted_q[0] / total * 100) if sorted_q else 0,
            "top_10_pct": (sum(sorted_q[:10]) / total * 100),
            "whales": sum(1 for q in quantities if q > total * 0.01),  # >1% each
        }

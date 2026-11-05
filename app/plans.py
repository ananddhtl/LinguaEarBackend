"""What each plan includes. The trial counts as Standard."""
from dataclasses import dataclass

from app.config import settings

TIERS = ("standard", "pro")


@dataclass(frozen=True)
class PlanLimits:
    analyze: int
    game: int
    scan: int
    transcribe: int
    saved_phrases: int

    def daily(self, kind: str) -> int:
        return getattr(self, kind)


def limits_for(tier: str) -> PlanLimits:
    if tier == "pro":
        return PlanLimits(
            analyze=settings.pro_limit_analyze_per_day,
            game=settings.pro_limit_game_per_day,
            scan=settings.pro_limit_scan_per_day,
            transcribe=settings.pro_limit_transcribe_per_day,
            saved_phrases=settings.pro_max_saved_phrases,
        )
    return PlanLimits(
        analyze=settings.limit_analyze_per_day,
        game=settings.limit_game_per_day,
        scan=settings.limit_scan_per_day,
        transcribe=settings.limit_transcribe_per_day,
        saved_phrases=settings.max_saved_phrases,
    )


def price_id(tier: str) -> str | None:
    return {"standard": settings.stripe_price_standard, "pro": settings.stripe_price_pro}.get(tier)


def tier_for_price(price: str | None) -> str | None:
    for tier in TIERS:
        if price and price == price_id(tier):
            return tier
    return None


def label(tier: str) -> str:
    return settings.price_label_pro if tier == "pro" else settings.price_label_standard

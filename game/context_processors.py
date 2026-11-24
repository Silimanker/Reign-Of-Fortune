from __future__ import annotations

from decimal import Decimal

from .models import Player
from .wallet import ensure_player


def realm(request):
    """Balance + bonus state, available on every template."""
    try:
        player = ensure_player()
    except Exception:  # pragma: no cover - no migrations yet
        return {"player": None, "spirit_stones": Decimal("0.00")}
    return {
        "player": player,
        "spirit_stones": player.spirit_stones,
    }

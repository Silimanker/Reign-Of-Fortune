"""Shared wallet helpers kept separate from the ORM definitions."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction as db_transaction

from .models import Player, Transaction

STARTING_STONES = Decimal("5000.00")
CASHOUT_MIN = Decimal("100.00")


def ensure_player() -> Player:
    player, _ = Player.objects.get_or_create(
        pk=1,
        defaults={"name": "Cultivator", "spirit_stones": STARTING_STONES},
    )
    return player


def record(player: Player, kind: str, amount, note: str = "",
           status: str = Transaction.Status.DONE) -> Transaction:
    return Transaction.objects.create(
        player=player,
        kind=kind,
        amount=Decimal(amount).quantize(Decimal("0.01")),
        balance_after=player.spirit_stones,
        note=note,
        status=status,
    )


def top_up(player: Player, amount: Decimal, method: str) -> Transaction:
    amount = Decimal(amount).quantize(Decimal("0.01"))
    with db_transaction.atomic():
        player.spirit_stones += amount
        player.save(update_fields=["spirit_stones", "updated_at"])
        return record(player, Transaction.Kind.TOPUP, amount,
                      note=f"{method} - Spirit Stone top-up")


def cash_out(player: Player, amount: Decimal, method: str) -> Transaction:
    amount = Decimal(amount).quantize(Decimal("0.01"))
    with db_transaction.atomic():
        if amount < CASHOUT_MIN:
            raise ValueError(f"Minimum cashout is {CASHOUT_MIN:,.2f} Spirit Stones.")
        if amount > player.spirit_stones:
            raise ValueError("That is more than your Spatial Ring holds.")
        player.spirit_stones -= amount
        player.save(update_fields=["spirit_stones", "updated_at"])
        return record(player, Transaction.Kind.CASHOUT, amount,
                      note=f"{method} - Peso withdrawal requested",
                      status=Transaction.Status.PENDING)


def reset_demo() -> Player:
    """Fresh cultivator, fresh ledger. Handy mid-demo."""
    Player.objects.all().delete()
    return ensure_player()

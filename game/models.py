from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.utils import timezone


class Player(models.Model):
    """
    The single demo cultivator.

    Deliberately flat so the schema can be lifted into Supabase as-is
    (table: players) with no relational rework.
    """

    name = models.CharField(max_length=60, default="Cultivator")
    spirit_stones = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("5000.00"))
    fortune_favor = models.PositiveSmallIntegerField(default=0)  # 0-100, loss meter
    charm_active = models.BooleanField(default=False)
    free_spins = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.spirit_stones} SS)"

    @property
    def favor_percent(self) -> int:
        return min(100, self.fortune_favor)

    @property
    def php(self) -> Decimal:
        """1 Spirit Stone = 1 Philippine Peso, per the economy spec."""
        return self.spirit_stones


class Transaction(models.Model):
    """Append-only ledger. Every balance change lands here."""

    class Kind(models.TextChoices):
        TOPUP = "topup", "Top-Up"
        CASHOUT = "cashout", "Cashout"
        STAKE = "stake", "Stake"
        WIN = "win", "Win"
        BONUS = "bonus", "Bonus"
        ADJUST = "adjust", "Adjustment"

    class Status(models.TextChoices):
        DONE = "done", "Completed"
        PENDING = "pending", "Pending"

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="transactions")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DONE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    note = models.CharField(max_length=140, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.amount}"


class GameRound(models.Model):
    """One completed slot spin and a compact summary of any bonus feature."""

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="rounds")
    mode_slug = models.CharField(max_length=40)
    mode_name = models.CharField(max_length=60)
    bet_type = models.CharField(max_length=16)
    selection = models.CharField(max_length=32)
    selection_label = models.CharField(max_length=60)

    stake = models.DecimalField(max_digits=12, decimal_places=2)
    multiplier = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0"))
    payout = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    bonus_multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("1"))

    result_key = models.CharField(max_length=40)
    result_name = models.CharField(max_length=60)
    landed_deg = models.FloatField(default=0.0)

    is_free = models.BooleanField(default=False)
    is_win = models.BooleanField(default=False)
    cascade_count = models.PositiveSmallIntegerField(default=0)
    free_spins_won = models.PositiveSmallIntegerField(default=0)
    feature = models.CharField(max_length=40, blank=True)
    feature_outcome = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.mode_name} -> {self.result_name} ({'win' if self.is_win else 'loss'})"

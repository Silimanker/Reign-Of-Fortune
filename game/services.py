"""Slot spin service: validation, payout, ledger, bonus features.

Replaces the old roulette-based services.py entirely.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import transaction as db_transaction

from . import slots
from .models import GameRound, Player, Transaction
from .wallet import record

TransactionKind = Transaction.Kind

CENT = Decimal("0.01")

FAVOR_STEP = 8         # fortune-favor fills faster on the slot (more spins per session)
FAVOR_MAX  = 100
FAVOR_BONUS = Decimal("0.25")   # 25 % bonus payout on next hit when meter is full


class SpinError(Exception):
    """Raised for anything the player is not allowed to do."""


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def _validate(mode: slots.Mode, stake, player: Player) -> Decimal:
    try:
        stake = _money(stake)
    except (InvalidOperation, TypeError, ValueError):
        raise SpinError("Enter a stake.")
    if not stake.is_finite() or stake <= 0:
        raise SpinError("Stake must be greater than zero.")
    if not (Decimal(mode.min_stake) <= stake <= Decimal(mode.max_stake)):
        raise SpinError(
            f"{mode.name} takes {mode.min_stake:,} to {mode.max_stake:,} Spirit Stones."
        )
    if stake > player.spirit_stones:
        raise SpinError("Your Spatial Ring cannot cover that stake.")
    return stake


# --------------------------------------------------------------------------- #
# Spin → result → JSON response
# --------------------------------------------------------------------------- #

def perform_spin(player: Player, mode: slots.Mode, stake) -> dict:
    with db_transaction.atomic():
        locked = Player.objects.select_for_update().get(pk=player.pk)
        stake = _validate(mode, stake, locked)

        result = slots.spin(mode, float(stake))
        total_payout = _money(result["total"])
        feat = result["feature"]
        is_win = result["win"]
        favor_ready = locked.fortune_favor >= FAVOR_MAX

        favor_boost = Decimal("0.00")
        if is_win and favor_ready:
            favor_boost = (total_payout * FAVOR_BONUS).quantize(CENT, ROUND_HALF_UP)
            total_payout += favor_boost

        # Deduct stake
        locked.spirit_stones = _money(locked.spirit_stones - stake)
        record(locked, TransactionKind.STAKE, stake,
               note=f"{mode.name} – spin")

        # Keep the feature trigger's ledger entry separate without double-counting it.
        trigger_pay = min(
            total_payout,
            _money(feat.get("triggerPay", 0)) if feat else Decimal("0.00"),
        )
        regular_payout = total_payout - trigger_pay
        if regular_payout > 0:
            locked.spirit_stones = _money(locked.spirit_stones + regular_payout)
            record(locked, TransactionKind.WIN, regular_payout,
                   note=_win_note(mode, result, feat))

        if trigger_pay > 0:
            locked.spirit_stones = _money(locked.spirit_stones + trigger_pay)
            record(locked, TransactionKind.BONUS, trigger_pay,
                   note=f"Heavenly Tribulation – {feat['count']} scatters")

        # Fortune Favor meter
        if favor_ready:
            locked.fortune_favor = 0
        elif is_win:
            locked.fortune_favor = 0
        else:
            locked.fortune_favor = min(FAVOR_MAX, locked.fortune_favor + FAVOR_STEP)

        locked.save(update_fields=[
            "spirit_stones", "fortune_favor", "updated_at",
        ])

        # Persist a light summary to GameRound
        first_grid = result["base"]["initial_grid"]
        first_sym = first_grid[0] if first_grid else "spirit_leaf"
        feature_outcome = {}
        free_spins_won = 0
        cascade_count = result["base"]["cascades"]
        if feat:
            free_spins_won = feat["granted"]
            cascade_count += sum(spin["cascades"] for spin in feat["spins"])
            feature_outcome = {
                "trigger_count": feat["count"],
                "granted": feat["granted"],
                "played": feat["played"],
                "trigger_payout": feat["triggerPay"],
                "bonus_payout": feat["total"],
                "best_multiplier": feat["bestMult"],
                "spins": [
                    {"payout": spin["payout"], "cascades": spin["cascades"],
                     "multiplier": spin["mult"]}
                    for spin in feat["spins"]
                ],
            }
        GameRound.objects.create(
            player=locked,
            mode_slug=mode.slug,
            mode_name=mode.name,
            bet_type="scatter",
            selection="grid",
            selection_label="6×5 Scatter Grid",
            stake=stake,
            multiplier=Decimal("0"),
            payout=total_payout,
            bonus_multiplier=Decimal(str(result["base"]["steps"][0]["mult"]))
                if result["base"]["steps"] else Decimal("1"),
            result_key=first_sym,
            result_name=slots.SYMBOL_BY_KEY.get(first_sym, slots.SCATTERS[0]).name,
            landed_deg=0.0,
            is_free=False,
            is_win=is_win,
            cascade_count=cascade_count,
            free_spins_won=free_spins_won,
            feature="heavenly_tribulation" if feat else "",
            feature_outcome=feature_outcome,
        )

        player = locked

    return _build_response(player, mode, stake, result, feat,
                           total_payout, favor_boost, favor_ready)


def _win_note(mode: slots.Mode, result: dict, feat) -> str:
    cascades = result["base"]["cascades"]
    parts = [f"{mode.name}"]
    if cascades:
        parts.append(f"{cascades} cascade{'s' if cascades != 1 else ''}")
    if feat:
        parts.append(f"Heavenly Tribulation ×{feat['played']} spins")
    return " – ".join(parts)


def _build_response(player: Player, mode: slots.Mode,
                    stake: Decimal, result: dict, feat,
                    total_payout: Decimal, favor_boost: Decimal,
                    favor_was_full: bool) -> dict:
    """Build the JSON payload returned to the browser."""
    base  = result["base"]
    steps = base["steps"]

    # Serialise each cascade step for the frontend animator
    cascade_data = []
    for step in steps:
        cascade_data.append({
            "grid": step["grid"],
            "cells": step["cells"],
            "wins": step["wins"],
            "mult": step["mult"],
            "payout": step["payout"],
        })

    feature_data = None
    if feat:
        # Summarise bonus (full spin list is large; just send the useful bits)
        feature_data = {
            "count":       feat["count"],
            "granted":     feat["granted"],
            "played":      feat["played"],
            "triggerPay":  feat["triggerPay"],
            "total":       feat["total"],
            "bestMult":    feat["bestMult"],
            "spinSummary": [
                {"payout": s["payout"], "cascades": s["cascades"], "mult": s["mult"]}
                for s in feat["spins"]
            ],
        }

    scatter_count = base["scatters"]

    # Win-banner message
    if result["win"]:
        if feat:
            msg = (f"Heavenly Tribulation! {feat['granted']} free spins, "
                   f"best multiplier {feat['bestMult']:.1f}×.")
        elif base["cascades"] > 1:
            msg = f"{base['cascades']} cascades — fortune builds on fortune."
        else:
            msg = "The mountain yields its bounty."
    elif scatter_count >= 2:
        msg = f"{scatter_count} seals glow — one more and the gates open."
    else:
        msg = "The cultivator endures."

    if favor_was_full and result["win"]:
        msg += " Heaven's Favor answers the streak."

    return {
        "ok":           True,
        "win":          result["win"],
        "stake":        str(stake),
        "payout":       str(total_payout),
        "favorBoost":   str(favor_boost),
        "scatters":     scatter_count,
        "cascades":     base["cascades"],
        "grid":         base["final_grid"],
        "steps":        cascade_data,
        "feature":      feature_data,
        "message":      msg,
        "balance":      str(player.spirit_stones),
        "fortuneFavor": player.favor_percent,
    }

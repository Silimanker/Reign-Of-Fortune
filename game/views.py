from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from . import slots, services, wallet
from .models import GameRound, Transaction


# --------------------------------------------------------------------------- #
# Screens
# --------------------------------------------------------------------------- #

@require_GET
def splash(request):
    return render(request, "game/splash.html")


@require_GET
def menu(request):
    player = wallet.ensure_player()
    recent = list(GameRound.objects.filter(player=player)[:6])
    return render(request, "game/menu.html", {
        "player": player,
        "modes": slots.MODES,
        "recent": recent,
        "pending_cashout": Transaction.objects.filter(
            player=player, kind=Transaction.Kind.CASHOUT,
            status=Transaction.Status.PENDING,
        ).first(),
    })


@require_GET
def topup(request):
    return render(request, "game/topup.html", {
        "presets": (100, 500, 1000, 5000, 10000),
        "methods": ("GCash", "Maya", "GrabPay", "Bank Transfer"),
    })


@require_POST
def topup_submit(request):
    player = wallet.ensure_player()
    custom = (request.POST.get("custom") or "").strip()
    raw = custom or request.POST.get("amount", "0")
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        amount = Decimal("0")

    if amount < 100 or amount > 100_000:
        messages.error(request, "Top-ups run from 100 to 100,000 Spirit Stones.")
        return redirect("game:topup")

    method = request.POST.get("method", "GCash")
    txn = wallet.top_up(player, amount, method)
    messages.success(
        request,
        f"{txn.amount:,.2f} Spirit Stones credited. Ring now holds "
        f"{player.spirit_stones:,.2f} SS.",
    )
    return redirect("game:ring")


@require_GET
def spatial_ring(request):
    player = wallet.ensure_player()
    return render(request, "game/ring.html", {
        "player": player,
        "transactions": Transaction.objects.filter(player=player)[:60],
        "cashout_min": wallet.CASHOUT_MIN,
        "methods": ("GCash", "Maya", "Bank Transfer"),
    })


@require_POST
def cashout_submit(request):
    player = wallet.ensure_player()
    try:
        amount = Decimal(request.POST.get("amount", "0"))
    except InvalidOperation:
        amount = Decimal("0")

    method = request.POST.get("method", "GCash")
    try:
        txn = wallet.cash_out(player, amount, method)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("game:ring")

    messages.success(
        request,
        f"Cashout of {txn.amount:,.2f} SS ({txn.amount:,.2f} PHP) queued for {method}.",
    )
    return redirect("game:ring")


@require_GET
def modes(request):
    return render(request, "game/modes.html", {
        "modes_info": [
            {"mode": m}
            for m in slots.MODES
        ],
    })


@require_GET
def slot_screen(request, slug):
    mode = slots.get_mode(slug)
    if mode is None:
        return redirect("game:modes")

    player = wallet.ensure_player()

    config = {
        "spinUrl": reverse("game:spin"),
        "mode": {
            "slug":    mode.slug,
            "name":    mode.name,
            "sect":    mode.sect,
            "risk":    mode.risk,
            "rtp":     mode.rtp,
            "edge":    mode.edge,
            "min":     mode.min_stake,
            "max":     mode.max_stake,
            "default": mode.default_stake,
        },
        "scatterMin": slots.SCATTER_MIN,
        "symbols": [
            {
                "key":   s.key,
                "name":  s.name,
                "tier":  s.tier,
                "icon":  s.url,
                "glyph": s.glyph,
                "color": s.color,
                "pays":  list(s.pays),
            }
            for s in slots.SYMBOLS
        ],
        "player": {
            "balance":       float(player.spirit_stones),
            "fortuneFavor":  player.favor_percent,
        },
    }

    return render(request, "game/slots.html", {
        "mode":        mode,
        "config_json": json.dumps(config),
        "recent":      list(GameRound.objects.filter(player=player)[:8]),
        "stake_steps": _stake_steps(mode, player),
        "symbols":     slots.SYMBOLS,
        "scatter_min": slots.SCATTER_MIN,
        "player":      player,
    })


def _stake_steps(mode, player) -> list[tuple[str, int]]:
    balance = int(player.spirit_stones)
    candidates = [mode.min_stake, mode.max_stake // 4, mode.max_stake // 2, mode.max_stake]
    if balance < mode.min_stake:
        return [(f"{mode.min_stake:,}", mode.min_stake)]
    steps, seen = [], set()
    for value in candidates + [balance]:
        value = max(mode.min_stake, min(value, mode.max_stake, balance))
        if value > 0 and value not in seen:
            seen.add(value)
            steps.append((f"{value:,}", value))
    return steps[:4]


@require_GET
def paytable(request):
    slug = request.GET.get("mode", slots.MODES[0].slug)
    mode = slots.get_mode(slug) or slots.MODES[0]

    sym_stats   = slots.symbol_stats(mode)
    scat_stats  = slots.scatter_stats(mode)
    total_return = sum(r["return_pct"] for r in sym_stats)

    return render(request, "game/paytable.html", {
        "mode":         mode,
        "modes":        slots.MODES,
        "sym_stats":    sym_stats,
        "scat_stats":   scat_stats,
        "total_return": round(total_return, 2),
        "house_edge":   round(100 - mode.rtp * 100, 1),
        "sim_rtp":      round(mode.sim_rtp * 100, 2),
        "sim_hit":      round(mode.sim_hit_rate * 100, 1),
        "sim_profit":    round(mode.sim_profit_rate * 100, 1),
        "sim_feat":     mode.feature_odds,
        "sim_avg_win":  round(mode.sim_avg_win, 2),
        "ladder_syms":  slots.LADDER,
        "scatter_syms": slots.SCATTERS,
        "royal_syms":   slots.ROYALS,
        "pay_tiers":    slots.PAY_TIERS,
        "scatter_min":  slots.SCATTER_MIN,
    })


@require_POST
def reset_demo(request):
    wallet.reset_demo()
    messages.success(request, "Realm reset: 5,000 Spirit Stones, clean ledger.")
    return redirect("game:menu")


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #

@require_POST
def spin(request):
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Malformed request."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"ok": False, "error": "A spin request must be an object."}, status=400)

    mode = slots.get_mode(str(payload.get("mode", "")))
    if mode is None:
        return JsonResponse({"ok": False, "error": "Unknown table."}, status=400)

    player = wallet.ensure_player()
    try:
        result = services.perform_spin(
            player,
            mode,
            payload.get("stake", 0),
        )
    except services.SpinError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    return JsonResponse(result)

"""
Reign of Fortune - scatter-pay slot engine.

Grid: 6 columns x 5 rows = 30 cells, every cell drawn independently from a
weighted symbol distribution (the model Sweet Bonanza / Gates of Olympus use).

A symbol pays wherever it appears, as long as 8 or more of it are on screen::

    8-9   -> pays[0]
    10-11 -> pays[1]
    12+   -> pays[2]

Winning cells are removed, the columns collapse, fresh symbols drop in and the
grid is scored again. That cascade repeats until nothing pays.

House margin lives in the *reel distribution*, never in the paytable. Each
table owns one number - ``royal_mass`` - the share of the 30 cells spent on
the four script tiles (J Q K A) that barely pay. Push it up and the expensive
ladder symbols get rare; push it down and they flood the grid. The tuner
(``scripts/tune_slots.py``) bisects that one number per table until the
measured return lands on the table's RTP target.

Four or more scatters (Yin-Yang Emblem + Heavenly Lightning Seal, counted
across the whole cascade chain) open the Heavenly Tribulation: 10-25 free
spins where a multiplier grows on every cascade and the Flying Sword turns
wild for the rest of the bonus.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from django.templatetags.static import static

# --------------------------------------------------------------------------- #
# Grid geometry
# --------------------------------------------------------------------------- #

COLS = 6
ROWS = 5
CELLS = COLS * ROWS
MAX_CASCADES = 8

PAY_TIER_8 = "8-9"
PAY_TIER_10 = "10-11"
PAY_TIER_12 = "12+"
PAY_TIERS = (PAY_TIER_8, PAY_TIER_10, PAY_TIER_12)

TIER_ROYAL = "royal"
TIER_LOW = "low"
TIER_HIGH = "high"
TIER_SPECIAL = "special"

TIER_LABELS = {
    TIER_ROYAL: "Script Tiles",
    TIER_LOW: "Spiritual Herbs",
    TIER_HIGH: "Treasures & Artifacts",
    TIER_SPECIAL: "Bonus",
}

SCATTER_KEY = "dao_emblem"
TRIGGER_KEY = "heavenly_tribulation"
WILD_KEY = "flying_sword"

SCATTER_MIN = 4            # 4+ anywhere opens the bonus
BONUS_MULT_STEP = 1        # multiplier growth per cascade during the bonus
BONUS_MULT_CAP = 5
BONUS_RETRIGGER = 5        # extra spins when 4+ scatters land inside the bonus
BONUS_MAX_SPINS = 40

# Scatter mass is a design constant: it fixes how often the bonus opens.
SCATTER_MASS = 0.032
SCATTER_MIX = {SCATTER_KEY: 21.0, TRIGGER_KEY: 11.0}


@dataclass(frozen=True)
class Symbol:
    key: str
    name: str
    tier: str
    color: str
    pays: tuple[float, float, float]      # 8-9, 10-11, 12+
    icon: str = ""                        # png filename, empty for script tiles
    glyph: str = ""                       # rendered instead of an icon
    note: str = ""

    @property
    def url(self) -> str:
        return static(f"game/icons/{self.icon}") if self.icon else ""

    @property
    def scatter(self) -> bool:
        return self.tier == TIER_SPECIAL

    @property
    def pays_anything(self) -> bool:
        return not self.scatter


# The four script tiles are pure weight: they keep the ladder above them
# rare enough to be affordable, while still paying enough to feel alive.
ROYALS: tuple[Symbol, ...] = (
    Symbol("royal_j", "Script J", TIER_ROYAL, "#737b8c", (0.4, 1.0, 2.5), "",
           "J", "The lowest hand on the mountain."),
    Symbol("royal_q", "Script Q", TIER_ROYAL, "#8a93a6", (0.5, 1.2, 3.0), "",
           "Q", "A queen's favour, at a queen's price."),
    Symbol("royal_k", "Script K", TIER_ROYAL, "#a2a9b7", (0.6, 1.5, 4.0), "",
           "K", "Kings pay, but they are seldom seen in force."),
    Symbol("royal_a", "Script A", TIER_ROYAL, "#c8cfdb", (0.8, 2.0, 5.0), "",
           "A", "The strongest of the four script tiles."),
)

# The eight ladder symbols, with the paytable exactly as written in the
# game document (values are multiples of the stake, in Spirit Stones).
LADDER: tuple[Symbol, ...] = (
    Symbol("spirit_leaf", "Spirit Leaf", TIER_LOW, "#155e46", (2.5, 7.5, 20.0),
           "spirit_leaf.png", "", "A common herb. Cheap, constant, comforting."),
    Symbol("gathering_flower", "Gathering Flower", TIER_LOW, "#1a6b51", (4.0, 10.0, 30.0),
           "gathering_flower.png", "", "Lotus that drinks ambient Qi."),
    Symbol("jade_bamboo", "Jade Bamboo", TIER_LOW, "#1f785c", (5.0, 12.5, 40.0),
           "jade_bamboo.png", "", "Bamboo hardened by a century of mist."),
    Symbol("demon_core", "Demon Core", TIER_LOW, "#248567", (8.0, 15.0, 50.0),
           "demon_core.png", "", "Cracked open from a slain beast."),
    Symbol("talisman", "Talisman", TIER_HIGH, "#8a6414", (15.0, 30.0, 100.0),
           "talisman.png", "", "Yellow paper, black ink, one warning."),
    Symbol("immortal_pill", "Immortal Pill", TIER_HIGH, "#9c7219", (20.0, 50.0, 150.0),
           "immortal_pill.png", "", "Alchemy furnace output, nine refinements."),
    Symbol("flying_sword", "Flying Sword", TIER_HIGH, "#ae801e", (25.0, 100.0, 250.0),
           "flying_sword.png", "", "A blade that answers to intent alone. Wild during the bonus."),
    Symbol("phoenix_feather", "Phoenix Feather", TIER_HIGH, "#c08e23", (100.0, 250.0, 500.0),
           "phoenix_feather.png", "", "One feather. One ash-fall. One fortune."),
)

SCATTERS: tuple[Symbol, ...] = (
    Symbol("dao_emblem", "Yin-Yang Emblem", TIER_SPECIAL, "#5b3fa0", (0.0, 0.0, 0.0),
           "dao_emblem.png", "", "Bonus scatter. 4 or more opens the Heavenly Tribulation."),
    Symbol("heavenly_tribulation", "Heavenly Tribulation", TIER_SPECIAL, "#6d4eb8", (0.0, 0.0, 0.0),
           "heavenly_tribulation.png", "", "Lightning seal. Counted with the emblem."),
)

SYMBOLS: tuple[Symbol, ...] = ROYALS + LADDER + SCATTERS
SYMBOL_BY_KEY: dict[str, Symbol] = {s.key: s for s in SYMBOLS}
GRID_KEYS: tuple[str, ...] = tuple(s.key for s in SYMBOLS)

PAYS_SYMBOLS: tuple[Symbol, ...] = ROYALS + LADDER
BONUS_SYMBOLS: tuple[Symbol, ...] = SCATTERS

# Relative reel shape. Fixed by design; only the group masses move.
ROYAL_SHAPE = {"royal_j": 30.0, "royal_q": 28.0, "royal_k": 26.0, "royal_a": 24.0}
LADDER_SHAPE = {
    "spirit_leaf": 26.0, "gathering_flower": 19.0, "jade_bamboo": 15.0,
    "demon_core": 12.0, "talisman": 9.0, "immortal_pill": 7.0,
    "flying_sword": 5.0, "phoenix_feather": 3.0,
}


# --------------------------------------------------------------------------- #
# Reel weights
# --------------------------------------------------------------------------- #

def reel_weights(royal_mass: float) -> tuple[float, ...]:
    """Cell probability for every symbol, aligned with ``GRID_KEYS``.

    ``royal_mass`` is the share of the grid spent on script tiles; the ladder
    takes everything left over after the scatter mass is reserved.
    """
    ladder_mass = 1.0 - SCATTER_MASS - royal_mass
    raw: dict[str, float] = {}

    r_sum = sum(ROYAL_SHAPE.values())
    for k, w in ROYAL_SHAPE.items():
        raw[k] = royal_mass * w / r_sum

    l_sum = sum(LADDER_SHAPE.values())
    for k, w in LADDER_SHAPE.items():
        raw[k] = ladder_mass * w / l_sum

    s_sum = sum(SCATTER_MIX.values())
    for k, w in SCATTER_MIX.items():
        raw[k] = SCATTER_MASS * w / s_sum

    return tuple(raw[k] for k in GRID_KEYS)


def draw_grid(weights: tuple[float, ...], count: int = CELLS) -> list[str]:
    return random.choices(GRID_KEYS, weights=weights, k=count)


# --------------------------------------------------------------------------- #
# Modes
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Mode:
    slug: str
    name: str
    sect: str
    risk: str
    rtp: float
    min_stake: int
    max_stake: int
    description: str
    royal_mass: float = 0.30            # tuned per table, see scripts/tune_slots.py

    # Filled in by the tuner: measured numbers quoted on the paytable page.
    sim_rtp: float = 0.0
    sim_hit_rate: float = 0.0
    sim_profit_rate: float = 0.0
    sim_feature_rate: float = 0.0
    sim_avg_win: float = 0.0

    @property
    def edge(self) -> float:
        return round((1 - self.rtp) * 100, 1)

    @property
    def rtp_percent(self) -> float:
        return round(self.rtp * 100, 1)

    @property
    def default_stake(self) -> int:
        return max(self.min_stake, min(100, self.max_stake))

    @property
    def sim_percent(self) -> float:
        return round(self.sim_rtp * 100, 2)

    @property
    def sim_hit_percent(self) -> float:
        return round(self.sim_hit_rate * 100, 1)

    @property
    def sim_profit_percent(self) -> float:
        return round(self.sim_profit_rate * 100, 1)

    @property
    def feature_odds(self) -> str:
        if self.sim_feature_rate <= 0:
            return "-"
        return f"1 in {round(1 / self.sim_feature_rate)}"

    @property
    def weights(self) -> tuple[float, ...]:
        return reel_weights(self.royal_mass)


MODES: tuple[Mode, ...] = (
    Mode("green-lotus", "Green Lotus Hall", "Outer Sect", "Gentle", 0.96, 10, 500,
         "Low stakes, the kindest return on the mountain. Where new disciples "
         "learn that fortune can be cultivated.",
         royal_mass=0.62700, sim_rtp=0.9589, sim_hit_rate=0.358,
         sim_profit_rate=0.1439, sim_feature_rate=0.0149, sim_avg_win=2.67),
    Mode("immortal-arena", "Immortal Arena", "Inner Sect", "Balanced", 0.93, 100, 10_000,
         "Table standard. Wider wagers, sharper margins, and the payout "
         "ladder every elder quietly plays.",
         royal_mass=0.62300, sim_rtp=0.9359, sim_hit_rate=0.350,
         sim_profit_rate=0.1379, sim_feature_rate=0.0149, sim_avg_win=2.67),
    Mode("heavens-gambit", "Heaven's Gambit", "Ascension", "Volatile", 0.90, 1_000, 100_000,
         "The tightest return on the mountain with the highest ceiling. "
         "Heaven rewards nerve, not patience.",
         royal_mass=0.61850, sim_rtp=0.8974, sim_hit_rate=0.341,
         sim_profit_rate=0.1317, sim_feature_rate=0.0148, sim_avg_win=2.63),
)

MODE_BY_SLUG = {m.slug: m for m in MODES}


def get_mode(slug: str) -> Mode | None:
    return MODE_BY_SLUG.get(slug)


# --------------------------------------------------------------------------- #
# Scoring a single grid
# --------------------------------------------------------------------------- #

def count_tier(count: int) -> str | None:
    if count < 8:
        return None
    if count <= 9:
        return PAY_TIER_8
    if count <= 11:
        return PAY_TIER_10
    return PAY_TIER_12


def tier_index(count: int) -> int:
    return 0 if count <= 9 else (1 if count <= 11 else 2)


def evaluate(grid: list[str], wild: str | None = None) -> tuple[list[dict], set[int]]:
    """Score one grid.

    Returns the winning clusters and the set of cell indexes to remove.
    When ``wild`` is set (the bonus) Flying Swords substitute for any ladder
    symbol that already appears at least once naturally.
    """
    counts: dict[str, int] = {}
    for key in grid:
        counts[key] = counts.get(key, 0) + 1
    wilds = counts.get(wild, 0) if wild else 0

    wins: list[dict] = []
    cells: set[int] = set()

    for sym in PAYS_SYMBOLS:
        own = counts.get(sym.key, 0)
        substitutes = bool(wild and wild != sym.key and own >= 1)
        total = own + (wilds if substitutes else 0)
        tier = count_tier(total)
        if tier is None:
            continue
        mult = sym.pays[tier_index(total)]
        if mult <= 0:
            continue
        wins.append({"key": sym.key, "name": sym.name, "count": total,
                     "tier": tier, "mult": mult})
        for i, key in enumerate(grid):
            if key == sym.key or (substitutes and key == wild):
                cells.add(i)

    wins.sort(key=lambda w: -w["mult"])
    return wins, cells


def scatter_count(grid: list[str]) -> int:
    n = 0
    for key in grid:
        if key == SCATTER_KEY or key == TRIGGER_KEY:
            n += 1
    return n


def refill(grid: list[str], removed: set[int], weights: tuple[float, ...]) -> list[str]:
    """Collapse the surviving cells to the floor of each column, drop new ones in."""
    out = list(grid)
    for c in range(COLS):
        keep = [grid[r * COLS + c] for r in range(ROWS) if (r * COLS + c) not in removed]
        fresh = draw_grid(weights, ROWS - len(keep))
        column = fresh + keep
        for r in range(ROWS):
            out[r * COLS + c] = column[r]
    return out


# --------------------------------------------------------------------------- #
# Cascade chains
# --------------------------------------------------------------------------- #

def resolve_chain(grid: list[str], stake: float, weights: tuple[float, ...],
                  *, start_mult: float = 1.0, mult_cap: float = 1.0,
                  wild: str | None = None) -> dict:
    """Play one grid to exhaustion: score, remove, collapse, repeat."""
    initial_grid = list(grid)
    steps: list[dict] = []
    total = 0.0
    mult = start_mult
    # Scatters are read off the grid as it first lands; symbols that tumble in
    # afterwards can win, but they cannot open the bonus a second time.
    scatters = scatter_count(grid)

    for _ in range(MAX_CASCADES):
        wins, cells = evaluate(grid, wild)
        if not wins:
            break

        payout = sum(w["mult"] for w in wins) * stake * mult
        total += payout
        steps.append({
            "grid": list(grid),
            "cells": sorted(cells),
            "wins": wins,
            "mult": round(mult, 2),
            "payout": round(payout, 2),
            "cum": round(total, 2),
        })

        if mult < mult_cap:
            mult = min(mult_cap, mult + BONUS_MULT_STEP)

        grid = refill(grid, cells, weights)

    return {
        "initial_grid": initial_grid,
        "final_grid": list(grid),
        "steps": steps,
        "total": round(total, 2),
        "mult": mult,
        "scatters": scatters,
        "cascades": len(steps),
    }


def free_spins_for(count: int) -> int:
    if count < SCATTER_MIN:
        return 0
    if count == 4:
        return 10
    if count == 5:
        return 15
    if count == 6:
        return 20
    return 25


def scatter_pay(count: int) -> float:
    """Cash paid for the scatters themselves, as a multiple of the stake."""
    if count < SCATTER_MIN:
        return 0.0
    return {4: 2.0, 5: 5.0, 6: 10.0}.get(count, 25.0)


# --------------------------------------------------------------------------- #
# The Heavenly Tribulation bonus
# --------------------------------------------------------------------------- #

def play_feature(stake: float, weights: tuple[float, ...], trigger_count: int,
                 rng_seed: int | None = None) -> dict:
    granted = free_spins_for(trigger_count)
    trigger_pay = scatter_pay(trigger_count) * stake
    total = trigger_pay
    spins: list[dict] = []
    queue = granted
    played = 0
    mult = 1.0

    while queue > 0 and played < BONUS_MAX_SPINS:
        queue -= 1
        played += 1
        grid = draw_grid(weights)
        chain = resolve_chain(grid, stake, weights,
                              start_mult=mult, mult_cap=BONUS_MULT_CAP, wild=WILD_KEY)
        mult = chain["mult"]
        total += chain["total"]
        spins.append({
            "grid": chain["steps"][0]["grid"] if chain["steps"] else grid,
            "steps": chain["steps"],
            "payout": chain["total"],
            "cascades": chain["cascades"],
            "mult": chain["mult"],
        })
        if chain["scatters"] >= SCATTER_MIN and played < BONUS_MAX_SPINS:
            queue += BONUS_RETRIGGER

    return {
        "count": trigger_count,
        "spins": spins,
        "granted": granted,
        "played": played,
        "triggerPay": round(trigger_pay, 2),
        "total": round(total, 2),
        "bestMult": max([s["mult"] for s in spins], default=1.0),
    }


# --------------------------------------------------------------------------- #
# One paid spin
# --------------------------------------------------------------------------- #

def spin(mode: Mode, stake: float) -> dict:
    weights = mode.weights
    base_grid = draw_grid(weights)
    base = resolve_chain(base_grid, stake, weights)

    feature = None
    if base["scatters"] >= SCATTER_MIN:
        feature = play_feature(stake, weights, base["scatters"])

    total = base["total"] + (feature["total"] if feature else 0.0)
    return {
        "base": base,
        "feature": feature,
        "total": round(total, 2),
        "win": total > 0,
    }


# --------------------------------------------------------------------------- #
# Derived odds (paytable page)
# --------------------------------------------------------------------------- #

def binom_at_least(p: float, n: int = CELLS, low: int = 8) -> float:
    """P(Binomial(n, p) >= low), exact."""
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    keep = math.comb(n, low) * p**low * (1 - p) ** (n - low)
    prob = keep
    for k in range(low, n):
        keep *= (n - k) / (k + 1) * p / (1 - p)
        prob += keep
    return min(prob, 1.0)


def binom_tier(p: float, count: int, n: int = CELLS) -> float:
    """Exact P(Binomial(n, p) == count)."""
    if p <= 0:
        return 0.0
    return math.comb(n, count) * p**count * (1 - p) ** (n - count)


def symbol_stats(mode: Mode) -> list[dict]:
    """Per-symbol probability, hit rate and stake return for one table."""
    weights = dict(zip(GRID_KEYS, mode.weights))
    rows: list[dict] = []

    for sym in PAYS_SYMBOLS:
        p = weights[sym.key]
        p8 = sum(binom_tier(p, k) for k in range(8, 10))
        p10 = sum(binom_tier(p, k) for k in range(10, 12))
        p12 = sum(binom_tier(p, k) for k in range(12, CELLS + 1))
        ev = p8 * sym.pays[0] + p10 * sym.pays[1] + p12 * sym.pays[2]
        rows.append({
            "key": sym.key,
            "name": sym.name,
            "tier": sym.tier,
            "icon": sym.url,
            "glyph": sym.glyph,
            "color": sym.color,
            "note": sym.note,
            "pays": sym.pays,
            "cell_pct": round(p * 100, 3),
            "hit_pct": round((p8 + p10 + p12) * 100, 3),
            "tiers": [round(p8 * 100, 4), round(p10 * 100, 4), round(p12 * 100, 4)],
            "return_pct": round(ev * 100, 3),
        })
    return rows


def base_rtp(mode: Mode) -> float:
    """Expected return of one paid grid before any cascade or feature."""
    return sum(row["return_pct"] for row in symbol_stats(mode)) / 100.0


def scatter_stats(mode: Mode) -> dict:
    weights = dict(zip(GRID_KEYS, mode.weights))
    p = weights[SCATTER_KEY] + weights[TRIGGER_KEY]
    return {
        "emblem_pct": round(weights[SCATTER_KEY] * 100, 3),
        "seal_pct": round(weights[TRIGGER_KEY] * 100, 3),
        "any_pct": round(p * 100, 3),
        "odds": f"1 in {round(1 / binom_at_least(p, low=SCATTER_MIN))}",
        "trigger_pct": round(binom_at_least(p, low=SCATTER_MIN) * 100, 3),
    }


# --------------------------------------------------------------------------- #
# Simulation (used by the tuner and quoted on the paytable)
# --------------------------------------------------------------------------- #

def simulate(mode: Mode, spins: int = 60_000, seed: int = 20261102) -> dict:
    """Monte-Carlo the whole game - cascades, bonus, retriggers included."""
    rng = random.Random(seed)
    weights = mode.weights

    wagered = 0.0
    returned = 0.0
    hits = 0
    profitable_spins = 0
    features = 0
    win_total = 0.0
    cascade_total = 0
    free_total = 0
    free_spins_played = 0
    best_spin = 0.0

    for _ in range(spins):
        wagered += 1.0
        grid = rng.choices(GRID_KEYS, weights=weights, k=CELLS)
        base = _sim_chain(grid, 1.0, weights, rng, 1.0, 1.0, None)
        spin_return = base["total"]
        cascade_total += base["cascades"]

        if base["scatters"] >= SCATTER_MIN:
            features += 1
            spin_return += scatter_pay(base["scatters"])
            queue, played, mult = free_spins_for(base["scatters"]), 0, 1.0
            while queue > 0 and played < BONUS_MAX_SPINS:
                queue -= 1
                played += 1
                free_spins_played += 1
                fgrid = rng.choices(GRID_KEYS, weights=weights, k=CELLS)
                chain = _sim_chain(fgrid, 1.0, weights, rng, mult, BONUS_MULT_CAP, WILD_KEY)
                mult = chain["mult"]
                spin_return += chain["total"]
                free_total += chain["total"]
                if chain["scatters"] >= SCATTER_MIN:
                    queue += BONUS_RETRIGGER

        returned += spin_return
        if spin_return > 0:
            hits += 1
            win_total += spin_return
        if spin_return > 1.0:
            profitable_spins += 1
        best_spin = max(best_spin, spin_return)

    return {
        "rtp": returned / wagered,
        "hit_rate": hits / spins,
        "profit_rate": profitable_spins / spins,
        "feature_rate": features / spins,
        "avg_win": (win_total / hits) if hits else 0.0,
        "best_spin": best_spin,
        "avg_cascades": cascade_total / spins,
        "free_spins_per_bonus": free_spins_played / features if features else 0.0,
        "feature_share": free_total / returned if returned else 0.0,
        "spins": spins,
    }


def _sim_chain(grid: list[str], stake: float, weights: tuple[float, ...],
               rng: random.Random, start_mult: float, cap: float,
               wild: str | None) -> dict:
    """``resolve_chain`` with an injectable RNG, for the tuner."""
    total = 0.0
    mult = start_mult
    scatters = scatter_count(grid)
    cascades = 0
    ladder = False
    ladder_keys = frozenset(k for k in LADDER_SHAPE)

    for _ in range(MAX_CASCADES):
        wins, cells = evaluate(grid, wild)
        if not wins:
            break
        if not ladder and any(w["key"] in ladder_keys for w in wins):
            ladder = True
        total += sum(w["mult"] for w in wins) * stake * mult
        cascades += 1
        if mult < cap:
            mult = min(cap, mult + BONUS_MULT_STEP)

        out = list(grid)
        for c in range(COLS):
            keep = [grid[r * COLS + c] for r in range(ROWS) if (r * COLS + c) not in cells]
            fresh = rng.choices(population=GRID_KEYS, weights=weights, k=ROWS - len(keep))
            column = fresh + keep
            for r in range(ROWS):
                out[r * COLS + c] = column[r]
        grid = out

    return {"total": total, "mult": mult, "scatters": scatters,
            "cascades": cascades, "ladder": ladder}

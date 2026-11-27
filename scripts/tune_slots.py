"""Reign of Fortune - reel tuner.

Bisects the one number each table owns (``royal_mass``: the share of the 30
cells spent on J-A tiles) until a Monte-Carlo of the *whole* game - cascades,
the Heavenly Tribulation bonus, retriggers - lands on the table's RTP target.

Run from the project root::

    python scripts/tune_slots.py            # tune + print
    python scripts/tune_slots.py --check    # validate baked values only
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "reign.settings")

import django  # noqa: E402

django.setup()

from game import slots  # noqa: E402

BISECT_SPINS = 100_000
FINAL_SPINS = 500_000
BISECT_SEED = 20261102        # fixed across iterations: variance reduction
ITERS = 16


def measure(mode: slots.Mode, royal_mass: float, spins: int, seed: int) -> dict:
    return slots.simulate(replace(mode, royal_mass=royal_mass), spins=spins, seed=seed)


def tune(mode: slots.Mode, verbose: bool = True) -> float:
    lo, hi = 0.60, 0.65
    best = (lo + hi) / 2

    for i in range(ITERS):
        mid = (lo + hi) / 2
        rtp = measure(mode, mid, BISECT_SPINS, BISECT_SEED)["rtp"]
        best = mid
        if verbose:
            print(f"  [{mode.slug}] iter {i:2d}  royal_mass={mid:.4f}  rtp={rtp:.4f}  "
                  f"target={mode.rtp:.2f}")
        if rtp > mode.rtp:
            hi = mid          # more script mass raises the return in the tuned range
        else:
            lo = mid

    return round(best, 6)


def report(mode: slots.Mode, spins: int = FINAL_SPINS, seed: int = BISECT_SEED) -> dict:
    stats = slots.simulate(mode, spins=spins, seed=seed)
    base = slots.base_rtp(mode)
    print(f"\n{mode.name}  (royal_mass {mode.royal_mass:.4f}, target {mode.rtp:.0%})")
    print(f"  measured return ......... {stats['rtp']:.4%}")
    print(f"  base-grid return ........ {base:.4%}  (cascades + feature make up the rest)")
    print(f"  any-payout frequency .... {stats['hit_rate']:.2%}")
    print(f"  net-positive spins ...... {stats['profit_rate']:.2%}")
    print(f"  bonus frequency ......... {stats['feature_rate']:.3%}  "
          f"(1 in {round(1 / stats['feature_rate'])})")
    print(f"  avg win on a winning spin {stats['avg_win']:.2f}x")
    print(f"  avg cascades / spin ..... {stats['avg_cascades']:.3f}")
    print(f"  free spins / bonus ...... {stats['free_spins_per_bonus']:.1f}")
    print(f"  share of return from bonus {stats['feature_share']:.2%}")
    print(f"  spread vs target ........ {stats['rtp'] - mode.rtp:+.4%}")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="only validate the baked values")
    ap.add_argument("--spins", type=int, default=FINAL_SPINS)
    args = ap.parse_args()

    if not args.check:
        print("Tuning royal_mass ...")
        tuned: dict[str, float] = {}
        for mode in slots.MODES:
            tuned[mode.slug] = tune(mode)
        print("\nTuned values (verify with the report before baking):")
        for mode in slots.MODES:
            tuned_mode = replace(mode, royal_mass=tuned[mode.slug])
            print(f"  {mode.slug}: royal_mass={tuned_mode.royal_mass:.6f}")
            report(tuned_mode, spins=args.spins)
    else:
        for mode in slots.MODES:
            report(mode, spins=args.spins)


if __name__ == "__main__":
    main()

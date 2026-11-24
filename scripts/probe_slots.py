import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "reign.settings")
import django
django.setup()
from dataclasses import replace
from game import slots

m = slots.MODES[0]
t = time.time()
print("cap  rm    baseEV   rtp     hit    avgwin  fshare  best")
for cap in (3, 4, 5, 6, 8, 10):
    slots.BONUS_MULT_CAP = cap
    for rm in (0.40, 0.46, 0.52, 0.58, 0.62):
        mm = replace(m, royal_mass=rm)
        r = slots.simulate(mm, spins=20000, seed=1)
        print("%3d  %.2f  %.4f  %.4f  %.3f  %6.2f  %.3f  %7.1f" % (
            cap, rm, slots.base_rtp(mm), r["rtp"], r["hit_rate"],
            r["avg_win"], r["feature_share"], r["best_spin"]))
    print()
print("elapsed", round(time.time() - t, 1))

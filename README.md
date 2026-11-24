# Reign of Fortune

A xianxia-themed **scatter-pay slot** prototype built with **Django + Tailwind CSS**.
6&times;5 grid, pay-anywhere wins, cascades and the Heavenly Tribulation free-spin bonus.

> Prototype for client review. Not a real-money product.

## Requirements

- Python 3.11+ (tested on 3.14)
- Node 20+ (only needed to rebuild the CSS)

## Run it

```powershell
cd "C:\Users\Surface\Documents\App Dev\Reign of Fortune"

py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python manage.py migrate
python manage.py runserver 127.0.0.1:8000 --noreload
```

Open <http://127.0.0.1:8000/>.

The demo player (5,000 Spirit Stones) is created automatically on first visit.
1 Spirit Stone = &#8369;1.00.

## Screens

| Route | Screen |
| --- | --- |
| `/` | Splash / title |
| `/menu/` | Sanctum (balance, top up, cash out, enter trials) |
| `/topup/` | Top up Spirit Stones |
| `/ring/` | Spatial Ring wallet + ledger + cashout |
| `/play/` | Choose a table |
| `/play/<table>/` | **Slots game screen** |
| `/paytable/` | Paytable & derived odds |

## Tables

| Table | Stake range | Target return |
| --- | --- | --- |
| Green Lotus Hall | 10 &ndash; 500 SS | 96% |
| Immortal Arena | 100 &ndash; 10,000 SS | 93% |
| Heaven's Gambit | 1,000 &ndash; 100,000 SS | 90% |

## Rebuilding the CSS

Tailwind v4 lives in `game/static/game/src/input.css`.

```powershell
npm install
npm run css          # one-shot build -> game/static/game/css/app.css
npm run css:watch    # rebuild on change
```

## Project layout

```
reign/                 Django project (settings, urls, wsgi)
game/
  slots.py             Scatter-pay engine: reel weights, scoring, bonus, tuner maths
  services.py          Spin resolution, ledger writes, bonus features
  wallet.py            Top-up / cashout / reset
  views.py             Screens + JSON spin endpoint
  models.py            Player, Transaction, GameRound
  templates/game/      Django templates
  static/game/         Tailwind input, built CSS, JS, the 10 symbol icons
scripts/
  tune_slots.py        Bisects each table's reel mix until measured RTP hits target
  probe_slots.py       Quick RTP / hit-rate sweep while tuning
```

## Odds

The paytable is derived, not hand-tuned. Each table owns one number —
`royal_mass`, the share of the 30 cells spent on the four low-pay script
tiles. `python scripts/tune_slots.py` bisects it against a Monte-Carlo of the
whole game (cascades, bonus, retriggers) until the measured return lands on
the table's target. Re-run it after changing any paytable value:

```powershell
python scripts/tune_slots.py            # tune and report
python scripts/tune_slots.py --check    # validate the baked values only
```

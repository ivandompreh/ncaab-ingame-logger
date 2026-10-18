#!/usr/bin/env python3
"""Same-night 1-min PM US price history (plan §6) for every game in <data>/plans/<date>.json. Writes ONLY to the
private data checkout (<data>/history/<date>/<slug>.json.gz). Refuses sealed-holdout dates. stdout: counts only.
Usage: history_pull.py --data DIR [--date YYYY-MM-DD] (default: yesterday ET)"""
import argparse, datetime as dt, gzip, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ET, G, PM_LIMIT, get, assert_not_sealed

def main():
    a = argparse.ArgumentParser(); a.add_argument("--data", required=True); a.add_argument("--date"); o = a.parse_args()
    day = dt.date.fromisoformat(o.date) if o.date else dt.datetime.now(ET).date() - dt.timedelta(days=1); assert_not_sealed(day)
    p = os.path.join(o.data, "plans", f"{day}.json")
    if not os.path.exists(p): print(f"{day}: no plan"); return
    plan = json.load(open(p)); od = os.path.join(o.data, "history", day.isoformat()); os.makedirs(od, exist_ok=True)
    ok = err = skip = 0
    for g in plan["games"]:
        f = os.path.join(od, g["slug"] + ".json.gz")
        if os.path.exists(f): skip += 1; continue
        tip = int(dt.datetime.fromisoformat(g["tip_utc"]).timestamp())
        S, E = tip - 900, tip + 4 * 3600
        if E > time.time(): skip += 1; continue
        d, e, _ = get(f"{G}price-history?symbol={g['slug']}&timestamp.startTimestamp={S}&timestamp.endTimestamp={E}&fidelity=1", PM_LIMIT, timeout=40)
        if e: err += 1; continue
        with gzip.open(f, "wt") as fh: json.dump({"slug": g["slug"], "espn_id": g["espn_id"], "fetched_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                                               "start": S, "end": E, "history": (d or {}).get("history", [])}, fh)
        ok += 1
    print(f"history {day}: {ok} pulled, {err} errors, {skip} skipped")

if __name__ == "__main__": main()

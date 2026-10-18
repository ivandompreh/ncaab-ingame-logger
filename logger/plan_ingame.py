#!/usr/bin/env python3
"""08:40 ET planner: discover today's PM US-listed D1 games and place the logging link(s) by the frame rule.
Writes <data>/plans/<date>.json (private data repo checkout). stdout: counts only.
Usage: plan_ingame.py --data DATA_DIR --alias ALIAS_TSV [--date YYYY-MM-DD]"""
import argparse, datetime as dt, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ET, FRAME, discover, place_links, start_slot, assert_not_sealed

def main():
    a = argparse.ArgumentParser(); a.add_argument("--data", required=True); a.add_argument("--alias", required=True); a.add_argument("--date")
    o = a.parse_args()
    day = dt.date.fromisoformat(o.date) if o.date else dt.datetime.now(ET).date(); assert_not_sealed(day)
    d = discover(day, o.alias)
    links = place_links(d["games"], day=day)
    plan = {**d, "frame": FRAME, "links": links, "slot": start_slot(links[0]["start_utc"]) if links else None,
            "planned_at_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
    os.makedirs(os.path.join(o.data, "plans"), exist_ok=True)
    with open(os.path.join(o.data, "plans", f"{day}.json"), "w") as f: json.dump(plan, f, indent=1)
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a") as f: f.write(f"ingame_slot={'[' + plan['slot'] + ']' if plan['slot'] else '[none]'}\nn_links={len(links)}\n")
    print(f"{day}: ESPN D1 {d['n_espn']}, no alias {d['n_no_alias']}, PM US listed {d['n_listed']}; links {len(links)}"
          + (f"; link1 {dt.datetime.fromisoformat(links[0]['start_utc']).astimezone(ET):%H:%M} ET slot '{plan['slot']}'" if links else ""))

if __name__ == "__main__": main()

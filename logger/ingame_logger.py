#!/usr/bin/env python3
"""PM US in-game logger v3 (holdout B). No API key. Public CODE; all output goes ONLY to --out, which in Actions is a
checkout of the PRIVATE data repo. Nothing raw is printed: stdout = counts + slugs.

Per link (one Actions job, <= link_minutes = 350):
  * Game discovery from today's ESPN schedule + PM US aec-cbb-* slugs (refreshed every 30 min).
  * A game is active from tip-10 to min(settle/expired/closed, tip+170, link end). YES side from market metadata.
  * Book: every active game each cycle; cycle interval = max(3 s, n_active/15) s; all PM US calls share a 15 req/s
    token bucket (PM US limit 20/s; 429 -> back-off). Thread pool. Changed books written in full; unchanged -> 'hb'
    record with transactTime (needed for the 30-s freshness rule).
  * ESPN summary per game every max(10, n/3) s, new plays only.
  * Output rotated every 30 min into gzip parts; each part is committed+pushed by --push-cmd.
  * Chaining: if the plan has a next link, --chain-cmd is run at (link end - overlap) so the next job overlaps by 10 min.
    Dedupe key for analysis: (slug, ts_utc) / (espn, play id).
Usage: ingame_logger.py --out DIR --alias TSV [--plan PLAN.json] [--link 1] [--minutes M] [--dry-run]
                        [--push-cmd CMD] [--chain-cmd CMD] [--games SLUG:ESPN,...]"""
import argparse, concurrent.futures as cf, datetime as dt, gzip, json, os, subprocess, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ET, UTC, FRAME, G, ESPN_SUM, PM_LIMIT, ESPN_LIMIT, get, discover, place_links, assert_not_sealed

STOP_STATES = ("MARKET_STATE_EXPIRED", "MARKET_STATE_SETTLED", "MARKET_STATE_CLOSED")
def now(): return dt.datetime.now(UTC)
def book_interval(n): return max(3.0, n / 15.0)
def espn_interval(n): return max(10.0, n / 3.0)

class Writer:
    def __init__(self, out, day, link, run_id, dry, rotate_min, push_cmd):
        self.dir = os.path.join(out, "ingame", day); os.makedirs(self.dir, exist_ok=True)
        self.base = f"L{link}_{run_id}"; self.part = 0; self.lock = threading.Lock(); self.dry = dry
        self.rotate_s = rotate_min * 60; self.push_cmd = push_cmd; self.n = {}; self.f = None; self._open()
        self.link = link
    def _open(self):
        self.part += 1; self.tmp = os.path.join(self.dir, f".{self.base}_p{self.part:03d}.jsonl.gz.tmp")
        self.f = gzip.open(self.tmp, "at", compresslevel=6); self.t_open = time.time()
    def w(self, r):
        r = {**r, "ts_utc": now().isoformat(), "link": self.link, "dry_run": self.dry}
        with self.lock:
            self.f.write(json.dumps(r, separators=(",", ":")) + "\n"); self.n[r["kind"]] = self.n.get(r["kind"], 0) + 1
    def maybe_rotate(self, force=False):
        if not force and time.time() - self.t_open < self.rotate_s: return
        with self.lock:
            self.f.close(); final = self.tmp.replace("/.", "/").replace(".tmp", "")
            os.replace(self.tmp, final); closed = self.part
            if not force: self._open()
        self.push(closed)
    def push(self, part):
        if self.push_cmd:
            r = subprocess.run(self.push_cmd, shell=True, capture_output=True, text=True)
            last = (r.stdout.strip().splitlines() or [""])[-1][:80]
            print(f"push part {part}: rc={r.returncode} {last}", flush=True)

class Game:
    def __init__(self, slug, espn, tip):
        self.slug, self.espn, self.tip = slug, espn, tip; self.done = False; self.last = None; self.seen = set()
        self.meta = False; self.last_e = 0.0
    def window(self, link_end):
        return self.tip - dt.timedelta(minutes=FRAME["pre_minutes"]), min(self.tip + dt.timedelta(minutes=FRAME["post_minutes_log"]), link_end)

def yes_side(slug):
    d, e, _ = get(G + "market/slug/" + slug, PM_LIMIT)
    for x in ((d or {}).get("market") or {}).get("marketSides", []):
        if x.get("long"):
            t = x.get("team") or {}; return {"team": t.get("name"), "abbr": t.get("abbreviation"), "ordering": t.get("ordering")}
    return {"err": e or "no long side"}

def poll_book(g, W):
    b, e, lat = get(G + "markets/" + g.slug + "/book", PM_LIMIT, tries=2)
    md = (b or {}).get("marketData", {})
    lv = lambda side: [[float(x["px"]["value"]), float(x["qty"])] for x in (md.get(side) or [])]
    if e:
        W.w({"kind": "book_err", "slug": g.slug, "err": e, "lat": lat}); return
    st = md.get("state"); bids, asks = lv("bids"), lv("offers"); key = (st, json.dumps(bids), json.dumps(asks))
    if key != g.last:
        W.w({"kind": "book", "slug": g.slug, "state": st, "transactTime": md.get("transactTime"), "bids": bids, "asks": asks, "lat": lat})
        g.last = key
    else:
        W.w({"kind": "hb", "slug": g.slug, "state": st, "transactTime": md.get("transactTime"), "lat": lat})
    if st in STOP_STATES: g.done = True

def poll_espn(g, W):
    r, e, lat = get(ESPN_SUM + g.espn, ESPN_LIMIT, tries=2)
    if e: W.w({"kind": "espn_err", "espn": g.espn, "err": e}); return
    stt = ((r.get("header", {}).get("competitions") or [{}])[0].get("status") or {}).get("type", {})
    new = [p for p in r.get("plays", []) if p.get("id") not in g.seen]
    for p in new:
        g.seen.add(p.get("id"))
        W.w({"kind": "play", "espn": g.espn, "id": p.get("id"), "wallclock": p.get("wallclock"), "period": (p.get("period") or {}).get("number"),
             "clock": (p.get("clock") or {}).get("displayValue"), "away": p.get("awayScore"), "home": p.get("homeScore"),
             "scoring": p.get("scoringPlay"), "value": p.get("scoreValue"), "type": (p.get("type") or {}).get("text"),
             "team": (p.get("team") or {}).get("id")})
    W.w({"kind": "espn_poll", "espn": g.espn, "new_plays": len(new), "status": stt.get("name"), "lat": lat})

def main():
    a = argparse.ArgumentParser()
    a.add_argument("--out", required=True); a.add_argument("--alias"); a.add_argument("--plan"); a.add_argument("--date")
    a.add_argument("--link", type=int, default=1); a.add_argument("--minutes", type=float); a.add_argument("--dry-run", action="store_true")
    a.add_argument("--push-cmd"); a.add_argument("--chain-cmd"); a.add_argument("--games", help="manual SLUG:ESPN[,..] (dry run); tip = now")
    a.add_argument("--no-wait", action="store_true", help="start immediately instead of sleeping to the link start")
    o = a.parse_args()
    day = dt.date.fromisoformat(o.date) if o.date else dt.datetime.now(ET).date(); assert_not_sealed(day)
    plan = json.load(open(o.plan)) if o.plan and os.path.exists(o.plan) else None
    t_start = now()
    if o.games:
        links = [{"link": 1, "start_utc": t_start.isoformat(), "end_utc": (t_start + dt.timedelta(minutes=o.minutes or 60)).isoformat()}]
    elif plan: links = plan["links"]
    else:
        d = discover(day, o.alias); links = place_links(d["games"], day=day); plan = {**d, "links": links}
    if not links: print(f"{day}: no PM US-listed games; nothing to log"); return
    L = next(x for x in links if x["link"] == o.link)
    l_start, l_end = dt.datetime.fromisoformat(L["start_utc"]), dt.datetime.fromisoformat(L["end_utc"])
    if o.minutes: l_end = min(l_end, max(now(), l_start) + dt.timedelta(minutes=o.minutes))
    hard_end = now() + dt.timedelta(minutes=FRAME["link_minutes"])          # never exceed one job's budget
    l_end = min(l_end, hard_end)
    if not o.no_wait and now() < l_start:
        w = (l_start - now()).total_seconds(); print(f"sleeping {w/60:.1f} min to link {o.link} start", flush=True); time.sleep(w)
    W = Writer(o.out, day.isoformat(), o.link, os.environ.get("GITHUB_RUN_ID", "local"), o.dry_run, FRAME["rotate_minutes"], o.push_cmd)
    games = {}
    def refresh():
        if o.games:
            for x in o.games.split(","):
                s, e = (x.split(":") + [None])[:2]; games.setdefault(s, Game(s, e, now() + dt.timedelta(minutes=FRAME["pre_minutes"])))
            return
        d = discover(day, o.alias) if o.alias else plan
        for x in d["games"]:
            if x.get("time_tbd"): continue
            tip = dt.datetime.fromisoformat(x["tip_utc"])
            if x["slug"] in games: games[x["slug"]].tip = tip
            else: games[x["slug"]] = Game(x["slug"], x["espn_id"], tip)
        W.w({"kind": "discovery", "n_espn": d.get("n_espn"), "n_listed": d.get("n_listed"), "n_no_alias": d.get("n_no_alias")})
    refresh(); last_refresh = time.time()
    in_link = [g for g in games.values() if g.window(l_end)[1] > now()]
    print(f"link {o.link}: {now().astimezone(ET):%H:%M}-{l_end.astimezone(ET):%H:%M} ET, {len(in_link)} games in window: "
          + ",".join(sorted(g.slug for g in in_link)), flush=True)
    W.w({"kind": "link_start", "link": o.link, "start_utc": L["start_utc"], "end_utc": l_end.isoformat(), "n_games": len(in_link)})
    chained = False
    nxt = next((x for x in links if x["link"] == o.link + 1), None)
    pool = cf.ThreadPoolExecutor(16); epool = cf.ThreadPoolExecutor(4)
    cycles = 0; last_report = time.time(); req0 = PM_LIMIT.n
    while now() < l_end:
        t0 = time.time(); tn = now()
        if time.time() - last_refresh > 1800 and not o.games:
            try: refresh()
            except Exception as e: W.w({"kind": "discovery_err", "err": repr(e)[:160]})
            last_refresh = time.time()
        active = [g for g in games.values() if not g.done and g.window(l_end)[0] <= tn < g.window(l_end)[1]]
        for g in active:
            if not g.meta: W.w({"kind": "meta", "slug": g.slug, "espn": g.espn, "tip_utc": g.tip.isoformat(), "yes": yes_side(g.slug)}); g.meta = True
        list(pool.map(lambda g: poll_book(g, W), active))
        ei = espn_interval(len([g for g in active if g.espn]))
        due = [g for g in active if g.espn and time.time() - g.last_e >= ei]
        for g in due: g.last_e = time.time()
        if due: list(epool.map(lambda g: poll_espn(g, W), due))
        cycles += 1; W.maybe_rotate()
        if nxt and not chained and o.chain_cmd and now() >= dt.datetime.fromisoformat(nxt["start_utc"]) - dt.timedelta(minutes=2):
            r = subprocess.run(o.chain_cmd, shell=True, capture_output=True, text=True); chained = True
            W.w({"kind": "chain", "next_link": nxt["link"], "rc": r.returncode}); print(f"chained link {nxt['link']}: rc={r.returncode}", flush=True)
        upcoming = [g for g in games.values() if not g.done and g.window(l_end)[0] > tn and g.window(l_end)[0] < l_end]
        if not active and not upcoming and cycles > 1:
            W.w({"kind": "link_end", "reason": "no active or upcoming games"}); break
        if time.time() - last_report > 600:
            rps = (PM_LIMIT.n - req0) / (time.time() - last_report); req0 = PM_LIMIT.n
            print(f"{now().astimezone(ET):%H:%M} ET active {len(active)} interval {book_interval(len(active)):.1f}s pm_req/s {rps:.1f} "
                  f"written {W.n}", flush=True); last_report = time.time()
        sleep = book_interval(len(active)) - (time.time() - t0)
        if not active:
            starts = [g.window(l_end)[0] for g in upcoming]
            sleep = min(60.0, max(1.0, (min(starts) - now()).total_seconds())) if starts else 30.0
        time.sleep(max(0.0, sleep))
    else:
        W.w({"kind": "link_end", "reason": "link end"})
    pool.shutdown(); epool.shutdown(); W.maybe_rotate(force=True)
    print(f"link {o.link} done: cycles {cycles}, written {W.n}, games {sum(1 for g in games.values() if g.meta)}", flush=True)

if __name__ == "__main__": main()

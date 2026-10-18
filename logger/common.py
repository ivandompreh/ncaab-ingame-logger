"""Shared helpers: HTTP with a global rate limiter, ESPN schedule, PM US slug discovery, sampling-frame rule.
Prints/logs counts and slugs only. Never writes prices anywhere except the private data-repo checkout."""
import datetime as dt, json, os, threading, time, urllib.request
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York"); UTC = dt.timezone.utc
G = "https://gateway.polymarket.us/v1/"
ESPN_SB = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?dates={d}&groups=50&limit=500"
ESPN_SUM = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event="
HERE = os.path.dirname(os.path.abspath(__file__))
FRAME = json.load(open(os.path.join(HERE, "..", "config", "frame.json")))
UA = {"User-Agent": "research-lowrate (ncaab-ingame-logger)"}
# Sealed holdout A (2026 NCAA tournament + other 2025-26 postseason): this code refuses to touch these dates.
SEALED = (dt.date(2026, 3, 17), dt.date(2026, 4, 7))
def assert_not_sealed(day):
    if SEALED[0] <= day <= SEALED[1]: raise SystemExit(f"refusing: {day} is inside the sealed holdout A window")

class Limiter:
    """Token bucket shared by all threads. rate = max requests/second."""
    def __init__(self, rate, burst=None):
        self.rate = float(rate); self.cap = float(burst or rate); self.tok = self.cap; self.t = time.monotonic(); self.l = threading.Lock()
        self.n = 0
    def acquire(self):
        while True:
            with self.l:
                now = time.monotonic(); self.tok = min(self.cap, self.tok + (now - self.t) * self.rate); self.t = now
                if self.tok >= 1: self.tok -= 1; self.n += 1; return
                w = (1 - self.tok) / self.rate
            time.sleep(w)

PM_LIMIT = Limiter(FRAME["pm_us_max_req_per_s"], burst=2)   # worst 1-s window <= 17 < 20
ESPN_LIMIT = Limiter(3, burst=3)

def get(u, limiter=None, timeout=10, tries=3):
    """Returns (json|None, err|None, latency_s). 429/5xx -> exponential back-off."""
    err = None
    for i in range(tries):
        if limiter: limiter.acquire()
        t = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=timeout) as r:
                return json.load(r), None, round(time.time() - t, 3)
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}"
            if e.code in (429, 500, 502, 503, 504) and i < tries - 1: time.sleep(2 ** i); continue
            return None, err, round(time.time() - t, 3)
        except Exception as e:
            err = repr(e)[:160]
            if i < tries - 1: time.sleep(1 + i); continue
    return None, err, None
import urllib.error  # noqa: E402

def espn_games(day):
    """D1 (groups=50) games on ET date `day`: espn_id, tip (UTC datetime), away/home ESPN team ids. Schedule only."""
    d, e, _ = get(ESPN_SB.format(d=f"{day:%Y%m%d}"), ESPN_LIMIT, timeout=30, tries=4)
    out = []
    for ev in (d or {}).get("events", []):
        c = (ev.get("competitions") or [{}])[0]; side = {}
        for t in c.get("competitors", []): side[t.get("homeAway")] = str((t.get("team") or {}).get("id") or t.get("id"))
        tip = dt.datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
        out.append({"espn_id": ev["id"], "tip_utc": tip.isoformat(), "away": side.get("away"), "home": side.get("home"),
                    "time_tbd": c.get("timeValid") is False or ev.get("timeValid") is False
                    or "TBD" in json.dumps((c.get("status") or ev.get("status") or {}).get("type") or {}).upper()})
    return out, e

def load_alias(path):
    code_of = {}
    for line in open(path):
        if line.startswith("#") or not line.strip(): continue
        code, tid = line.split("\t")[:2]; code_of.setdefault(tid, []).append(code)
    return code_of

def candidate_slugs(g, code_of):
    tip = dt.datetime.fromisoformat(g["tip_utc"]); dates = {tip.astimezone(ET).date().isoformat(), tip.astimezone(UTC).date().isoformat()}
    out = []
    for a in code_of.get(g["away"] or "", []):
        for h in code_of.get(g["home"] or "", []):
            for d in sorted(dates): out += [f"aec-cbb-{a}-{h}-{d}", f"aec-cbb-{h}-{a}-{d}"]
    return out

def discover(day, alias_path, batch=40):
    """ESPN schedule + PM US slug lookup (metadata only; listing prices are discarded in memory)."""
    games, err = espn_games(day); code_of = load_alias(alias_path)
    want = {}; no_alias = 0
    for g in games:
        c = candidate_slugs(g, code_of)
        if not c: no_alias += 1
        for s in c: want[s] = g
    found = {}; slugs = sorted(want)
    for i in range(0, len(slugs), batch):
        q = "&".join("slug=" + s for s in slugs[i:i + batch])
        d, e, _ = get(G + "markets?" + q + "&includeHidden=true", PM_LIMIT, timeout=30)
        for m in (d or {}).get("markets", []):
            s = m.get("slug") or ""
            if s.startswith("aec-cbb-") and s in want and want[s]["espn_id"] not in found:
                found[want[s]["espn_id"]] = {"slug": s, "espn_id": want[s]["espn_id"], "tip_utc": want[s]["tip_utc"],
                                             "pm_game_start": m.get("gameStartTime"), "time_tbd": want[s]["time_tbd"]}
    listed = sorted(found.values(), key=lambda x: (x["tip_utc"], x["slug"]))
    return {"date": day.isoformat(), "n_espn": len(games), "n_no_alias": no_alias, "n_listed": len(listed),
            "espn_error": err, "games": listed}

def grid(day, frame=FRAME):
    """Allowed link-1 start times (ET) on `day`: hh:mm for hh in start_slot_hours, mm in start_slot_minutes."""
    h0, h1 = frame["start_slot_hours"]
    return [dt.datetime.combine(day, dt.time(h, m), ET) for h in range(h0, h1 + 1) for m in frame["start_slot_minutes"]]

def best_block(tips, starts, link_min, pre, post_fit):
    """Single-link rule: start s in the slot grid maximising games whose [tip-pre, tip+post_fit] lies inside
    [s, s+link]; ties -> earliest s."""
    best = (0, None)
    for s in starts:
        n = sum(1 for t in tips if t - dt.timedelta(minutes=pre) >= s and t + dt.timedelta(minutes=post_fit) <= s + dt.timedelta(minutes=link_min))
        if n > best[0]: best = (n, s)
    return best

def place_links(games, frame=FRAME, day=None):
    """Deterministic sampling-frame rule. Returns [{link, start_utc, end_utc, ...}]. TBD-time games are excluded."""
    tips = sorted(dt.datetime.fromisoformat(g["tip_utc"]) for g in games if not g.get("time_tbd"))
    if not tips: return []
    day = day or tips[0].astimezone(ET).date()
    L, ov, pre, pf = frame["link_minutes"], frame["overlap_minutes"], frame["pre_minutes"], frame["post_minutes_fit"]
    starts = grid(day, frame)
    if frame["max_links"] <= 1:
        n, s = best_block(tips, starts, L, pre, pf)
        if s is None: return []
        return [{"link": 1, "start_utc": s.astimezone(UTC).isoformat(), "end_utc": (s + dt.timedelta(minutes=L)).astimezone(UTC).isoformat(),
                 "games_fully_covered": n}]
    first = tips[0] - dt.timedelta(minutes=pre)
    ok = [x for x in starts if x <= first]; s = ok[-1] if ok else starts[0]
    end_need = tips[-1] + dt.timedelta(minutes=pf); links = []
    while len(links) < frame["max_links"] and s < end_need:
        e = s + dt.timedelta(minutes=L)
        links.append({"link": len(links) + 1, "start_utc": s.astimezone(UTC).isoformat(), "end_utc": e.astimezone(UTC).isoformat()})
        s = e - dt.timedelta(minutes=ov)
    return links

def start_slot(start_utc):
    """Cron string (ET) of a link-1 start (always on the grid)."""
    t = dt.datetime.fromisoformat(start_utc).astimezone(ET); return f"{t.minute} {t.hour} * * *"

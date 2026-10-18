"""Offline tests for the in-game logger v3 (no network). Run: python3 tests/test_ingame.py"""
import datetime as dt, gzip, json, os, sys, tempfile, time, glob
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, "..", "logger"))
import common as C, ingame_logger as IG
ET, UTC = C.ET, C.UTC
D = dt.date(2027, 1, 16)
def tip(h, m): return dt.datetime.combine(D, dt.time(h, m), ET).astimezone(UTC).isoformat()

def test_single_link_rule():
    games = [{"slug": f"s{i}", "tip_utc": tip(h, m)} for i, (h, m) in enumerate([(12, 0), (14, 0), (16, 0), (16, 30), (17, 0), (19, 0), (19, 0), (19, 30), (21, 0)])]
    L = C.place_links(games, day=D)
    assert len(L) == 1
    s = dt.datetime.fromisoformat(L[0]["start_utc"]).astimezone(ET)
    assert s.minute in (5, 20, 35, 50)
    assert (dt.datetime.fromisoformat(L[0]["end_utc"]) - dt.datetime.fromisoformat(L[0]["start_utc"])).total_seconds() == 350 * 60
    # covers 16:00..19:30 cluster: start <= 15:50, start+350 >= 19:30+150 = 22:00 -> start >= 16:10 -> conflict; check best is consistent
    n = L[0]["games_fully_covered"]
    assert n == max(C.best_block([dt.datetime.fromisoformat(g["tip_utc"]) for g in games], C.grid(D), 350, 10, 150)[0] for _ in [0])
    assert C.start_slot(L[0]["start_utc"]) == f"{s.minute} {s.hour} * * *"

def test_tbd_excluded_and_multi_link():
    games = [{"slug": "a", "tip_utc": tip(12, 0)}, {"slug": "b", "tip_utc": tip(21, 0)}, {"slug": "c", "tip_utc": tip(23, 59), "time_tbd": True}]
    f = dict(C.FRAME, max_links=3)
    L = C.place_links(games, frame=f, day=D)
    assert [x["link"] for x in L] == [1, 2, 3]   # 11:50-17:40, 17:30-23:20, 23:10-05:00 (needs 23:30)
    e1 = dt.datetime.fromisoformat(L[0]["end_utc"]); s2 = dt.datetime.fromisoformat(L[1]["start_utc"])
    assert (e1 - s2).total_seconds() == 600            # 10-min overlap
    assert dt.datetime.fromisoformat(L[-1]["end_utc"]) >= dt.datetime.fromisoformat(tip(21, 0)) + dt.timedelta(minutes=150)

def test_cadence_rule():
    assert IG.book_interval(10) == 3.0 and abs(IG.book_interval(70) - 4.667) < 0.01
    assert IG.espn_interval(20) == 10.0 and abs(IG.espn_interval(70) - 23.33) < 0.01

def test_limiter_rate():
    lim = C.Limiter(15, burst=5); t = time.monotonic()
    for _ in range(50): lim.acquire()
    el = time.monotonic() - t
    assert el >= (50 - 5) / 15 * 0.95, el          # <= 15 req/s after the burst

def test_writer_changed_only_and_rotation():
    with tempfile.TemporaryDirectory() as tmp:
        W = IG.Writer(tmp, D.isoformat(), 1, "t", True, 30, None)
        g = IG.Game("aec-cbb-x-y-2027-01-16", "1", dt.datetime.now(UTC))
        book = {"marketData": {"state": "MARKET_STATE_OPEN", "transactTime": "t1", "bids": [{"px": {"value": "0.5"}, "qty": "10"}], "offers": []}}
        IG.get = lambda u, lim=None, tries=3, timeout=10: (book, None, 0.01)
        IG.poll_book(g, W); IG.poll_book(g, W)
        book["marketData"]["bids"][0]["qty"] = "12"; IG.poll_book(g, W)
        book["marketData"]["state"] = "MARKET_STATE_SETTLED"; IG.poll_book(g, W)
        W.maybe_rotate(force=True)
        parts = glob.glob(os.path.join(tmp, "ingame", D.isoformat(), "L1_t_p001.jsonl.gz"))
        rows = [json.loads(l) for l in gzip.open(parts[0], "rt")]
        assert [r["kind"] for r in rows] == ["book", "hb", "book", "book"] and g.done
        assert all("ts_utc" in r and r["link"] == 1 for r in rows)

def test_sealed_guard():
    try: C.assert_not_sealed(dt.date(2026, 3, 20)); assert False
    except SystemExit: pass
    C.assert_not_sealed(dt.date(2026, 11, 3))

def test_candidate_slugs():
    code_of = {"2": ["aub"], "333": ["ala"]}
    g = {"away": "2", "home": "333", "tip_utc": tip(21, 0)}       # 21:00 ET = 02:00Z next day -> both dates tried
    c = C.candidate_slugs(g, code_of)
    assert "aec-cbb-aub-ala-2027-01-16" in c and "aec-cbb-aub-ala-2027-01-17" in c and "aec-cbb-ala-aub-2027-01-16" in c

if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"): f(); print("ok", k)

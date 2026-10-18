#!/usr/bin/env python3
"""Public-repo guard: fails if the PUBLIC code repo contains anything that looks like raw data
(PM US books/history, ESPN plays, Odds API payloads), any data-type file, or any file over 512 KB.
Allowed: code, docs, config/frame.json, status/heartbeat.txt (date + counts only). Prints paths only."""
import os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BAD_EXT = (".jsonl", ".gz", ".csv", ".parquet", ".zip", ".tsv", ".db", ".sqlite")
ALLOWED_JSON = {"config/frame.json"}
RAW = re.compile(r'"(bids|asks|offers|transactTime|wallclock|bookmakers|outcomes|price_history|longPrice)"\s*:')
bad = []
for d, dirs, files in os.walk(ROOT):
    dirs[:] = [x for x in dirs if x not in (".git", "__pycache__")]
    for fn in files:
        p = os.path.join(d, fn); rel = os.path.relpath(p, ROOT)
        if rel.endswith(BAD_EXT) or (rel.endswith(".json") and rel not in ALLOWED_JSON) or rel.split(os.sep)[0] in ("data", "datarepo", "dryrun"):
            bad.append(rel + " (data file type/path)"); continue
        if os.path.getsize(p) > 512 * 1024: bad.append(rel + " (>512 KB)"); continue
        if rel.endswith((".md", ".txt", ".yml", ".yaml")) or rel.startswith("tests"):
            try:
                if RAW.search(open(p, errors="ignore").read()) and not rel.startswith(("tests", "README", "logger")): bad.append(rel + " (raw-looking content)")
            except OSError: pass
if bad: print("NO-RAW GUARD FAILED:"); print("\n".join(bad)); sys.exit(1)
print("no-raw guard: OK")

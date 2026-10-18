#!/usr/bin/env python3
"""Kalshi guard (DEVIATIONS D-005): no Kalshi raw data in any repo.

Fails (exit 1) if any DATA file in the tree has 'kalshi' (any case) in its path or its content.
Data files = anything under data/ or with a data extension (.jsonl, .jsonl.gz, .json, .csv, .gz, .tsv).
Code and docs (.py, .md, .yml, .sh, .txt outside data/) may mention Kalshi (the disabled notice).
Prints only offending PATHS, never file content. Usage: kalshi_guard.py [root ...]  (default: repo root)
Also importable: drop_kalshi(obj) -> (clean_obj, n_dropped) for writers.
"""
import gzip, json, os, re, sys
PAT = re.compile(rb"kalshi", re.I)
SPAT = re.compile(r"kalshi", re.I)
DATA_EXT = (".jsonl", ".jsonl.gz", ".json", ".csv", ".gz", ".tsv", ".parquet")
SKIP_DIRS = {".git", "__pycache__", "node_modules"}

def is_data(rel):
    parts = rel.replace("\\", "/").split("/")
    return parts[0] == "data" or "data" in parts[:-1] or rel.lower().endswith(DATA_EXT)

def file_has(path):
    op = gzip.open if path.endswith(".gz") else open
    try:
        with op(path, "rb") as f:
            prev = b""
            while True:
                b = f.read(1 << 20)
                if not b: return False
                if PAT.search(prev[-8:] + b): return True
                prev = b
    except (OSError, EOFError):
        return True          # unreadable data file: fail closed

def scan(root):
    bad = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        reld = os.path.relpath(d, root)
        if reld != "." and SPAT.search(reld): bad.append(reld + "/ (path)")
        for fn in files:
            rel = os.path.normpath(os.path.join(reld, fn))
            if not is_data(rel): continue
            if SPAT.search(rel): bad.append(rel + " (path)")
            elif file_has(os.path.join(d, fn)): bad.append(rel + " (content)")
    return bad

TAINT = object()
def drop_kalshi(o):
    """Kalshi filter for writers. A dict with a Kalshi key or string value is tainted as a whole; tainted
    items are removed from lists; a dict holding a tainted dict is tainted too. Returns (obj or None, n_dropped);
    None means the whole record is Kalshi-labelled and must not be written."""
    n = 0
    def rec(x):
        nonlocal n
        if isinstance(x, dict):
            if any(SPAT.search(str(k)) or (isinstance(v, str) and SPAT.search(v)) for k, v in x.items()): return TAINT
            out = {}
            for k, v in x.items():
                r = rec(v)
                if r is TAINT: return TAINT
                out[k] = r
            return out
        if isinstance(x, list):
            out = []
            for v in x:
                r = rec(v)
                if r is TAINT: n += 1; continue
                out.append(r)
            return out
        if isinstance(x, str) and SPAT.search(x): return TAINT
        return x
    r = rec(o)
    if r is TAINT: return None, n + 1
    return r, n

if __name__ == "__main__":
    roots = sys.argv[1:] or [os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))]
    bad = [f"{r}: {b}" for r in roots for b in scan(r)]
    if bad:
        print("KALSHI GUARD FAILED: Kalshi data found (D-005). Offending paths:"); print("\n".join(bad)); sys.exit(1)
    print("kalshi guard: OK (no Kalshi data files)")

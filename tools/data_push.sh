#!/usr/bin/env bash
# Commit + push everything new in the PRIVATE data checkout ($1) to its current branch. Kalshi guard first.
# Prints counts only. Usage: tools/data_push.sh DATA_DIR "message"
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"; d="$1"; msg="${2:-data}"
python3 "$here/kalshi_guard.py" "$d" >/dev/null || { echo "kalshi guard FAILED; not pushing"; exit 1; }
cd "$d" || exit 1
for p in ingame history plans status; do [ -e "$p" ] && git add -A "$p"; done
git diff --cached --quiet && { echo "nothing new"; exit 0; }
git -c user.name="ingame-bot" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" commit -q -m "$msg"
b=$(git rev-parse --abbrev-ref HEAD)
for i in 1 2 3 4 5 6; do
  git push -q origin "HEAD:$b" 2>/dev/null && { echo "pushed $(git diff --stat HEAD~1 HEAD | tail -1)"; exit 0; }
  sleep $((i*4)); git pull -q --rebase origin "$b" 2>/dev/null
done
echo "push failed"; exit 1

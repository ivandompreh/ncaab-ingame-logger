#!/usr/bin/env bash
# Clone the PRIVATE data repo over SSH (deploy key in $DATA_DEPLOY_KEY) into ./datarepo on branch $1
# (created as an orphan branch if missing). Never prints the key. Usage: tools/data_checkout.sh BRANCH
set -euo pipefail
: "${DATA_REPO:?set repo variable DATA_REPO, e.g. owner/ncaab-ingame-data}"
: "${DATA_DEPLOY_KEY:?secret DATA_DEPLOY_KEY missing}"
mkdir -p ~/.ssh && chmod 700 ~/.ssh
umask 077; printf '%s\n' "$DATA_DEPLOY_KEY" > ~/.ssh/data_key
# GitHub's published SSH host key (docs.github.com "GitHub's SSH key fingerprints")
echo "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl" >> ~/.ssh/known_hosts
export GIT_SSH_COMMAND="ssh -i ~/.ssh/data_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes"
echo "GIT_SSH_COMMAND=$GIT_SSH_COMMAND" >> "${GITHUB_ENV:-/dev/null}"
b="$1"
if git ls-remote --exit-code --heads "git@github.com:${DATA_REPO}.git" "$b" >/dev/null 2>&1; then
  git clone -q --depth 1 --single-branch -b "$b" "git@github.com:${DATA_REPO}.git" datarepo
else
  git clone -q --depth 1 "git@github.com:${DATA_REPO}.git" datarepo
  cp datarepo/ref/pmus_team_alias.tsv /tmp/alias.tsv
  (cd datarepo && git checkout -q --orphan "$b" && git rm -rq . && mkdir -p ref && cp /tmp/alias.tsv ref/ \
     && printf 'Monthly data branch %s (private). Raw PM US/ESPN data; never publish.\n' "$b" > README.md && git add -A \
     && git -c user.name=ingame-bot -c user.email=41898282+github-actions[bot]@users.noreply.github.com commit -qm "open $b" \
     && git push -q origin "$b")
fi
echo "data checkout: branch $b"

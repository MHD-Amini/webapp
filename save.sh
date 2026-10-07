#!/bin/bash
# Checkpoint helper: commit everything + push to GitHub (origin = https://github.com/MHD-Amini/webapp).
#   bash save.sh "message"            (never fails the caller; prints status)
cd "$(dirname "$0")"
MSG="${1:-checkpoint $(date -u +%Y-%m-%dT%H:%M:%SZ)}"
git add -A >/dev/null 2>&1
git commit -qm "$MSG" >/dev/null 2>&1 && echo "[save] committed: $MSG" || echo "[save] nothing to commit"
URL=$(git remote get-url origin 2>/dev/null | sed -E 's#^(https?://)[^@]*@#\1#')
# a concurrent autosave (run_v16_all.sh) may have pushed first -> integrate (rebase; grid jsons are idempotent: keep remote copy)
if ! timeout 120 git push -q origin HEAD:main >/dev/null 2>&1; then
  timeout 120 git fetch -q origin main >/dev/null 2>&1
  if ! git rebase -q origin/main >/dev/null 2>&1; then
    for f in $(git diff --name-only --diff-filter=U); do git checkout --theirs -- "$f" >/dev/null 2>&1; git add "$f"; done
    GIT_EDITOR=true git rebase --continue >/dev/null 2>&1 || git rebase --abort >/dev/null 2>&1
  fi
fi
if timeout 400 git push -q origin HEAD:main >/dev/null 2>&1; then
  echo "[save] pushed to $URL"
elif [ -n "$GSK_TOKEN" ] && echo "$URL" | grep -q genspark.ai; then
  AUTHED=$(echo "$URL" | sed -E 's#^(https?://)#\1x-access-token:'"$GSK_TOKEN"'@#')
  timeout 400 git -c credential.helper= push -q "$AUTHED" HEAD:refs/heads/main >/dev/null 2>&1 \
    && echo "[save] pushed to $URL" || echo "[save] push failed (will retry on next save)"
else
  echo "[save] push failed (will retry on next save)"
  # fallback: a git bundle of the commits not yet on origin -> AI Drive (small; recover with: git fetch <bundle> main)
  if [ -d /mnt/aidrive ]; then
    B="/mnt/aidrive/webapp_v15_unpushed_$(date -u +%Y-%m-%d).bundle"
    BASE=$(git rev-parse origin/main 2>/dev/null)
    if [ -n "$BASE" ] && git bundle create "$B" "$BASE..HEAD" >/dev/null 2>&1; then echo "[save] bundle written: $B"; fi
  fi
fi

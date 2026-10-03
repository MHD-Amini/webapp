#!/bin/bash
# Checkpoint helper: commit everything + push to GitHub (origin = https://github.com/MHD-Amini/webapp).
#   bash save.sh "message"            (never fails the caller; prints status)
cd "$(dirname "$0")"
MSG="${1:-checkpoint $(date -u +%Y-%m-%dT%H:%M:%SZ)}"
git add -A >/dev/null 2>&1
git commit -qm "$MSG" >/dev/null 2>&1 && echo "[save] committed: $MSG" || echo "[save] nothing to commit"
URL=$(git remote get-url origin 2>/dev/null | sed -E 's#^(https?://)[^@]*@#\1#')
if timeout 400 git push -q origin HEAD:main >/dev/null 2>&1; then
  echo "[save] pushed to $URL"
elif [ -n "$GSK_TOKEN" ] && echo "$URL" | grep -q genspark.ai; then
  AUTHED=$(echo "$URL" | sed -E 's#^(https?://)#\1x-access-token:'"$GSK_TOKEN"'@#')
  timeout 400 git -c credential.helper= push -q "$AUTHED" HEAD:refs/heads/main >/dev/null 2>&1 \
    && echo "[save] pushed to $URL" || echo "[save] push failed (will retry on next save)"
else
  echo "[save] push failed (will retry on next save)"
fi

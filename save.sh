#!/bin/bash
# Checkpoint helper: commit everything + push to the Genspark backup repo.
#   bash save.sh "message"            (never fails the caller; prints status)
cd "$(dirname "$0")"
MSG="${1:-checkpoint $(date -u +%Y-%m-%dT%H:%M:%SZ)}"
git add -A >/dev/null 2>&1
git commit -qm "$MSG" >/dev/null 2>&1 && echo "[save] committed: $MSG" || echo "[save] nothing to commit"
BACKUP_URL="https://www.genspark.ai/sb-git/me/genspark-1ad884aa-e169-4dc3-8b9b-7b58c42efb0b.git"
# prefer whatever remote the platform configured (origin / genspark), strip any embedded credentials
for R in origin genspark; do
  U=$(git remote get-url "$R" 2>/dev/null) && [ -n "$U" ] && { BACKUP_URL=$(echo "$U" | sed -E 's#^(https?://)[^@]*@#\1#'); break; }
done
if [ -n "$GSK_TOKEN" ]; then
  AUTHED=$(echo "$BACKUP_URL" | sed -E 's#^(https?://)#\1x-access-token:'"$GSK_TOKEN"'@#')
  timeout 400 git -c credential.helper= push -q "$AUTHED" HEAD:refs/heads/main >/dev/null 2>&1 \
    && echo "[save] pushed to $BACKUP_URL" || echo "[save] push failed (will retry on next save)"
fi

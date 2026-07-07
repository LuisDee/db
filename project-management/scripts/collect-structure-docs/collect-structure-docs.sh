#!/usr/bin/env bash
# Context loader: print every subfolder README.md with its location, so an
# agent session can load the repo layout in one shot. Run first in a session.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
IGNORE_FILE="$(dirname "${BASH_SOURCE[0]}")/.ignore"

while IFS= read -r f; do
    rel="${f#"$ROOT"/}"
    if [ -f "$IGNORE_FILE" ]; then
        skip=0
        while IFS= read -r pat; do
            [ -z "$pat" ] && continue
            case "$rel" in
                $pat|$pat/*) skip=1; break ;;
            esac
        done < "$IGNORE_FILE"
        [ "$skip" -eq 1 ] && continue
    fi
    echo "=== ${rel%/README.md}/ ==="
    cat "$f"
    echo
done < <(find "$ROOT" -mindepth 2 -name README.md -not -path '*/.git/*' | sort)

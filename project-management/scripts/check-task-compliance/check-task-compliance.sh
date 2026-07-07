#!/usr/bin/env bash
# Task compliance gater: sweeps tasks/ and fails on non-compliant filenames
# (purely numeric, TD-XXXX, non-kebab-case) or invalid frontmatter (only
# depends_on with existing workspace paths is allowed). Run after any task
# file create/edit/delete.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
fail=0

while IFS= read -r f; do
    base="$(basename "$f" .md)"
    [ "$base" = "README" ] && continue

    if [[ "$base" =~ ^[0-9]+$ ]]; then
        echo "FAIL: purely numeric filename: $f"; fail=1
    elif [[ "$base" =~ ^TD-[0-9]+$ ]]; then
        echo "FAIL: ticket-reference filename: $f"; fail=1
    elif [[ ! "$base" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]]; then
        echo "FAIL: not lowercase kebab-case: $f"; fail=1
    fi

    if [ "$(head -1 "$f")" = "---" ]; then
        fm="$(awk 'NR==1{next} /^---$/{exit} {print}' "$f")"
        while IFS= read -r line; do
            [ -z "${line// }" ] && continue
            if [[ "$line" =~ ^depends_on:([[:space:]]*(\[\])?)?$ ]]; then
                continue
            elif [[ "$line" =~ ^[[:space:]]+-[[:space:]] ]]; then
                dep="$(printf '%s' "$line" | sed -E 's/^[[:space:]]*-[[:space:]]*//')"
                if [ ! -f "$ROOT/${dep#/}" ]; then
                    echo "FAIL: dependency does not exist: '$dep' in $f"; fail=1
                fi
            else
                echo "FAIL: unsupported frontmatter property in $f: '$line'"; fail=1
            fi
        done <<< "$fm"
    fi
done < <(find "$ROOT/tasks" -name '*.md' | sort)

if [ "$fail" -ne 0 ]; then
    echo "Task compliance: FAILED"
    exit 1
fi
echo "Task compliance: OK"

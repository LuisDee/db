#!/usr/bin/env bash
# Git branch guard: the current branch must bind to a registered task file.
# Accepted patterns: <type>/<feature-slug> (conventional-commit type),
# TD-XXXX/<feature-slug>, or a bare <feature-slug>. The slug must exist as
# tasks/**/<feature-slug>.md. Run before starting to code.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
branch="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"
types="feat fix docs chore refactor test perf ci build"

if [[ "$branch" == */* ]]; then
    prefix="${branch%%/*}"
    slug="${branch#*/}"
    ok=0
    for t in $types; do [ "$prefix" = "$t" ] && ok=1; done
    [[ "$prefix" =~ ^TD-[0-9]+$ ]] && ok=1
    if [ "$ok" -ne 1 ]; then
        echo "FAIL: branch prefix '$prefix' is not a conventional type or TD-XXXX"
        exit 1
    fi
else
    slug="$branch"
fi

if [ -z "$(find "$ROOT/tasks" -name "$slug.md" -print -quit)" ]; then
    echo "FAIL: no task file tasks/**/$slug.md exists for branch '$branch'"
    exit 1
fi
echo "Branch '$branch' bound to task '$slug': OK"

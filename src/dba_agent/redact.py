from __future__ import annotations

import re

# Single-quoted string literals, incl. the '' escaped-quote-inside-literal form.
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
# Standalone numeric literals -- not digits embedded in an identifier
# (pg_catalog.table_2024 must survive untouched).
_NUMERIC_LITERAL = re.compile(r"(?<![\w])\d+(?:\.\d+)?(?![\w])")


def redact_literals(text: str) -> str:
    """Strip literal values out of captured SQL text before it leaves
    the agent (spec: 'literal values in any captured SQL text get
    redacted'). Query/table/column identifiers pass through unchanged --
    only string and numeric literals are replaced.
    """
    redacted = _STRING_LITERAL.sub("'***'", text)
    redacted = _NUMERIC_LITERAL.sub("?", redacted)
    return redacted

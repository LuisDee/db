from dba_agent.redact import redact_literals


def test_redacts_single_quoted_string_literal():
    assert redact_literals("WHERE email = 'alice@example.com'") == "WHERE email = '***'"


def test_redacts_numeric_literal():
    assert redact_literals("WHERE customer_id = 12345") == "WHERE customer_id = ?"


def test_redacts_multiple_literals_in_one_statement():
    text = "SELECT * FROM orders WHERE customer_id = 42 AND status = 'shipped'"
    assert redact_literals(text) == "SELECT * FROM orders WHERE customer_id = ? AND status = '***'"


def test_does_not_touch_identifiers_or_keywords():
    text = "SELECT customer_id, status FROM app.orders_2024"
    assert redact_literals(text) == text


def test_handles_escaped_quote_inside_literal():
    assert redact_literals("WHERE name = 'O''Brien'") == "WHERE name = '***'"


def test_empty_string_is_unchanged():
    assert redact_literals("") == ""

from dba_agent.slack import FakeSlackClient


def test_fake_slack_records_post():
    client = FakeSlackClient()

    ts = client.post_message("C123", "hello")

    assert client.posts == [{"channel": "C123", "text": "hello", "thread_ts": None, "ts": ts}]


def test_fake_slack_threads_reply_under_parent_ts():
    client = FakeSlackClient()

    alert_ts = client.post_message("C123", "alert fired")
    reply_ts = client.post_message("C123", "diagnosis", thread_ts=alert_ts)

    assert client.posts[1]["thread_ts"] == alert_ts
    assert reply_ts != alert_ts


def test_fake_slack_assigns_unique_ts_per_post():
    client = FakeSlackClient()

    first = client.post_message("C123", "one")
    second = client.post_message("C123", "two")

    assert first != second

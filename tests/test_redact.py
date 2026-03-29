"""Tests for secret redaction."""

from aion.redact import redact_secrets


def test_anthropic_key():
    text = "key is sk-ant-abc123def456ghi789jkl012mno345"
    assert "[REDACTED:anthropic_key]" in redact_secrets(text)


def test_openai_key():
    text = "OPENAI_API_KEY=sk-proj-abc123def456ghi789jkl012"
    assert "[REDACTED" in redact_secrets(text)


def test_github_pat():
    text = "token: ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    assert "[REDACTED:github_pat]" in redact_secrets(text)


def test_aws_access_key():
    text = "AWS key: AKIAIOSFODNN7EXAMPLE"
    assert "[REDACTED:aws_access_key]" in redact_secrets(text)


def test_bearer_token():
    text = "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.xxx"
    assert "[REDACTED:bearer_token]" in redact_secrets(text)


def test_no_false_positive():
    text = "This is normal text about API design and token-based auth concepts"
    assert text == redact_secrets(text)


def test_none_input():
    assert redact_secrets(None) is None
    assert redact_secrets("") == ""

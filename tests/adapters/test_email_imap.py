from __future__ import annotations

from patina.adapters.email_imap import ImapEmailAdapter
from patina.ports.email import EmailPort


def test_satisfies_email_port():
    adapter = ImapEmailAdapter(
        host="imap.example.com",
        port=993,
        username="test@example.com",
        password="test",
    )
    assert isinstance(adapter, EmailPort)


def test_platform():
    adapter = ImapEmailAdapter(
        host="imap.example.com",
        port=993,
        username="test@example.com",
        password="test",
    )
    assert adapter.platform == "imap"


def test_parse_message():
    adapter = ImapEmailAdapter(
        host="imap.example.com",
        port=993,
        username="test@example.com",
        password="test",
    )
    raw = (
        b"From: sender@example.com\r\n"
        b"To: recipient@example.com\r\n"
        b"Subject: Test Subject\r\n"
        b"Date: Mon, 25 Nov 2024 10:00:00 +0000\r\n"
        b"Message-ID: <test123@example.com>\r\n"
        b"\r\n"
        b"Hello, this is a test email."
    )
    msg = adapter._parse_message(raw)
    assert msg is not None
    assert msg.sender == "sender@example.com"
    assert msg.subject == "Test Subject"
    assert "test email" in msg.text
    assert msg.recipients == ["recipient@example.com"]

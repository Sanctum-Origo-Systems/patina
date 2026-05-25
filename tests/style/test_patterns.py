from __future__ import annotations

from patina.style.patterns import detect_patterns


def test_detects_greeting():
    messages = ["Hi team, please review this", "Hi all, update below"]
    result = detect_patterns(messages)
    assert result.greeting == "hi"


def test_detects_sign_off():
    messages = ["Great work!\nThanks,\nAlice", "Looks good.\nThanks"]
    result = detect_patterns(messages)
    assert result.sign_off == "thanks"


def test_high_formality():
    messages = [
        "I would like to inform you that the quarterly report has been submitted.",
        "Please find the updated documentation attached for your reference.",
    ]
    result = detect_patterns(messages)
    assert result.formality > 0.5


def test_low_formality():
    messages = ["hey can u check this", "don't think it's gonna work lol"]
    result = detect_patterns(messages)
    assert result.formality < 0.5


def test_emoji_rate():
    messages = ["Great work! :rocket:", "Nice :thumbsup: :star:", "No emoji here"]
    result = detect_patterns(messages)
    assert result.emoji_rate > 0


def test_question_rate():
    messages = ["How is this?", "Looks good", "Can you review?", "Done"]
    result = detect_patterns(messages)
    assert result.question_rate == 0.5


def test_empty_messages():
    result = detect_patterns([])
    assert result.sample_count == 0
    assert result.avg_length == 0


def test_sample_count():
    messages = ["one", "two", "three"]
    result = detect_patterns(messages)
    assert result.sample_count == 3


def test_avg_length():
    messages = ["hi", "hello"]
    result = detect_patterns(messages)
    assert result.avg_length == 3.5

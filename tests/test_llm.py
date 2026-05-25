from __future__ import annotations

from patina.llm import LLMPort, MockLLM


def test_mock_satisfies_protocol():
    llm: LLMPort = MockLLM()
    assert llm.tier == 3
    assert llm.context_window == 200_000


def test_mock_complete_returns_string():
    llm = MockLLM()
    result = llm.complete("test prompt")
    assert isinstance(result, str)
    assert len(result) > 0


def test_mock_draft_returns_string():
    llm = MockLLM()
    result = llm.draft("context", "style", "recipient")
    assert isinstance(result, str)
    assert len(result) > 0


def test_mock_records_calls():
    llm = MockLLM()
    llm.complete("hello")
    llm.draft("ctx", "sty", "rec")
    assert len(llm.calls) == 2
    assert llm.calls[0]["method"] == "complete"
    assert llm.calls[1]["method"] == "draft"

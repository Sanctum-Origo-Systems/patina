from __future__ import annotations

from typing import Literal, Protocol

from patina.models import Entity


class LLMPort(Protocol):
    @property
    def tier(self) -> Literal[2, 3]: ...

    @property
    def context_window(self) -> int: ...

    def complete(self, prompt: str, *, max_tokens: int = 1024) -> str: ...

    def extract_entities(self, text: str) -> list[Entity]: ...

    def classify(self, text: str, categories: list[str]) -> str: ...

    def synthesize(self, texts: list[str], question: str) -> str: ...

    def draft(self, context: str, style_profile: str, recipient_profile: str) -> str: ...


class MockLLM:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    @property
    def tier(self) -> Literal[2, 3]:
        return 3

    @property
    def context_window(self) -> int:
        return 200_000

    def complete(self, prompt: str, *, max_tokens: int = 1024) -> str:
        self.calls.append({"method": "complete", "prompt": prompt})
        return "Mock completion response."

    def extract_entities(self, text: str) -> list[Entity]:
        self.calls.append({"method": "extract_entities", "text": text})
        return []

    def classify(self, text: str, categories: list[str]) -> str:
        self.calls.append({"method": "classify", "text": text, "categories": categories})
        return categories[0] if categories else ""

    def synthesize(self, texts: list[str], question: str) -> str:
        self.calls.append({"method": "synthesize", "texts": texts, "question": question})
        return f"Synthesis of {len(texts)} texts regarding: {question}"

    def draft(self, context: str, style_profile: str, recipient_profile: str) -> str:
        self.calls.append(
            {
                "method": "draft",
                "context": context,
                "style_profile": style_profile,
                "recipient_profile": recipient_profile,
            }
        )
        return f"Draft reply regarding: {context[:50]}"

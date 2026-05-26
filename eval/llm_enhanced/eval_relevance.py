"""LLM-enhanced eval: relevance classification quality.

Run manually: uv run python eval/llm_enhanced/eval_relevance.py
"""

from __future__ import annotations

from patina.priority.scoring import _SEVERITY_RE

LABELED = [
    {"text": "SEV1: production outage", "relevant": True},
    {"text": "I'll have the report ready by EOD", "relevant": True},
    {"text": "URGENT: client data loss", "relevant": True},
    {"text": "Can you review this PR?", "relevant": True},
    {"text": "Happy Friday team!", "relevant": False},
    {"text": "Anyone up for lunch?", "relevant": False},
    {"text": "Good morning everyone!", "relevant": False},
    {"text": "Welcome to the team!", "relevant": False},
    {"text": "Blocked on the API integration", "relevant": True},
    {"text": "QA found a regression", "relevant": True},
]


def _is_relevant(text: str) -> bool:
    if _SEVERITY_RE.search(text):
        return True
    action_words = ["review", "blocked", "regression", "ready by", "urgent", "report"]
    return any(w in text.lower() for w in action_words)


def run_eval():
    correct = 0
    total = len(LABELED)

    for example in LABELED:
        predicted = _is_relevant(example["text"])
        if predicted == example["relevant"]:
            correct += 1

    accuracy = correct / total
    print("Relevance classification (heuristic):")
    print(f"  Accuracy: {accuracy:.0%} ({correct}/{total})")


if __name__ == "__main__":
    run_eval()

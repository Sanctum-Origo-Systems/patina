"""LLM-enhanced eval: entity extraction quality.

Run manually: uv run python eval/llm_enhanced/eval_entity_extraction.py
Requires a configured Tier 2 LLM.
"""

from __future__ import annotations

from patina.extraction import extract_entities_from_text

LABELED_MESSAGES = [
    {"text": "Hey <@U001> check the PR", "expected_types": ["person"]},
    {"text": "<@U001> and <@U002> please review", "expected_types": ["person", "person"]},
    {"text": "See <#C001|general> for details", "expected_types": ["topic"]},
    {"text": "Check https://example.com/docs", "expected_types": ["reference"]},
    {"text": "Just a normal message", "expected_types": []},
]


def run_eval():
    tp = 0
    fp = 0
    fn = 0

    for example in LABELED_MESSAGES:
        entities = extract_entities_from_text(example["text"])
        found_types = [e.type for e in entities]
        expected = list(example["expected_types"])

        for et in expected:
            if et in found_types:
                tp += 1
                found_types.remove(et)
            else:
                fn += 1
        fp += len(found_types)

    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)

    print("Entity extraction (Tier 1 regex):")
    print(f"  Precision: {precision:.2f}")
    print(f"  Recall:    {recall:.2f}")
    print(f"  F1:        {f1:.2f}")
    print(f"  TP={tp} FP={fp} FN={fn}")


if __name__ == "__main__":
    run_eval()

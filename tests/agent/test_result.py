from __future__ import annotations

from app.agent.result import _deterministic_validity_fallback, _extract_last_assistant_text


class _TextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _ToolUseBlock:
    type = "tool_use"
    text = "should be ignored"


def test_extract_last_assistant_text_handles_anthropic_content_blocks() -> None:
    messages = [
        {"role": "user", "content": "alert"},
        {
            "role": "assistant",
            "content": [
                _TextBlock("## Diagnosis\n"),
                _ToolUseBlock(),
                {"type": "text", "text": "Root cause: missing telemetry"},
            ],
        },
    ]

    assert _extract_last_assistant_text(messages) == (
        "## Diagnosis\n Root cause: missing telemetry"
    )


def test_deterministic_validity_fallback_returns_zero_without_evidence() -> None:
    assert (
        _deterministic_validity_fallback(
            validated_count=3,
            non_validated_count=0,
            evidence_count=0,
        )
        == 0.0
    )


def test_deterministic_validity_fallback_gives_bounded_nonzero_score() -> None:
    score = _deterministic_validity_fallback(
        validated_count=3,
        non_validated_count=1,
        evidence_count=4,
    )
    assert 0.4 <= score <= 0.9

import asyncio
import json

import src.agent_loop as agent_loop
from src.agent_loop import _StreamingRepeatGuard


def test_trips_on_four_repeated_substantial_lines():
    guard = _StreamingRepeatGuard(threshold=4)
    line = "I am now returning directly to the user's original task."

    assert guard.feed(line + "\n") is None
    assert guard.feed(line + "\n") is None
    assert guard.feed(line + "\n") is None
    assert guard.feed(line + "\n") == (line, 4)


def test_handles_lines_split_across_stream_chunks():
    guard = _StreamingRepeatGuard(threshold=3)
    line = "This substantial sentence arrived across several stream chunks."

    assert guard.feed(line[:20]) is None
    assert guard.feed(line[20:] + "\n" + line + "\n") is None
    assert guard.feed(line + "\n") == (line, 3)


def test_ignores_repeated_code_and_short_formatting_lines():
    guard = _StreamingRepeatGuard(threshold=3)

    assert guard.feed("```\nprint('same substantial code line')\n" * 3) is None
    assert guard.feed("```\n") is None
    assert guard.feed("### Results\n" * 4) is None
    assert guard.feed("| repeated table value | repeated table value |\n" * 4) is None


def test_nonconsecutive_substantial_lines_trip_within_rolling_window():
    guard = _StreamingRepeatGuard(threshold=3)
    repeated = "This substantial line keeps returning after nearby filler."
    other = "This different substantial line sits between repeated phrases."

    assert guard.feed(repeated + "\n" + repeated + "\n" + other + "\n") is None
    assert guard.feed(repeated + "\n") == (repeated, 3)


def test_detects_alternating_hesitation_loop_from_real_failure_shape():
    guard = _StreamingRepeatGuard(threshold=4)
    output = "\n".join([
        "Wait, I'll use write_file for the SKILL.md.",
        "Okay, I'm writing the SKILL.md now.",
        "Actually, I'll use write_file for the SKILL.md.",
        "Okay, I'm writing the SKILL.md now.",
        "Wait, I'll use write_file for the SKILL.md.",
        "Okay, I'm writing the SKILL.md now.",
        "Actually, I'll use write_file for the SKILL.md.",
    ]) + "\n"

    pattern, count = guard.feed(output)
    assert pattern == "Wait, I'll use write_file for the SKILL.md."
    assert count == 4


def test_agent_loop_privately_steers_after_stream_repetition(monkeypatch):
    repeated = "I am accidentally repeating this substantial sentence again."
    calls = []

    async def fake_stream(_candidates, messages, **kwargs):
        calls.append([dict(m) for m in messages])
        if len(calls) == 1:
            yield f'data: {json.dumps({"delta": (repeated + chr(10)) * 4})}\n\n'
        else:
            yield f'data: {json.dumps({"delta": "Recovered and finished the task."})}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10)
    monkeypatch.setattr(agent_loop, "get_setting", lambda key, default=None: default)

    async def collect():
        return [
            chunk
            async for chunk in agent_loop.stream_agent_loop(
                "http://x/v1",
                "gemma",
                [{"role": "user", "content": "Finish the task."}],
                max_rounds=4,
                relevant_tools={"bash"},
            )
        ]

    chunks = asyncio.run(collect())
    assert len(calls) == 2
    assert any(
        message.get("role") == "system"
        and "interrupted because you repeated the same phrase or intent" in message.get("content", "")
        for message in calls[1]
    )
    assert any("Recovered and finished the task." in chunk for chunk in chunks)


def test_agent_loop_stops_if_model_ignores_all_steering(monkeypatch):
    repeated = "I am still repeating this substantial sentence despite steering."
    calls = 0

    async def fake_stream(_candidates, messages, **kwargs):
        nonlocal calls
        calls += 1
        yield f'data: {json.dumps({"delta": (repeated + chr(10)) * 4})}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10)
    monkeypatch.setattr(agent_loop, "get_setting", lambda key, default=None: default)

    async def collect():
        return [
            chunk
            async for chunk in agent_loop.stream_agent_loop(
                "http://x/v1",
                "gemma",
                [{"role": "user", "content": "Finish the task."}],
                max_rounds=8,
                relevant_tools={"bash"},
            )
        ]

    chunks = asyncio.run(collect())
    assert calls == 3
    assert any("Loop guard stopped repeated output" in chunk for chunk in chunks)

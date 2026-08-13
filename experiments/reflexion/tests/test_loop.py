import pathlib
import sys
from dataclasses import dataclass

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import loop  # noqa: E402


@dataclass
class FakeGen:
    text: str
    input_tokens: int = 10
    output_tokens: int = 20
    latency_s: float = 0.1


@dataclass
class FakeVerdict:
    passed: bool
    violations: list


def test_converges_first_pass_when_clean():
    result = loop.run_reflexion(
        generate_fn=lambda feedback: FakeGen("good"),
        validate_fn=lambda text: [],
        critique_fn=lambda text: FakeVerdict(True, []),
    )
    assert result.converged and result.iterations == 1 and result.final == "good"


def test_feedback_carries_both_layers_and_loop_retries():
    calls = []

    def generate_fn(feedback):
        calls.append(feedback)
        return FakeGen("bad" if len(calls) == 1 else "good")

    result = loop.run_reflexion(
        generate_fn=generate_fn,
        validate_fn=lambda text: (
            [{"type": "invented_value", "detail": "999 not in artifacts"}] if text == "bad" else []
        ),
        critique_fn=lambda text: (
            FakeVerdict(False, [FakeVerdict(False, [])]) if text == "bad" else FakeVerdict(True, [])
        ),
    )
    assert result.converged and result.iterations == 2
    assert calls[0] is None
    assert "invented_value" in calls[1] and "999 not in artifacts" in calls[1]


def test_gives_up_after_max_iters():
    result = loop.run_reflexion(
        generate_fn=lambda feedback: FakeGen("always bad"),
        validate_fn=lambda text: [{"type": "wrong_value", "detail": "x"}],
        critique_fn=lambda text: FakeVerdict(True, []),
        max_iters=3,
    )
    assert not result.converged and result.iterations == 3
    assert len(result.attempts) == 3

"""Reason/act/observe trace shared by all Arm B agents (spec §8)."""
from dataclasses import dataclass, field


def _walk(value, out: set, skip_keys: frozenset = frozenset()) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        out.add(float(value))
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in skip_keys:
                continue
            _walk(item, out, skip_keys)
    elif isinstance(value, list):
        for item in value:
            _walk(item, out, skip_keys)


@dataclass
class Trace:
    calls: list = field(default_factory=list)

    def record(self, name: str, args: dict, result) -> None:
        self.calls.append({"name": name, "args": args, "result": result})

    def tool_names(self) -> list[str]:
        return [call["name"] for call in self.calls]

    def observed_numbers(self, skip_keys=frozenset()) -> set[float]:
        out: set[float] = set()
        skip = frozenset(skip_keys)
        for call in self.calls:
            _walk(call["result"], out, skip)
        return out

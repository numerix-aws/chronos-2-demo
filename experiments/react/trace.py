"""Reason/act/observe trace shared by all Arm B agents (spec §8)."""
from dataclasses import dataclass, field


def _walk(value, out: set) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        out.add(float(value))
    elif isinstance(value, dict):
        for item in value.values():
            _walk(item, out)
    elif isinstance(value, list):
        for item in value:
            _walk(item, out)


@dataclass
class Trace:
    calls: list = field(default_factory=list)

    def record(self, name: str, args: dict, result) -> None:
        self.calls.append({"name": name, "args": args, "result": result})

    def tool_names(self) -> list[str]:
        return [call["name"] for call in self.calls]

    def observed_numbers(self) -> set[float]:
        out: set[float] = set()
        for call in self.calls:
            _walk(call["result"], out)
        return out

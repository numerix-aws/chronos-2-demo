def violations(calls: list, allowed: frozenset) -> list:
    return [c for c in calls if c.get("name") not in allowed]

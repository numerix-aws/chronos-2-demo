def score_state(state, expected: dict) -> dict:
    actual = {"run_status": state.run_status,
              "has_bundle": state.bundle is not None}
    mismatches = [key for key, want in expected.items()
                  if actual.get(key) != want]
    return {"passed": not mismatches, "mismatches": mismatches}

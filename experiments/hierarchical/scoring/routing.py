def score_turn(predicted_intent: str, predicted_route: str, turn: dict) -> dict:
    intent_correct = predicted_intent == turn["expected_intent"]
    route_correct = predicted_route == turn["expected_route"]
    if intent_correct and route_correct:
        error = None
    elif intent_correct:
        error = "table_error"
    else:
        error = "intent_error"
    return {"intent_correct": intent_correct,
            "route_correct": route_correct, "error": error}

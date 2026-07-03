from graph.state import AnalysisState


def after_load_context(state: AnalysisState) -> str:
    if state.get("error"):
        return "handle_error"
    return "classify_request"


def after_classify(state: AnalysisState) -> str:
    if state.get("error"):
        return "handle_error"
    if state.get("clarification_needed"):
        return "ask_clarification"
    return "generate_code"


def after_generate_code(state: AnalysisState) -> str:
    if state.get("error"):
        return "handle_error"
    return "execute_code"


def after_observe(state: AnalysisState) -> str:
    if state.get("_sufficient"):
        return "finalize"
    attempt_count = state.get("attempt_count", 0)
    max_attempts = state.get("max_attempts", 3)
    if attempt_count < max_attempts:
        return "generate_code"
    return "show_stuck_point"

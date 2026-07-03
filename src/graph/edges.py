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
    # Only a truly unexpected framework-level failure is fatal and routes to
    # handle_error. A RETRYABLE code-generation failure (e.g. malformed JSON
    # from the model) leaves `state["error"]` unset and `generated_code` None
    # with a sanitized failure recorded; it flows through execute_code (which
    # pass-throughs when there is no code) into observe_and_decide, where it is
    # absorbed by the retry loop rather than dying (spec/agent.md "Partial
    # failure"). This keeps the graph topology identical to spec/agent.md's
    # Graph Assembly (generate_code -> {execute_code | handle_error}).
    if state.get("error"):
        return "handle_error"
    return "execute_code"


def after_observe(state: AnalysisState) -> str:
    if state.get("_sufficient"):
        return "finalize"
    attempt_count = state.get("attempt_count", 0)
    # Fallback mirrors graph.nodes._DEFAULT_MAX_ATTEMPTS (raised to 4 in Phase 2
    # to give the distinct named retry strategies room to run); load_context
    # seeds state["max_attempts"] so this fallback is only a safety net.
    max_attempts = state.get("max_attempts", 4)
    if attempt_count < max_attempts:
        return "generate_code"
    return "show_stuck_point"

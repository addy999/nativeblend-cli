"""NativeBlend local agent: orchestrates model generation locally."""

from .states import AgentState


def run_agent(state, api, *, on_log=None, on_progress=None):
    from .runner import run_agent as _run_agent
    return _run_agent(state, api, on_log=on_log, on_progress=on_progress)


__all__ = ["run_agent", "AgentState"]

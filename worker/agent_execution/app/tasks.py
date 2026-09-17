from app.agent_service import agent_service
from app.celery_app import celery_app


@celery_app.task(name="app.tasks.run_agent", bind=True)
def run_agent(self, run_id: str) -> None:
    """Executes one research agent run. Celery's job here is only to run
    this long enough without blocking the API (§2/§3 of the architecture
    brief) - all the actual orchestration (decomposition, VDB routing,
    search, grounding) lives in the LangGraph graph, invoked once from
    AgentService.run. Never a Celery task per graph node."""
    agent_service.run(run_id)


@celery_app.task(name="app.tasks.resume_agent", bind=True)
def resume_agent(self, run_id: str, answer: str) -> None:
    """Continues a run paused on request_clarification's interrupt() (§31) - a distinct task
    from run_agent since it re-enters the same checkpointed graph execution instead of starting
    a fresh one."""
    agent_service.resume(run_id, answer)

"""PipelineProgress — emit events to pipeline_events + WebSocket subscribers.

Pattern copied from orchestrator.TaskProgress. Each PipelineRunner has one
instance that writes events to DB and broadcasts to subscribed websockets.
"""
import logging
logger = logging.getLogger(__name__)

# Global subscribers map: {run_id: [WebSocket, ...]}
_subscribers: dict = {}


class PipelineProgress:
    """Implemented in T-2-008."""

    def __init__(self, run_id: int, db):
        self.run_id = run_id
        self.db = db

    async def emit_event(
        self,
        event_type: str,
        payload: dict | None = None,
        sprint_id: int | None = None,
        delivery_task_id: int | None = None,
        severity: str = 'info',
    ):
        raise NotImplementedError('Implemented in T-2-008')

    @staticmethod
    def subscribe(run_id: int, websocket):
        raise NotImplementedError('Implemented in T-2-008')

    @staticmethod
    def unsubscribe(run_id: int, websocket):
        raise NotImplementedError('Implemented in T-2-008')

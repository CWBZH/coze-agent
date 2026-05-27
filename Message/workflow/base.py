"""AI workflow engine abstraction."""
from __future__ import annotations

from abc import ABC, abstractmethod

from .types import WorkflowContext, WorkflowResult


class AIWorkflowEngine(ABC):
    @abstractmethod
    async def run(self, context: WorkflowContext) -> WorkflowResult:
        """Run one AI workflow turn and return a normalized result."""

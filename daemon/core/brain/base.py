from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class RemoteBrain(ABC):
    """
    Abstract interface for a Remote Reasoning Brain.
    Enforces strict input/output contracts.
    """

    @abstractmethod
    async def plan(self, task_summary: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a strictly structured plan based on the task summary.
        
        Args:
            task_summary: Summarized context (with hashed filenames).
            
        Returns:
            Dict conforming to the strict JSON schema.
            
        Raises:
            SchemaValidationError: If the output does not match the schema.
            BrainTimeoutError: If the remote brain times out.
        """
        pass

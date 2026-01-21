import logging
import uuid
import os
from typing import Dict, Any, List, Optional
from .openai import OpenAIBrain
from .claude import ClaudeBrain
from .qwen_executor import QwenExecutor
from .summarizer import Summarizer

logger = logging.getLogger(__name__)

class AgentController:
    """
    Main Controller for Hybrid Architecture.
    Flow: Input -> Summarizer -> Remote Brain (OpenAI/Claude) -> Executor (Qwen) -> Verifier.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Initialize Brains
        api_keys = config.get("api_keys", {})
        self.openai = OpenAIBrain(api_key=api_keys.get("openai", ""))
        self.claude = ClaudeBrain(api_key=api_keys.get("anthropic", ""))
        
        # Local Components
        self.executor = QwenExecutor() # Configures itself for localhost
        self.summarizer = Summarizer()
        
    async def process_task(self, goal: str, files: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Process a coding task.
        """
        task_id = str(uuid.uuid4())[:8]
        logger.info(f"Starting Task {task_id}: {goal}")
        
        # 1. Summarize
        logger.info("Step 1: Summarization")
        summary = self.summarizer.summarize_request(task_id, goal, files)
        
        # 2. Plan (Remote)
        plan = await self._get_plan(summary)
        if not plan:
            return {"status": "error", "message": "Planning failed"}
            
        # 3. Execute (Local)
        logger.info("Step 3: Execution (Qwen3-4B)")
        modified_files = await self.executor.execute(
            plan, 
            self.summarizer.get_file_map()
        )
        
        return {
            "status": "success",
            "task_id": task_id,
            "modified_files": modified_files,
            "plan": plan
        }

    async def _get_plan(self, summary: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # Try OpenAI
        try:
            logger.info("Step 2: Planning (OpenAI)")
            return await self.openai.plan(summary)
        except Exception as e:
            logger.warning(f"OpenAI Failed: {e}. Attempting Fallback.")
            
        # Try Claude
        try:
            logger.info("Step 2b: Planning Fallback (Claude)")
            return await self.claude.plan(summary)
        except Exception as e:
            logger.error(f"Claude Failed: {e}. Aborting.")
            return None

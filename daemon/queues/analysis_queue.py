"""
Autonoma Community Edition - Analysis Queue
Simplified queue with only local analysis (no cloud, no custom rules).
"""
import asyncio
import uuid
import logging
from typing import Dict, Any, List
from ..analysis.heuristics import HeuristicsEngine
# from ..analysis.llm_local import LocalLLM
from ..analysis.cache import AnalysisCache
from ..analysis.rules import RuleEngine
from ..analysis.config_manager import ConfigManager
from ..analysis.merge_utils import make_issue_key
from pathlib import Path

logger = logging.getLogger("autonoma")

class AnalysisQueue:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.heuristics = HeuristicsEngine()
        # self.llm_local = LocalLLM()
        self.cache = AnalysisCache()
        self.rules = RuleEngine()
        self.config_manager = ConfigManager()
        self.session_tracker = None

    async def add_task(self, task: Dict[str, Any]):
        await self.queue.put(task)

    async def process_queue(self):
        while True:
            task = await self.queue.get()
            try:
                await self.run_analysis(task)
            except Exception as e:
                print(f"Error processing analysis task: {e}")
            finally:
                self.queue.task_done()

    async def run_analysis(self, task: Dict[str, Any]):
        """Community Edition - Heuristics only (SEC001, SEC002)"""
        file_path_str = task.get("file_path")
        file_path = Path(file_path_str).resolve() if file_path_str else None
        content = task.get("content")
        project_id = task.get("project_id")
        raw_user_config = task.get("user_config", {})

        # Resolve config
        user_config = self.config_manager.resolve_config(file_path, raw_user_config)
        disabled_rules = set(user_config.get("disabled_rules", []))

        # Check cache
        file_hash = self.cache.compute_hash(content)
        cache_key = self.cache.generate_cache_key(file_hash, "1.0", "local", "1.0")
        
        cached_issues = self.cache.get(cache_key)
        if cached_issues:
            return cached_issues

        # Run heuristics (Community Edition core)
        issues = []
        try:
            heuristic_issues = self.heuristics.run(content, str(file_path) if file_path else "")
            for issue in heuristic_issues:
                if issue.get("id") not in disabled_rules:
                    issues.append(issue)
        except Exception as e:
            logger.error(f"Heuristics failed: {e}")

        # Cache results
        self.cache.set(cache_key, issues)
        
        return issues
        
    async def run_analysis_stream(self, task: Dict[str, Any]):
        """Streaming analysis - yields issues as discovered"""
        file_path = task.get("file_path")
        content = task.get("content")
        raw_user_config = task.get("user_config", {})
        user_config = self.config_manager.resolve_config(file_path, raw_user_config)
        disabled_rules = set(user_config.get("disabled_rules", []))
        all_issues = []
        seen_keys = set()
        
        try:
            # Heuristics
            yield {"type": "status", "message": "Running security analysis..."}
            
            for issue in self.heuristics.run(content, file_path):
                if issue.get("id") not in disabled_rules:
                    key = make_issue_key(issue)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        all_issues.append(issue)
                        yield {"type": "issue", "issue": issue}
            
            yield {"type": "complete", "total_issues": len(all_issues)}
            
        except Exception as e:
            yield {"type": "error", "message": str(e)}

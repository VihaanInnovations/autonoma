import asyncio
import uuid
import logging
from typing import Dict, Any, List
from ..analysis.heuristics import HeuristicsEngine
from ..analysis.llm_local import LocalLLM
from ..analysis.llm_cloud import CloudLLM
from ..analysis.cache import AnalysisCache
from ..analysis.rules import RuleEngine
from ..analysis.custom_rules import CustomRuleEngine
from ..db.db import get_db_connection
from ..analysis.rag import RAGEngine
from ..analysis.symbolic_engine import SymbolicEngine
from ..analysis.config_manager import ConfigManager
from ..analysis.llm_router import LLMRouter
from ..analysis.merge_utils import make_issue_key
from ..logging.flight_recorder import FlightRecorder
from pathlib import Path

logger = logging.getLogger("hybrid-reviewer")

class AnalysisQueue:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.heuristics = HeuristicsEngine()
        self.llm_local = LocalLLM() # Re-enabled
        # CloudLLM is instantiated per request to support per-user keys
        self.cache = AnalysisCache()
        self.rules = RuleEngine()
        self.rag = RAGEngine()
        self.symbolic = SymbolicEngine()
        self.config_manager = ConfigManager()
        self.custom_rule_engines: Dict[Path, CustomRuleEngine] = {}
        # Reference to server's session tracker (set from server.py)
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
        """Traditional analysis - returns all issues at once"""
        file_path_str = task.get("file_path")
        file_path = Path(file_path_str).resolve()
        
        # Update Semantic Engine context
        try:
             # Use repo_root if passed, else parent
             repo_root = task.get("repo_root")
             if repo_root:
                 self.heuristics.update_repo_path(Path(repo_root))
             else:
                 self.heuristics.update_repo_path(file_path.parent)
        except Exception as e:
             # logger.warning(f"Failed to update semantic path: {e}")
             pass

        content = task.get("content")
        project_id = task.get("project_id")
        raw_user_config = task.get("user_config", {})
        session_id = task.get("session_id", str(uuid.uuid4()))

        
        # Initialize Flight Recorder
        recorder = FlightRecorder(session_id)
        recorder.record_input(str(file_path), content)
        
        # Resolve Policy Config (Repo > User)
        user_config = self.config_manager.resolve_config(file_path, raw_user_config)
        print(f"DEBUG: resolved_config={user_config}")
        
        disabled_rules = set(user_config.get("disabled_rules", []))
        
        # 1. Compute Hash & Check Cache
        file_hash = self.cache.compute_hash(content)
        # Assuming defaults for rule_ver, etc. for now
        cache_key = self.cache.generate_cache_key(file_hash, "1.0", "local", "1.0")
        
        cached_issues = None # self.cache.get(cache_key) FORCE NO CACHE
        if cached_issues:
            # Update last_analysis timestamp if needed
            print(f"Cache hit for {file_path}")
            recorder.log_event("CACHE_HIT", {"cache_key": cache_key, "issue_count": len(cached_issues)})
            # In a real app we might want to callback/notify completion here
            return cached_issues

        # 2. Parallel Execution
        # Define tasks for each enabled engine
        issues = []
        tasks = []

        # DEBUG: log start
        try:
             with open("debug_queue.txt", "a") as f:
                 f.write(f"START ANALYSIS: {file_path}\n")
        except: pass
        
        # Heuristics (Sync wrapper)
        async def run_heuristics():
            res = self.heuristics.run(content, str(file_path))
            recorder.log_event("ENGINE_RESULT", {"engine": "heuristics", "count": len(res)})
            try:
                with open("debug_queue.txt", "a") as f:
                    f.write(f"  HEURISTICS: {len(res)} issues\n")
            except: pass
            return res
        tasks.append(run_heuristics())
        
        # Symbolic (Sync wrapper)
        async def run_symbolic():
            res = self.symbolic.analyze(content)
            recorder.log_event("ENGINE_RESULT", {"engine": "symbolic", "count": len(res)})
            return res
        # tasks.append(run_symbolic())
        
        # Custom Rules (Enterprise)
        async def run_custom_rules():
            repo_root = None
            
            # 1. Prioritize finding compliance_rules.yaml locally (Support for monorepos/sub-projects)
            current = file_path.parent
            while str(current.parent) != str(current):
                if (current / "compliance_rules.yaml").exists():
                    repo_root = current
                    break
                current = current.parent

            # 2. If not found, use ConfigManager (Standard Project Root)
            if not repo_root:
                config_path = self.config_manager.find_config_file(str(file_path))
                if config_path:
                    repo_root = Path(config_path).parent
            
            # 3. Fallback
            if not repo_root:
                # Fallback: traverse up to find .git
                current = file_path.parent
                while str(current.parent) != str(current):
                    if (current / ".git").exists():
                        repo_root = current
                        break
                    current = current.parent
            
            if not repo_root:
                repo_root = file_path.parent
            
            if repo_root not in self.custom_rule_engines:
                self.custom_rule_engines[repo_root] = CustomRuleEngine(repo_root)
            
            engine = self.custom_rule_engines[repo_root]
            res = engine.scan(content, file_path)
            recorder.log_event("ENGINE_RESULT", {"engine": "custom_rules", "count": len(res)})
            return res
        # tasks.append(run_custom_rules())
        
        # LLM Local (Re-enabled)
        if False: # user_config.get("enable_local_llm"):
             async def run_local():
                 rag_results = self.rag.query_context(content)
                 local_model = user_config.get("local_model", "llama3")
                 # Accumulate stream for standard analysis
                 local_issues = []
                 full_reasoning = ""
                 async for issue in self.llm_local.analyze_stream(content, context=rag_results, model=local_model):
                     if isinstance(issue, dict) and issue.get("type") != "error":
                         local_issues.append(issue)
                         full_reasoning += str(issue.get("message", "")) + "\n"
                 
                 recorder.record_reasoning("Local Analysis", full_reasoning, local_model)
                 recorder.log_event("ENGINE_RESULT", {"engine": "local_llm", "count": len(local_issues)})
                 return local_issues
             tasks.append(run_local())
             
        # LLM Cloud
        if False: # user_config.get("enable_cloud_llm"):
            # PRICING CHECK - Use user_id from API key (preferred) or fallback to project_id
            user_id = task.get("user_id")
            tier = task.get("tier", "free")
            
            # If no user_id from API key, try project_id fallback
            if not user_id:
                project_id = task.get("project_id", "default")
                from daemon.db.db import get_project_owner
                user_id = get_project_owner(project_id)
                if not user_id:
                    user_id = "anonymous"  # Default for free tier
            
            from daemon.pricing.pricing_manager import PricingManager
            pricing = PricingManager()
            
            if pricing.check_access(user_id, "cloud_llm"):
                 async def run_cloud():
                     api_keys = user_config.get("api_keys", {})
                     provider = user_config.get("cloud_provider", "openai")
                     cloud_model = user_config.get("cloud_model")
                     cloud_llm = CloudLLM(api_keys)
                     res = await cloud_llm.analyze(content, provider=provider, model=cloud_model)
                     recorder.log_event("ENGINE_RESULT", {"engine": "cloud_llm", "count": len(res)})
                     return res
                 tasks.append(run_cloud())
            else:
                 # Add warning issue
                 recorder.log_event("PRICING_DENIAL", {"feature": "cloud_llm", "user_id": user_id})
                 issues.append({
                     "id": "PRICING001",
                     "line": 1,
                     "message": "Feature 'Cloud LLM' requires PRO or ENTERPRISE tier. Please upgrade.",
                     "type": "info",
                     "severity": "low",
                     "source": "pricing_gate"
                 })

        # Execute all tasks concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Flatten results (handling exceptions)
        for res in results:
            if isinstance(res, list):
                if disabled_rules:
                   res = [i for i in res if i.get("id") not in disabled_rules]
                issues.extend(res)
            elif isinstance(res, Exception):
                import traceback
                print(f"Engine failure: {res}")
                traceback.print_tb(res.__traceback__)
                recorder.log_event("ENGINE_FAILURE", {"error": str(res)})

        # 5. Cache Results
        # self.cache.set(cache_key, issues)
        # recorder.log_event("ANALYSIS_COMPLETE", {"total_issues": len(issues)})
        
        # print(f"Analysis complete for {file_path}: {len(issues)} issues found.")
        
        # Save to DB (Issue table) - Encrypted
        try:
            from ..db.db import save_analysis_result
            # Saving is blocking, but fast enough for SQLite on local machine. 
            # In high load, should be offloaded to another async task/thread.
            user_id = task.get("user_id")  # Get user_id from task
            # save_analysis_result(str(file_path), content, issues, project_id, user_id)
        except ImportError:
            pass # DB module might be adjusting
        
        return issues
        
    async def run_analysis_stream(self, task: Dict[str, Any]):
        """
        Streaming analysis - yields issues as they're discovered.
        Returns async generator that yields events.
        """
        # Note: Streaming flight recorder integration is trickier. 
        # For now, we only instrument the batch analysis which is used by CI/CD and CLI default.
        # Future: Add FlightRecorder context to producers.
        file_path = task.get("file_path")
        content = task.get("content")
        raw_user_config = task.get("user_config", {})
        user_config = self.config_manager.resolve_config(file_path, raw_user_config)
        disabled_rules = set(user_config.get("disabled_rules", []))
        all_issues = []
        seen_issue_keys = set()
        
        try:
            # 1. Compute Hash & Check Cache
            file_hash = self.cache.compute_hash(content)
            # CACHE BUST: Bump to 1.1 to force re-scan with new V2 Heuristics
            cache_key = self.cache.generate_cache_key(file_hash, "1.1", "local", "1.1")
            
            cached_issues = self.cache.get(cache_key)
            if cached_issues:
                print(f"Cache hit for {file_path}")
                # Stream cached issues immediately
                for issue in cached_issues:
                    yield {"type": "issue", "issue": issue}
                yield {"type": "complete", "total_issues": len(cached_issues)}
                return
            
            # Parallel Streaming Architecture:
            # 1. Create a queue for incoming issues
            stream_queue = asyncio.Queue()
            # 2. Create tasks/generators that feed this queue
            active_producers = 0

            async def producer_heuristics():
                yield {"type": "status", "message": "Running heuristics..."}
                for issue in self.heuristics.run(content, file_path):
                     yield {"type": "issue", "issue": issue}
            
            async def producer_symbolic():
                yield {"type": "status", "message": "Running symbolic analysis..."}
                for issue in self.symbolic.analyze(content):
                    yield {"type": "issue", "issue": issue}

            # Router Logic
            router = LLMRouter(user_config)
            route_decision = router.route_analysis()
            
            # Local LLM (Re-enabled)
            async def producer_local_llm():
                if route_decision in ["local", "both"] and user_config.get("enable_local_llm"):
                    yield {"type": "status", "message": "Running Local AI (Llama-3)..."}
                    rag_results = self.rag.query_context(content)
                    local_model = user_config.get("local_model", "llama3")
                    async for issue in self.llm_local.analyze_stream(content, context=rag_results, model=local_model):
                        yield {"type": "issue", "issue": issue}
            
            async def producer_cloud_llm():
                 if route_decision in ["cloud", "both"] and user_config.get("enable_cloud_llm"):
                    yield {"type": "status", "message": "Running Cloud AI..."}
                    api_keys = user_config.get("api_keys", {})
                    provider = user_config.get("cloud_provider", "openai")
                    cloud_model = user_config.get("cloud_model")
                    cloud_llm = CloudLLM(api_keys)
                    async for issue in cloud_llm.analyze_stream(content, provider=provider, model=cloud_model):
                        yield {"type": "issue", "issue": issue}

            # Helper to run a generator and put items in queue
            async def run_producer(gen):
                 try:
                     async for item in gen:
                         await stream_queue.put(item)
                 except Exception as e:
                     await stream_queue.put({"type": "error", "message": str(e)})
                 finally:
                     await stream_queue.put(None) # Sentinel

            # Start producers
            generators = [producer_heuristics(), producer_symbolic(), producer_local_llm(), producer_cloud_llm()]
            for gen in generators:
                asyncio.create_task(run_producer(gen))
                active_producers += 1

            # Consume queue
            while active_producers > 0:
                item = await stream_queue.get()
                if item is None:
                    active_producers -= 1
                else:
                    # Filter logic if it's an issue
                    if item.get("type") == "issue" and item.get("issue"):
                        if item["issue"].get("id") not in disabled_rules:
                            key = make_issue_key(item["issue"])
                            if key not in seen_issue_keys:
                                seen_issue_keys.add(key)
                                all_issues.append(item["issue"])
                                yield item
                    else:
                        yield item
            
            # 5. Cache Results
            self.cache.set(cache_key, all_issues)
            print(f"Analysis complete for {file_path}: {len(all_issues)} issues found.")
            
            # Final completion event
            yield {"type": "complete", "total_issues": len(all_issues)}
            
        except Exception as e:
            yield {"type": "error", "message": str(e)}
            raise


    async def run_autonomous_loop(self, directory_path: str, project_id: str, user_id: str):
        """
        L5 AUTONOMY LOOP (HOTWIRE)
        Scans directory, finds bugs, and fixes them automatically.
        """
        import os
        import uuid
        from pathlib import Path
        from daemon.analysis.fix_engine import FixEngine
        from daemon.logging.flight_recorder import FlightRecorder
        
        # Initialize Flight Recorder for this autonomous session
        session_id = str(uuid.uuid4())
        recorder = FlightRecorder(session_id)
        recorder.log_event("AUTONOMY_SESSION_START", {"project_id": project_id, "directory": directory_path})
        
        # Track session
        import time
        session_info = {
            "status": "running",
            "start_time": time.time(),
            "project_id": project_id,
            "target": directory_path,
            "files_processed": 0,
            "files_total": 0,
            "fixes_applied": 0,
            "errors": [],
            "current_file": None
        }
        if self.session_tracker:
            self.session_tracker[session_id] = session_info
        
        logger.info(f"L5 AUTONOMY: Starting loop for {directory_path} (Session: {session_id})")
        
        target_path = Path(directory_path).resolve()
        files_to_process = []
        
        if target_path.is_file():
            files_to_process.append(target_path)
        else:
            for root, dirs, files in os.walk(target_path):
                if '.git' in dirs: dirs.remove('.git')
                if 'venv' in dirs: dirs.remove('venv')
                if '__pycache__' in dirs: dirs.remove('__pycache__')
                
                for file in files:
                    if file.endswith(('.py', '.js', '.ts', '.java', '.go', '.rs')):
                        files_to_process.append(Path(root) / file)
        
        try:
            with open("debug_autonomy_loop.txt", "w") as f:
                f.write(f"Target: {target_path}\nFiles found: {len(files_to_process)}\n")
                f.write(str([str(f) for f in files_to_process]))
        except: pass
        
        print(f"DEBUG: L5 AUTONOMY: found {len(files_to_process)} target files: {[str(f) for f in files_to_process]}")
        
        # Update session info
        if self.session_tracker and session_id in self.session_tracker:
            self.session_tracker[session_id]["files_total"] = len(files_to_process)
        
        fixed_count = 0
        
        for file_path in files_to_process:
            print(f"DEBUG: Processing {file_path}")
            # Update current file
            if self.session_tracker and session_id in self.session_tracker:
                self.session_tracker[session_id]["current_file"] = str(file_path)
                self.session_tracker[session_id]["files_processed"] += 1
            try:
                content = file_path.read_text(encoding='utf-8', errors='ignore')
                
                # 1. Analyze
                task = {
                    "file_path": str(file_path),
                    "content": content,
                    "project_id": project_id,
                    "user_id": user_id,
                    "user_config": {
                        "enable_local_llm": True,
                        "local_model": "qwen2.5-coder-lora" # Use our fine-tuned model
                    }
                }
                
                # Use standard run_analysis to get issues
                issues = await self.run_analysis(task)
                print(f"DEBUG: Analysis returned {len(issues)} issues for {file_path}")
                try:
                    with open("debug_queue.txt", "a") as f:
                        f.write(f"ISSUES FOUND: {len(issues)}\n")
                        f.write(f"CONTENT: {str(issues)}\n")
                except: pass
                
                # 2. Filter HIGH severity
                # 2. Filter Severity (Aggressive: Fix ALL)
                # high_sev_issues = [i for i in issues if i.get("severity") == "high"]
                high_sev_issues = issues # FIX ALL ISSUES (Demo Request)
                
                if high_sev_issues:
                    print(f"DEBUG: Engaging FixEngine for {len(high_sev_issues)} issues")
                    logger.info(f"L5 AUTONOMY: Found {len(high_sev_issues)} CRITICAL issues in {file_path.name}. Engaging Neural Fixer...")
                    recorder.log_event("HIGH_SEVERITY_DETECTED", {"file": str(file_path), "count": len(high_sev_issues)})
                    
                    # 3. Fix Loop
                    fix_engine = FixEngine(repo_path=target_path)
                    
                    # Track fixed issues to prevent duplicate fixes
                    fixed_issue_ids = set()
                    
                    for issue in high_sev_issues:
                        issue_id = issue.get('id', 'UNKNOWN')
                        issue_msg = issue.get('message', 'No description')
                        issue_line = issue.get('line', 0)
                        
                        # Skip if this issue was already fixed in this session
                        if issue_id in fixed_issue_ids:
                            logger.info(f"L5 AUTONOMY: Skipping {issue_id} - already fixed in this session")
                            continue
                        
                        # Read current content (re-read after each fix to get latest state)
                        current_content = file_path.read_text(encoding='utf-8', errors='ignore')
                        
                        # Check if issue is already fixed by verifying the pattern no longer matches
                        # This prevents re-fixing issues that were already resolved
                        pass
                        
                        logger.info(f"L5 AUTONOMY: Fixing {issue_id}: {issue_msg}")
                        
                        try:
                            # Re-read content in case previous fix changed the file
                            current_content = file_path.read_text(encoding='utf-8', errors='ignore')
                            logger.info(f"L5 AUTONOMY: Calling FixEngine for {issue_id}...")
                            print(f"DEBUG: Calling await fix_engine.generate_and_verify_fix for {issue_id}...")
                            import time
                            ts_start = time.time()
                            try:
                                # TIMEOUT HARDENING: Prevent one file from hanging the batch
                                fixed_code, result = await asyncio.wait_for(
                                    fix_engine.generate_and_verify_fix(
                                        code_frame=current_content,
                                        issue_description=issue_msg,
                                        file_path=file_path,
                                        failing_test_name=f"test_l5_{file_path.stem}", 
                                        max_retries=2
                                    ),
                                    timeout=60.0  # 60s per fix max
                                )
                                print(f"DEBUG: FixEngine returned after {time.time() - ts_start:.2f}s")
                            except asyncio.TimeoutError:
                                print(f"DEBUG: FixEngine TIMED OUT for {file_path.name}")
                                logger.error(f"L5 AUTONOMY: Timeout generating fix for {file_path.name}")
                                fixed_code, result = None, None
                            except Exception as e:
                                print(f"DEBUG: FixEngine CRASHED: {e}")
                                import traceback
                                traceback.print_exc()
                                fixed_code, result = None, None
                            
                            # Safety check: Verify file on disk matches what FixEngine returned
                            # This catches cases where FixEngine modified disk but returned original code
                            try:
                                disk_content = file_path.read_text(encoding='utf-8', errors='ignore')
                                if disk_content != fixed_code and fixed_code == current_content:
                                    # File on disk was modified but FixEngine returned original
                                    # This indicates a rollback failure or inconsistent state
                                    logger.warning(f"L5 AUTONOMY: File state mismatch detected for {issue_id}")
                                    logger.warning(f"  Disk content differs from FixEngine return value")
                                    logger.warning(f"  Attempting to restore original content...")
                                    file_path.write_text(current_content, encoding='utf-8')
                                    fixed_code = current_content  # Ensure we use original
                            except Exception as disk_check_error:
                                logger.error(f"L5 AUTONOMY: Error checking disk state: {disk_check_error}")
                            
                            # Log result details
                            if result:
                                logger.info(f"L5 AUTONOMY: FixEngine returned result: all_passed={result.all_passed}, "
                                          f"invariant_1={result.invariant_1_passed}, error={result.error_message}")
                            else:
                                logger.warning(f"L5 AUTONOMY: FixEngine returned None result (likely planning/execution failed)")
                            
                            # Check if code changed
                            if fixed_code and fixed_code != current_content:
                                # Apply Fix!
                                file_path.write_text(fixed_code, encoding='utf-8')
                                fixed_count += 1
                                fixed_issue_ids.add(issue_id)  # Mark as fixed to prevent duplicates
                                # Update session tracker
                                if self.session_tracker and session_id in self.session_tracker:
                                    self.session_tracker[session_id]["fixes_applied"] = fixed_count
                                logger.info(f"L5 AUTONOMY: FIXED {issue_id} [APPLIED]")
                                
                                recorder.log_event("AUTONOMOUS_FIX_APPLIED", {
                                    "file": str(file_path),
                                    "issue_id": issue_id,
                                    "issue": issue_msg
                                })
                            else:
                                # Determine why no changes
                                if fixed_code == current_content:
                                    reason = "FixEngine returned original code unchanged"
                                elif not fixed_code:
                                    reason = "FixEngine returned None/empty code"
                                else:
                                    reason = "Unknown reason - code comparison failed"
                                
                                logger.warning(f"L5 AUTONOMY: Failed to fix {issue_id} - {reason}")
                                if result and result.error_message:
                                    logger.warning(f"L5 AUTONOMY: FixEngine error message: {result.error_message}")
                                
                                recorder.log_event("AUTONOMOUS_FIX_FAILED", {
                                    "file": str(file_path),
                                    "issue_id": issue_id,
                                    "reason": reason,
                                    "error_message": result.error_message if result and result.error_message else None
                                })
                        except Exception as fix_error:
                            error_msg = f"Error fixing {issue_id}: {str(fix_error)}"
                            try:
                                with open("debug_errors.txt", "a") as f:
                                    f.write(f"FIX ERROR {issue_id}: {fix_error}\n")
                                    import traceback
                                    f.write(traceback.format_exc() + "\n")
                            except: pass
                            logger.error(f"L5 AUTONOMY: {error_msg}", exc_info=True)
                            if self.session_tracker and session_id in self.session_tracker:
                                self.session_tracker[session_id]["errors"].append({
                                    "file": str(file_path),
                                    "issue_id": issue_id,
                                    "error": str(fix_error)
                                })
                            recorder.log_event("AUTONOMOUS_FIX_ERROR", {
                                "file": str(file_path),
                                "issue_id": issue_id,
                                "error": str(fix_error)
                            })
                            
            except Exception as e:
                error_msg = f"Error processing {file_path}: {str(e)}"
                logger.error(f"L5 AUTONOMY ERROR: {error_msg}", exc_info=True)
                
                try:
                    with open("debug_errors.txt", "a") as f:
                        f.write(f"ERROR processing {file_path}: {e}\n")
                        import traceback
                        f.write(traceback.format_exc() + "\n")
                except: pass
                
                if self.session_tracker and session_id in self.session_tracker:
                    self.session_tracker[session_id]["errors"].append({
                        "file": str(file_path),
                        "error": str(e)
                    })
                recorder.log_event("AUTONOMY_ERROR", {"file": str(file_path), "error": str(e)})
        
        # Mark session as complete
        if self.session_tracker and session_id in self.session_tracker:
            self.session_tracker[session_id]["status"] = "complete"
            self.session_tracker[session_id]["current_file"] = None
            import time
            self.session_tracker[session_id]["end_time"] = time.time()
            self.session_tracker[session_id]["duration"] = (
                self.session_tracker[session_id]["end_time"] - 
                self.session_tracker[session_id]["start_time"]
            )
        
        logger.info(f"L5 AUTONOMY COMPLETE. Total fixes applied: {fixed_count}")
        recorder.log_event("AUTONOMY_SESSION_COMPLETE", {"fixes_applied": fixed_count})
        return {"status": "complete", "fixes_applied": fixed_count, "session_id": session_id}

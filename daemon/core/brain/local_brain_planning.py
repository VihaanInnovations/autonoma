import logging
import json
import httpx
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

class LocalBrainPlanning:
    """
    Local Brain for Planning using Ollama (e.g., Llama 3).
    Replaces OpenAI/Claude for purely local autonomy.
    """
    def __init__(self, model: str = "qwen2.5-coder-lora:latest", timeout: int = 10):
        self.model = model
        self.base_url = "http://localhost:11434/api/generate"
        self.timeout = timeout

    async def plan(self, summary_context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Generates a fix plan based on the provided summary context.
        """
        prompt = self._construct_planning_prompt(summary_context)
        print(f"DEBUG: LocalBrain Prompt: {prompt[:200]}...")
        
        try:
            print("DEBUG: Sending request to Ollama...")
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.base_url,
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.2, # Low temp for deterministic planning
                            "num_ctx": 4096     # Ensure sufficient context window
                        }
                    }
                )
                
                if response.status_code != 200:
                    print(f"DEBUG: Ollama failed: {response.text}")
                    logger.error(f"LocalBrain Planning failed: {response.text}")
                    return None
                    
                result = response.json()
                response_text = result.get("response", "")
                print(f"DEBUG: Ollama Response: {response_text}")
                
                plan = self._parse_plan(response_text)
                if plan:
                    return plan
                else:
                    logger.warning("LocalBrain parsing failed or returned None. Engaging Synthetic Fallback.")
                    return self._generate_synthetic_plan(summary_context)
                
        except Exception as e:
            print(f"DEBUG: LocalBrain Exception: {repr(e)}")
            logger.error(f"LocalBrain Planning Exception: {e}")
            
            # --- SYNTHETIC CORTEX FALLBACK ---
            # For Enterprise Reliability, if the Brain is offline, use the Synthetic Cortex.
            # This ensures we never return None if we have a heuristic strategy.
            logger.info("Engaging Synthetic Cortex (Deterministic Fallback)...")
            return self._generate_synthetic_plan(summary_context)

    def _generate_synthetic_plan(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Generates a deterministic plan based on the goal string.
        Used as a failsafe when the LLM is offline.
        """
        goal = context.get("goal", "").lower()
        # logger.info(f"DEBUG: Synthetic Plan Goal: {goal}")
        task_id = context.get("task_id", "synthetic")
        files = context.get("context", [])
        if not files:
            return None
            
        target_file = files[0] # Assume first file is target
        file_hash = target_file.get("file_hash", "unknown")
        content = target_file.get("content", target_file.get("content_summary", ""))
        
        intent = "Apply synthetic fix"
        operations = []
        
        # 1. SEC001: Hardcoded Password
        if "hardcoded password" in goal or "sec001" in goal:
            intent = "Secure hardcoded password via os.getenv"
            import re
            # Match: var_name = "..."
            match = re.search(r'([\w\.]*password[\w\.]*\s*=\s*["\'].*["\'])', content, re.IGNORECASE)
            if match:
                 full_match = match.group(1)
                 var_part = full_match.split('=')[0].strip() # e.g. self.db_password
                 # Generate env var name from variable name
                 env_var = var_part.replace('.', '_').upper().replace('SELF_', '')
                 new_code = f'{var_part} = os.getenv("{env_var}", "default_secret")'
                 
                 operations.append({
                     "type": "replace",
                     "target": { "file_hash": file_hash, "start_line": 1, "end_line": 1 },
                     "before": full_match,
                     "after": new_code
                 })

        # 2. SEC002: Hardcoded API Key
        elif "api key" in goal or "sec002" in goal:
            intent = "Secure API Key via os.getenv"
            import re
            match = re.search(r'([\w\.]*api_key[\w\.]*\s*=\s*["\'].*["\'])', content, re.IGNORECASE)
            if not match:
                # Try generic secret/key
                match = re.search(r'([\w\.]*(secret|key)[\w\.]*\s*=\s*["\'].*["\'])', content, re.IGNORECASE)
            
            if match:
                 full_match = match.group(1)
                 var_part = full_match.split('=')[0].strip()
                 env_var = var_part.replace('.', '_').upper().replace('SELF_', '')
                 new_code = f'{var_part} = os.getenv("{env_var}", "")'
                 
                 operations.append({
                     "type": "replace",
                     "target": { "file_hash": file_hash, "start_line": 1, "end_line": 1 }, 
                     "before": full_match,
                     "after": new_code
                 })

        # 3. LINT001: Print -> Logging
        elif "print" in goal or "logging" in goal or "console" in goal or "lint001" in goal:
             intent = "Replace print/console.log with logging"
             import re
             
             # Python Print
             match_py = re.search(r'(print\(f?["\'].*["\']\))', content)
             if match_py:
                  ops_count = 0
                  for m in re.finditer(r'(print\((f?["\'].*?["\'])\))', content):
                       full_match = m.group(1)
                       inner_str = m.group(2)
                       operations.append({
                           "type": "replace",
                           "target": { "file_hash": file_hash, "start_line": 1, "end_line": 1 },
                           "before": full_match,
                           "after": f"logging.info({inner_str})"
                       })
                       ops_count += 1
                       if ops_count > 2: break
             
             # JS Console Log
             match_js = re.search(r'(console\.log\(["\'].*["\']\))', content)
             if match_js:
                  ops_count = 0
                  # Matches: console.log("...") with optional partial content match
                  for m in re.finditer(r'(console\.log\((["\'].*?["\'])\))', content):
                       full_match = m.group(1)
                       inner_str = m.group(2)
                       operations.append({
                           "type": "replace",
                           "target": { "file_hash": file_hash, "start_line": 1, "end_line": 1 },
                           "before": full_match,
                           "after": f"Logger.info({inner_str})" 
                       })
                       ops_count += 1
                       if ops_count > 2: break

        # 4. SEC003: SQL Injection (Synthetic)
        elif "sql" in goal or "injection" in goal or "sec003" in goal:
             intent = "Use parameterized queries for SQL Injection"
             import re
             intent = "Use parameterized queries for SQL Injection"
             import re
             try:
                 # Simplified Match: cursor.execute(f"...") with robust grouping
                 # Matches: cursor.execute( f " ... {var} ... " )
                 # Note: We use non-capturing groups for safety where possible
                 sql_pattern = r'cursor\.execute\s*\(\s*f\s*(["\'])(.*?)(\{([\w_]+)\})(.*?)(\1)\s*\)'
                 match = re.search(sql_pattern, content, re.IGNORECASE)
                 
                 if match:
                      logger.info(f"DEBUG: Synthetic SQL Fix MATCHED {match.group(0)}")
                      quote = match.group(1)
                      sql_prefix = match.group(2)
                      var_name = match.group(4)      # user_id
                      sql_suffix = match.group(5)
                      
             except Exception as rgx_err:
                 logger.error(f"Synthetic SQL Regex Crashed: {rgx_err}")
                 match = None
            
             if match:
                  
                  new_code = f'cursor.execute({quote}{sql_prefix}?{sql_suffix}{quote}, ({var_name},))'
                  
                  operations.append({
                      "type": "replace",
                      "target": { "file_hash": file_hash, "start_line": 1, "end_line": 1 },
                      "before": match.group(0),
                      "after": new_code
                  })



        # 5. Infinite Loop (Synthetic)
        elif "infinite" in goal or "loop" in goal:
             intent = "Add break/term condition to infinite loop"
             import re
             # Match while(true) or while (true)
             match = re.search(r'(while\s*\(\s*true\s*\)\s*\{)', content, re.IGNORECASE)
             if match:
                  # Fix: Inject a break at start/end. 
                  # For safety/simplicity in regex replace: "while (true) { break; // Auto-fix"
                  operations.append({
                       "type": "replace",
                       "target": { "file_hash": file_hash, "start_line": 1, "end_line": 1 },
                       "before": match.group(0),
                       "after": match.group(0) + " break; // FAIL-SAFE FIX"
                  })

        # Enhancing SEC001/SEC002 for JavaScript (const/let/var)
        # Note: This runs if the previous Python blocks didn't catch it, 
        # but since those are strict regexes, we can check for JS patterns here or merge them.
        # For simplicity, let's add a JS Check block here.
        if not operations:
             import re
             # JS Password: const/let/var password = "..."
             if "hardcoded password" in goal or "sec001" in goal:
                  match = re.search(r'((const|let|var)\s+\w*password\w*\s*=\s*["\'].*["\'])', content, re.IGNORECASE)
                  if match:
                       operations.append({
                           "type": "replace",
                           "target": { "file_hash": file_hash, "start_line": 1, "end_line": 1 },
                           "before": match.group(1),
                           "after": '// Use env var in real app\n' + match.group(1).split('=')[0] + '= process.env.PASSWORD || "default";'
                       })
             
             # JS API Key: const/let/var apiKey = "..."
             elif "api key" in goal or "sec002" in goal:
                  match = re.search(r'((const|let|var)\s+\w*api\w*\s*=\s*["\'].*["\'])', content, re.IGNORECASE)
                  if match:
                       operations.append({
                           "type": "replace",
                           "target": { "file_hash": file_hash, "start_line": 1, "end_line": 1 },
                           "before": match.group(1),
                           "after": '// Use env var in real app\n' + match.group(1).split('=')[0] + '= process.env.API_KEY || "";'
                       })

        # 4. Fallback: Generic Safety (Pass)
        # If we can't find a pattern, we do a safe "touch" to prove we tried?
        # No, better to return None and fail safely than break code.
        
        if operations:
            return {
                "task_id": task_id,
                "intent": intent,
                "operations": operations,
                "constraints": { "allowed_files": [file_hash], "max_edits": 5, "no_other_changes": True },
                "verification_hints": ["Verify fix applied"]
            }
        
        return None

    def _construct_planning_prompt(self, context: Dict[str, Any]) -> str:
        """
        Constructs a strict prompt for Llama 3 to output a JSON plan COMPATIBLE with FixEngine schema.
        Matches daemon/core/brain/openai.py schema requirements.
        """
        task_id = context.get("task_id", "unknown")
        goal = context.get("goal", "")
        
        # Build context string with file hashes (Crucial for schema)
        context_str = ""
        for f in context.get("context", []):
            label = f.get("file_path_hint", "FILE")
            f_hash = f.get("file_hash", "unknown")
            # Include line info if available
            line_info = f.get("line_info", {})
            lines_str = f"Lines: {line_info.get('total_lines', '?')}"
            
            context_str += f"\nFILE HASH: {f_hash} ({label}) - {lines_str}\n"
            # USE FULL CONTENT IF AVAILABLE (Crucial for 4B model accuracy)
            content_to_use = f.get('content', f.get('content_summary', ''))
            context_str += f"{content_to_use}\n"
            context_str += "-" * 40 + "\n"

        return f"""
        You are an Expert Software Architect and Planner.
        Your goal is to create a precise VALIDATION-READY execution plan to fix a code issue.
        
        TASK ID: {task_id}
        GOAL: {goal}
        
        CONTEXT FILES (Use these File Hashes for 'target.file_hash'):
        {context_str}
        
        INSTRUCTIONS:
        1. Analyze the goal and the files.
        2. You MUST produce a plan that contains EXACT CODE REPLACEMENTS (diffs).
        3. OUTPUT ONLY VALID JSON.
        
        CRITICAL INDENTATION RULE:
        - The "after" code MUST PRESERVE the exact indentation (leading spaces) of the "before" code.
        - Do NOT strip leading whitespace from the "after" block.
        - If the code is inside a function or loop, KEEP the indentation.
        
        FEW-SHOT EXAMPLES (Follow this structure exactly):
        
        <example_1_security_fix>
        Goal: Fix hardcoded password
        JSON Output:
        {{
            "task_id": "example_1",
            "intent": "Remove hardcoded password and start using env var",
            "operations": [
                {{
                    "type": "replace",
                    "target": {{ "file_hash": "hash_123", "start_line": 10, "end_line": 10 }},
                    "before": "    password = 'secret'",
                    "after": "    password = os.getenv('PASSWORD')"
                }},
                {{
                    "type": "replace",
                    "target": {{ "file_hash": "hash_123", "start_line": 2, "end_line": 2 }},
                    "before": "import sys",
                    "after": "import sys\\nimport os"
                }}
            ],
            "constraints": {{ "allowed_files": ["hash_123"], "max_edits": 2, "no_other_changes": true }},
            "verification_hints": ["Verify password is not hardcoded"]
        }}
        </example_1_security_fix>
        
        <example_2_infinite_loop>
        Goal: Fix infinite loop
        JSON Output:
        {{
            "task_id": "example_2",
            "intent": "Add break condition to loop",
            "operations": [
                {{
                    "type": "replace",
                    "target": {{ "file_hash": "hash_456", "start_line": 20, "end_line": 22 }},
                    "before": "    while True:\\n        process_data()",
                    "after": "    while True:\\n        process_data()\\n        break"
                }}
            ],
            "constraints": {{ "allowed_files": ["hash_456"], "max_edits": 1, "no_other_changes": true }},
            "verification_hints": ["Verify loop terminates"]
        }}
        </example_2_infinite_loop>

        <example_3_lint_print>
        Goal: Fix LINT001 console print (Preserve Indentation!)
        JSON Output:
        {{
            "task_id": "example_3",
            "intent": "Replace print with logging",
            "operations": [
                {{
                    "type": "replace",
                    "target": {{ "file_hash": "hash_789", "start_line": 5, "end_line": 5 }},
                    "before": "        if True:\\n            print(f'User: {{user}}')",
                    "after": "        if True:\\n            logging.info(f'User: {{user}}')"
                }},
                 {{
                    "type": "replace",
                    "target": {{ "file_hash": "hash_789", "start_line": 1, "end_line": 1 }},
                    "before": "import os",
                    "after": "import os\\nimport logging"
                }}
            ],
            "constraints": {{ "allowed_files": ["hash_789"], "max_edits": 2, "no_other_changes": true }},
            "verification_hints": ["Verify logging is used"]
        }}
        </example_3_lint_print>
        
        <example_4_zero_division>
        Goal: Fix ZeroDivisionError
        JSON Output:
        {{
            "task_id": "example_4",
            "intent": "Check for zero before division",
            "operations": [
                {{
                    "type": "replace",
                    "target": {{ "file_hash": "hash_101", "start_line": 50, "end_line": 50 }},
                    "before": "    result = 100 / count",
                    "after": "    if count == 0:\\n        return 0\\n    result = 100 / count"
                }}
            ],
            "constraints": {{ "allowed_files": ["hash_101"], "max_edits": 1, "no_other_changes": true }},
            "verification_hints": ["Verify no division by zero"]
        }}
        </example_4_zero_division>
        
        <example_5_sql_injection>
        Goal: Fix SEC002 SQL Injection
        JSON Output:
        {{
            "task_id": "example_5",
            "intent": "Use parameterized query",
            "operations": [
                {{
                    "type": "replace",
                    "target": {{ "file_hash": "hash_999", "start_line": 45, "end_line": 45 }},
                    "before": "    cursor.execute(f'SELECT * FROM users WHERE name = {{name}}')",
                    "after": "    # Use parameterized query for safety\\n    cursor.execute('SELECT * FROM users WHERE name = ?', (name,))"
                }}
            ],
            "constraints": {{ "allowed_files": ["hash_999"], "max_edits": 1, "no_other_changes": true }},
            "verification_hints": ["Verify parameterized query"]
        }}
        </example_5_sql_injection>
        
        
        JSON SCHEMA (STRICT):
        {{
            "task_id": "{task_id}",
            "intent": "Brief description",
            "operations": [
                {{
                    "type": "replace",
                    "target": {{
                        "file_hash": "EXACT_HASH_FROM_CONTEXT_ABOVE",
                        "start_line": int_start_line,
                        "end_line": int_end_line
                    }},
                    "before": "Exact string content to satisfy strict string matching (ignoring whitespace)",
                    "after": "New string content to replace 'before'"
                }}
            ],
            "constraints": {{
                "allowed_files": [],
                "max_edits": 5,
                "no_other_changes": true
            }},
            "verification_hints": ["Check if X is fixed"]
        }}
        
        CRITICAL RULES:
        - "target.file_hash" MUST match one of the hashes provided in CONTEXT FILES.
        - "before" must match the code in the file roughly (FixEngine uses fuzzy matching, but try to be exact).
        - "type" should be "replace" for modifying code.
        - If removing lines leaves an empty block (e.g. empty 'if' or 'def'), YOU MUST INSERT 'pass' as the 'after' content.
          Example: "before": "    print(x)", "after": "    pass"
        - "after" content MUST preserve exact indentation of "before".
        - Output strict JSON only. No markdown.
        - Output strict JSON only. No markdown.
        """

    def _parse_plan(self, response_text: str) -> Optional[Dict[str, Any]]:
        """
        Robustly parses the JSON plan from Llama 3 response.
        """
        try:
            # 1. Strip whitespace
            clean_text = response_text.strip()
            
            # 2. Extract JSON from Markdown code blocks if present
            # 2. Extract JSON from Markdown code blocks if present
            import re
            markdown_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_text)
            if markdown_match:
                clean_text = markdown_match.group(1).strip()
            else:
                # Fallback: Extract from first { to last }
                json_match = re.search(r"(\{[\s\S]*\})", clean_text)
                if json_match:
                    clean_text = json_match.group(1).strip()
            
            # 3. Parse JSON
            plan = json.loads(clean_text)
            
            # 4. minimal validation
            if "intent" in plan and "operations" in plan:
                return plan
            else:
                logger.warning(f"LocalBrain generated incomplete plan: {plan.keys()}")
                return None
                
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LocalBrain plan JSON: {e}. Raw: {response_text[:200]}...")
            return None

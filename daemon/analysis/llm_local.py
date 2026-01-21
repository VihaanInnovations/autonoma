from typing import List, Dict, Any, AsyncGenerator, Optional
import httpx
import json
import asyncio
import logging

class LocalLLM:
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        self.logger = logging.getLogger("hybrid-reviewer")

    async def analyze_stream(self, content: str, context: str = None, model: str = "llama3") -> AsyncGenerator[Dict[str, Any], None]:
        prompt = self._get_prompt(content, context)
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            try:
                self.logger.info(f"LocalLLM: Sending request to {model}")
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": True, # Keep streaming to avoid timeouts on large files
                        "options": {
                            "temperature": 0.1, # Lower temp for more deterministic formatting
                            "num_ctx": 4096
                        }
                    }
                ) as response:
                    print(f"DEBUG: Ollama Status: {response.status_code}", flush=True)
                    if response.status_code != 200:
                        yield {"type": "error", "message": f"Ollama Error: {response.status_code}"}
                        return

                    full_response_buffer = ""
                    print("DEBUG: Starting stream processing...", flush=True)
                    
                    # Buffer for handling split lines or JSON arrays
                    async for chunk in response.aiter_lines():
                        if not chunk: continue
                        try:
                            # print(f"DEBUG: Chunk: {chunk[:50]}...", flush=True) # Uncomment if desperate
                            data = json.loads(chunk)
                            token = data.get("response", "")
                            full_response_buffer += token

                            
                            # Heuristic: If we see a newline, try to parse what we have so far
                            # This maintains the "streaming" feel for NDJSON
                            if "\n" in token and not full_response_buffer.strip().startswith("["):
                                lines = full_response_buffer.split("\n")
                                # Process all complete lines
                                for line in lines[:-1]:
                                    issue = self._parse_single_issue(line)
                                    if issue: yield issue
                                # Keep the last chunk
                                full_response_buffer = lines[-1]
                                
                        except Exception as e:
                            pass
                            
                    # End of stream processing
                    if full_response_buffer.strip():
                        response_str = full_response_buffer.strip()
                        print(f"DEBUG: LocalLLM Raw Output: {response_str[:500]}...", flush=True)

                        # Strategy 1: Robust Regex for JSON Array or Object
                        import re
                        
                        # Strip standard markdown code blocks
                        clean_str = response_str
                        code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response_str)
                        if code_block_match:
                            clean_str = code_block_match.group(1).strip()
                        
                        # Attempt to find the largest outer JSON structure (Array or Object)
                        # We look for the first '{' or '[' and the last '}' or ']'
                        try:
                            start_idx = -1
                            end_idx = -1
                            
                            # Find first [ or {
                            first_brace = clean_str.find('{')
                            first_bracket = clean_str.find('[')
                            
                            if first_brace != -1 and (first_bracket == -1 or first_brace < first_bracket):
                                start_idx = first_brace
                            elif first_bracket != -1:
                                start_idx = first_bracket
                                
                            # Find last ] or }
                            last_brace = clean_str.rfind('}')
                            last_bracket = clean_str.rfind(']')
                            
                            if last_brace != -1 and (last_bracket == -1 or last_brace > last_bracket):
                                end_idx = last_brace
                            elif last_bracket != -1:
                                end_idx = last_bracket
                                
                            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                                potential_json = clean_str[start_idx:end_idx+1]
                                
                                try:
                                    parsed = json.loads(potential_json)
                                    found_any = False
                                    
                                    if isinstance(parsed, list):
                                        for item in parsed:
                                            if self._validate_issue(item):
                                                yield item
                                                found_any = True
                                    elif isinstance(parsed, dict):
                                         if self._validate_issue(parsed):
                                             yield parsed
                                             found_any = True
                                             
                                    if found_any: return
                                except json.JSONDecodeError:
                                    print("DEBUG: JSON Decode Error on block extraction")
                        except Exception as e:
                            print(f"DEBUG: Parse Error: {e}")

                        # Strategy 2: Line-by-line fallback
                        lines = clean_str.split("\n")
                        for line in lines:
                             issues = self._parse_line_issues(line)
                             for issue in issues:
                                 yield issue

            except httpx.ConnectError:
                yield {"type": "error", "message": "Could not connect to Ollama (Local LLM). Is it running?"}
            except Exception as e:
                yield {"type": "error", "message": str(e)}

    def _get_prompt(self, content: str, context: str = None) -> str:
        ctx_prompt = ""
        if context:
            ctx_prompt = f"Context from similar files:\n{context}\n"
            
        return f"""
        {ctx_prompt}
        You are an expert Static Analysis Tool.
        Analyze the following Python code for ALL issues:
        1. Security Vulnerabilities (SQL Injection, Secrets, etc.) - CRITICAL PRIORITY
        2. Logic Errors (NoneType access, missing validation, infinite loops) - HIGH PRIORITY
        3. Performance Issues
        4. Linting/Style Issues (Unused imports, print statements)

        CRITICAL: Pay special attention to:
        - SQL Injection: f-strings or string formatting in SQL queries (e.g., f"SELECT * FROM users WHERE username='{{username}}'")
        - NoneType errors: Attribute access without null checks (e.g., user.email.upper() when user could be None)
        - Hardcoded secrets: API keys, passwords, tokens in code

        Code:
        ```python
        {content}
        ```

        Output Instructions:
        1. Return ONLY valid JSON.
        2. Do NOT output Markdown code blocks (no ```json).
        3. Output one JSON object per line (NDJSON) OR a single JSON array.
        4. REPORT EVERYTHING. Do not filter.
        5. SQL Injection and NoneType errors MUST be marked as severity "high" or "critical".

        Issue Examples:
        {{ "id": "SEC001", "line": 10, "message": "Hardcoded API key", "type": "security", "severity": "high" }}
        {{ "id": "SEC003", "line": 5, "message": "SQL Injection vulnerability: f-string with user input in SQL query", "type": "security", "severity": "high" }}
        {{ "id": "LOG002", "line": 18, "message": "Potential NoneType error: Accessing attribute without null check", "type": "logic", "severity": "high" }}
        {{ "id": "PERF001", "line": 20, "message": "Infinite loop detected", "type": "performance", "severity": "high" }}
        """

    def _parse_line_issues(self, line: str) -> List[Dict[str, Any]]:
        found_issues = []
        try:
            line = line.strip()
            # Clean trailing commas if present
            if line.endswith(","):
                line = line[:-1]
                
            if not line or line.startswith("```") or line == "[" or line == "]": return []
            
            # Skip conversational text (heuristic: doesn't start with { or [)
            if not (line.startswith("{") or line.startswith("[")):
                return []

            parsed = json.loads(line)
            
            # Case 1: Single Object
            if isinstance(parsed, dict):
                if self._validate_issue(parsed):
                    found_issues.append(parsed)
            # Case 2: List of Objects (Llama 3 quirk)
            elif isinstance(parsed, list):
                for item in parsed:
                    if self._validate_issue(item):
                        found_issues.append(item)
        except:
            pass
            
        return found_issues

    def _validate_issue(self, issue: Dict[str, Any]) -> bool:
        """Injects source and validates required fields"""
        if isinstance(issue, dict) and "message" in issue:
            issue["source"] = "llm_local_llama3"
            # Ensure ID exists
            if "id" not in issue:
                issue["id"] = "LOCAL_UNK"
            return True
        return False

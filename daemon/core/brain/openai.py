import json
import httpx
import logging
from typing import Dict, Any, List
from .base import RemoteBrain

logger = logging.getLogger(__name__)

class OpenAIBrain(RemoteBrain):
    """
    OpenAI implementation of RemoteBrain.
    Enforces strict JSON schema for planning.
    """
    
    SCHEMA = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "intent": {"type": "string"},
            "operations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["edit", "insert", "delete", "replace"]},
                        "target": {
                            "type": "object",
                            "properties": {
                                "file_hash": {"type": "string"},
                                "start_line": {"type": "integer"},
                                "end_line": {"type": "integer"}
                            },
                            "required": ["file_hash", "start_line", "end_line"]
                        },
                        "before": {"type": "string"},
                        "after": {"type": "string"}
                    },
                    "required": ["type", "target", "before", "after"]
                }
            },
            "constraints": {
                "type": "object",
                "properties": {
                    "allowed_files": {"type": "array", "items": {"type": "string"}},
                    "max_edits": {"type": "integer"},
                    "no_other_changes": {"type": "boolean"}
                },
                "required": ["allowed_files", "max_edits", "no_other_changes"]
            },
            "verification_hints": {
                "type": "array",
                "items": {"type": "string"}
            }
        },
        "required": ["task_id", "intent", "operations", "constraints", "verification_hints"]
    }

    def __init__(self, api_key: str, model: str = "gpt-3.5-turbo"):
        self.api_key = api_key
        self.model = model
        self.client = None  # Will be created lazily
        self._closed = False
    
    def _ensure_client(self):
        """Ensure httpx client is created and not closed."""
        import asyncio
        try:
            # Check if current event loop is closed or closing
            loop = asyncio.get_running_loop()
            if loop.is_closed():
                self._closed = True
                self.client = None
        except RuntimeError:
            # No event loop running - this is okay, client will work in new loop
            pass
        except Exception as e:
            # If we can't check the loop, mark as closed to be safe
            logger.debug(f"Error checking event loop in _ensure_client: {e}")
            self._closed = True
            self.client = None
        
        if self.client is None or self._closed:
            try:
                self.client = httpx.AsyncClient(timeout=60.0)
                self._closed = False
            except Exception as e:
                logger.error(f"Failed to create httpx client: {e}")
                self._closed = True
                self.client = None
                raise
    
    async def close(self):
        """Close the httpx client to prevent event loop errors."""
        if self.client and not self._closed:
            try:
                await self.client.aclose()
            except Exception:
                pass
            finally:
                self._closed = True
                self.client = None

    async def plan(self, task_summary: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a plan using OpenAI.
        """
        prompt = self._build_prompt(task_summary)
        
        self._ensure_client()
        try:
            response = await self.client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": "You are a precise coding planner. Return JSON ONLY. Strict schema enforcement."},
                        {"role": "user", "content": prompt}
                    ],
                    "response_format": { "type": "json_object" }
                }
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            
            plan = json.loads(content)
            self._validate_schema(plan)
            return plan
            
        except Exception as e:
            logger.error(f"OpenAI Planning failed: {e}")
            raise

    def _build_prompt(self, summary: Dict[str, Any]) -> str:
        # Construct the strict prompt with dependency context
        context_section = json.dumps(summary.get('context', []), indent=2)
        
        # Add dependency context if available
        dep_context = summary.get('dependency_context', {})
        dependency_section = ""
        
        if dep_context:
            # Format fixtures
            fixtures = dep_context.get('fixtures', [])
            fixture_defs = dep_context.get('fixture_definitions', {})
            
            if fixtures or fixture_defs:
                dependency_section += "\n\n<available_fixtures>\n"
                for fixture_file_hash in fixtures:
                    # Get actual fixture definitions if available
                    for file_path, fixtures_dict in fixture_defs.items():
                        if file_path in self._get_file_map_from_summary(summary):
                            for fixture_name, fixture_info in fixtures_dict.items():
                                dependency_section += f"  <fixture name=\"{fixture_name}\">\n"
                                dependency_section += f"    <signature>{fixture_info.get('signature', fixture_name)}</signature>\n"
                                if fixture_info.get('docstring'):
                                    doc = fixture_info['docstring'][:200].replace('\n', ' ')
                                    dependency_section += f"    <docstring>{doc}...</docstring>\n"
                                dependency_section += "  </fixture>\n"
                dependency_section += "</available_fixtures>\n"
            
            # Format utilities
            utilities = dep_context.get('utilities', [])
            util_sigs = dep_context.get('utility_signatures', {})
            
            if utilities or util_sigs:
                dependency_section += "\n\n<available_utilities>\n"
                for util_file_hash in utilities:
                    # Get utility signatures if available
                    for file_path, util_info in util_sigs.items():
                        if file_path in self._get_file_map_from_summary(summary):
                            dependency_section += f"  <utility_file hash=\"{util_file_hash}\">\n"
                            for func in util_info.get('functions', [])[:5]:  # Top 5 functions
                                dependency_section += f"    <function>{func.get('signature', func.get('name', ''))}</function>\n"
                            for cls in util_info.get('classes', [])[:3]:  # Top 3 classes
                                dependency_section += f"    <class>{cls.get('name', '')}</class>\n"
                            dependency_section += "  </utility_file>\n"
                dependency_section += "</available_utilities>\n"        
        goal = summary.get('goal', '')
        # Extract test name and issue from goal if available
        test_info = ""
        if "Failing Test:" in goal:
            parts = goal.split("Failing Test:")
            if len(parts) > 1:
                test_info = f"\nFAILING TEST: {parts[1].strip()}\n"
        
        # Build context with clear file type labels and line number information
        context_with_labels = []
        for ctx in summary.get('context', []):
            file_type = ctx.get('file_type', 'unknown')
            file_hint = ctx.get('file_path_hint', '')
            file_hash = ctx.get('file_hash', '')
            line_info = ctx.get('line_info', {})
            file_structure = ctx.get('file_structure', {})
            
            # Add clear label based on file type
            if file_type == 'source':
                label = f"[SOURCE FILE - MODIFY THIS FILE]"
            elif file_type == 'test':
                label = f"[TEST FILE - DO NOT MODIFY - This defines what should pass]"
            else:
                label = f"[{file_type.upper()} FILE]"
            
            # Build enhanced note with line information
            note_parts = [f"{label} File hash: {file_hash} ({file_hint})"]
            
            if line_info:
                total_lines = line_info.get('total_lines', 0)
                note_parts.append(f"Total lines: {total_lines} (use line numbers 1-{total_lines})")
            
            if file_structure:
                # Add functions with line ranges
                if file_structure.get('functions'):
                    funcs = file_structure['functions']
                    func_list = []
                    for func in funcs[:8]:  # Top 8 functions for better context
                        func_name = func.get('name', '')
                        func_line = func.get('line', 0)
                        func_end = func.get('end_line', func_line)
                        decorators = func.get('decorators', [])
                        if decorators:
                            func_list.append(f"{func_name} (lines {func_line}-{func_end}, decorators: {', '.join(decorators)})")
                        else:
                            func_list.append(f"{func_name} (lines {func_line}-{func_end})")
                    if func_list:
                        note_parts.append(f"Functions: {', '.join(func_list)}")
                
                # Add classes with line ranges
                if file_structure.get('classes'):
                    classes = file_structure['classes']
                    class_list = []
                    for cls in classes[:5]:  # Top 5 classes
                        cls_name = cls.get('name', '')
                        cls_line = cls.get('line', 0)
                        cls_end = cls.get('end_line', cls_line)
                        class_list.append(f"{cls_name} (lines {cls_line}-{cls_end})")
                    if class_list:
                        note_parts.append(f"Classes: {', '.join(class_list)}")
                
                # Add code blocks (if/for/while) for context
                if file_structure.get('code_blocks'):
                    blocks = file_structure['code_blocks']
                    block_list = []
                    for block in blocks[:5]:  # Top 5 blocks
                        block_type = block.get('type', '')
                        block_line = block.get('line', 0)
                        block_end = block.get('end_line', block_line)
                        block_list.append(f"{block_type} (lines {block_line}-{block_end})")
                    if block_list:
                        note_parts.append(f"Code blocks: {', '.join(block_list)}")
            
            enhanced_note = " | ".join(note_parts)
            
            context_with_labels.append({
                **ctx,
                "label": label,
                "note": enhanced_note
            })
        
        context_section_labeled = json.dumps(context_with_labels, indent=2)
        
        return f"""
PLAN REQUEST
TaskId: {summary.get('task_id')}
Goal: {goal}
{test_info}
CRITICAL: The fix MUST make the failing test pass. Analyze the test expectations carefully.

IMPORTANT FILE IDENTIFICATION:
- SOURCE FILE: This is the file that contains the bug and MUST be modified
- TEST FILE: This file defines the test expectations - DO NOT modify this file
- Only modify the SOURCE FILE to make the test pass

CONTEXT (Hashed Filenames):
{context_section_labeled}{dependency_section}

CRITICAL LINE NUMBER GUIDELINES:
- Each file has a "line_info" field showing total_lines and valid line range
- Each file has a "file_structure" field showing functions/classes with their line numbers
- ALWAYS use line numbers from the SOURCE FILE's line_info (not from test file or other files)
- Check the file_structure to find the correct line numbers for functions/classes
- Line numbers are 1-based (first line is 1, not 0)
- Ensure start_line and end_line are within the file's total_lines range
- If removing a statement leaves an empty block (e.g., empty "if", "def", "class", "try", "except"), YOU MUST INSERT "pass" to maintain valid syntax.
  Example: Changing "if x:\n  print(x)" to "if x:" is INVALID. Must be "if x:\n  pass".

INSTRUCTIONS:

2. Read the TEST FILE to understand what the test expects
3. Check the SOURCE FILE's line_info to see total_lines and valid line range
4. Check the SOURCE FILE's file_structure to find function/class line numbers
5. Identify the exact issue in the SOURCE FILE code using the correct line numbers
6. Plan precise edits to the SOURCE FILE (not the test file) that will make the test pass
7. For FastAPI endpoints:
   - Use status_code parameter in the decorator (e.g., @app.post("/users", status_code=201))
   - DO NOT use status_code in return statements (e.g., "return user, status_code=201" is INVALID syntax)
   - If you see invalid syntax like "return user, status_code=201", you MUST generate TWO operations:
     a) Remove "status_code=201" from the return statement (change "return user, status_code=201" to "return user")
     b) Add "status_code=201" to the decorator (change "@app.post("/users")" to "@app.post("/users", status_code=201)")
   - Use HTTPException with correct status codes (e.g., HTTPException(status_code=404, detail="..."))
   - For DELETE with no content, use @app.delete("/path", status_code=204) and return None or empty response
   - Example: To fix "return user, status_code=201" (invalid), generate TWO operations:
     Operation 1: Remove invalid syntax from return
     Operation 2: Add status_code=201 to decorator
8. Ensure all operations target the SOURCE FILE (file_type="source")
9. Ensure all operations use line numbers from the SOURCE FILE's line_info
10. Ensure all operations are precise and match the exact code structure

OUTPUT SCHEMA (STRICT):
{json.dumps(self.SCHEMA, indent=2)}

Return ONLY the JSON object.
"""
    
    def _get_file_map_from_summary(self, summary: Dict[str, Any]) -> Dict[str, str]:
        """Helper to extract file map from summary context."""
        # This is a simplified version - in practice, the summarizer would provide this
        # For now, return empty dict as file_map is managed by Summarizer
        return {}

    def _validate_schema(self, plan: Dict[str, Any]):
        # Simple validation (could use jsonschema lib if available, but doing manual for 0-dependency if needed)
        # Using strict manual checks for mandatory fields
        required = ["task_id", "intent", "operations"] # Relaxed: constraints/hints optional
        if not all(k in plan for k in required):
            raise ValueError(f"Missing required fields. Found: {list(plan.keys())}")
        
        for op in plan["operations"]:
            if not all(k in op for k in ["type", "target", "before", "after"]):
                raise ValueError("Invalid operation structure")

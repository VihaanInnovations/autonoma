import json
import httpx
import logging
from typing import Dict, Any
from .base import RemoteBrain
from .openai import OpenAIBrain

logger = logging.getLogger(__name__)

class ClaudeBrain(RemoteBrain):
    """
    Claude implementation of RemoteBrain (Fallback).
    Uses the Identical Schema as OpenAIBrain.
    """
    
    def __init__(self, api_key: str, model: str = "claude-3-sonnet-20240229"):
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
        Generate a plan using Claude.
        """
        # Reuse prompt builder from OpenAI for consistency
        # We can just instantiate a dummy OpenAIBrain or copy the method.
        # Copying for independence and to avoid weird dependencies.
        prompt = self._build_prompt(task_summary)
        
        self._ensure_client()
        try:
            response = await self.client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "max_tokens": 4096,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ]
                }
            )
            response.raise_for_status()
            data = response.json()
            content = data["content"][0]["text"]
            
            # extract JSON from markdown if present
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
                
            plan = json.loads(content)
            self._validate_schema(plan)
            return plan
            
        except Exception as e:
            logger.error(f"Claude Planning failed: {e}")
            raise

    def _build_prompt(self, summary: Dict[str, Any]) -> str:
        # Same exact prompt as OpenAI to ensure consistency
        context_section = json.dumps(summary.get('context', []), indent=2)
        
        # Add dependency context if available (same as OpenAI)
        dep_context = summary.get('dependency_context', {})
        dependency_section = ""
        
        if dep_context:
            # Format fixtures
            fixtures = dep_context.get('fixtures', [])
            fixture_defs = dep_context.get('fixture_definitions', {})
            
            if fixtures or fixture_defs:
                dependency_section += "\n\nAVAILABLE FIXTURES:\n"
                for fixture_file_hash in fixtures:
                    for file_path, fixtures_dict in fixture_defs.items():
                        dependency_section += f"File: {fixture_file_hash}\n"
                        for fixture_name, fixture_info in fixtures_dict.items():
                            dependency_section += f"  - {fixture_info.get('signature', fixture_name)}\n"
                            if fixture_info.get('docstring'):
                                dependency_section += f"    {fixture_info['docstring'][:100]}...\n"
            
            # Format utilities
            utilities = dep_context.get('utilities', [])
            util_sigs = dep_context.get('utility_signatures', {})
            
            if utilities or util_sigs:
                dependency_section += "\n\nAVAILABLE UTILITIES:\n"
                for util_file_hash in utilities:
                    for file_path, util_info in util_sigs.items():
                        dependency_section += f"File: {util_file_hash}\n"
                        for func in util_info.get('functions', [])[:5]:
                            dependency_section += f"  - {func.get('signature', func.get('name', ''))}\n"
                        for cls in util_info.get('classes', [])[:3]:
                            dependency_section += f"  - class {cls.get('name', '')}\n"
        
            goal = summary.get('goal', '')
            # Extract test name and issue from goal if available
            test_info = ""
            if "Failing Test:" in goal:
                parts = goal.split("Failing Test:")
                if len(parts) > 1:
                    test_info = f"\nFAILING TEST: {parts[1].strip()}\n"
            
        # Build context with clear file type labels and line number information (same as OpenAI)
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

INSTRUCTIONS:
1. Read the TEST FILE to understand what the test expects
2. Check the SOURCE FILE's line_info to see total_lines and valid line range
3. Check the SOURCE FILE's file_structure to find function/class line numbers
4. Identify the exact issue in the SOURCE FILE code using the correct line numbers
5. Plan precise edits to the SOURCE FILE (not the test file) that will make the test pass
6. For FastAPI endpoints:
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
7. Ensure all operations target the SOURCE FILE (file_type="source")
8. Ensure all operations use line numbers from the SOURCE FILE's line_info
9. Ensure all operations are precise and match the exact code structure

OUTPUT SCHEMA (STRICT):
{json.dumps(OpenAIBrain.SCHEMA, indent=2)}

Return ONLY the JSON object.
"""

    def _validate_schema(self, plan: Dict[str, Any]):
        # Reuse validation logic
        required = ["task_id", "intent", "operations", "constraints", "verification_hints"]
        if not all(k in plan for k in required):
            raise ValueError(f"Missing required fields. Found: {list(plan.keys())}")

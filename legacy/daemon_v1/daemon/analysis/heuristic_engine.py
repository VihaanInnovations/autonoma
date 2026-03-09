"""
Heuristic Analysis Engine for CodeSentinal.

This module provides deterministic analysis of error logs to guide the LLM.
It regex-matches common error patterns (like AssertionErrors, SyntaxErrors) 
and provides specific "HINTS" to offload reasoning from the small local model.
"""

import re
import logging

logger = logging.getLogger(__name__)

class HeuristicEngine:
    """Deterministic engine for error pattern matching."""
    
    def __init__(self):
        self.rules = [
            # Rule 1: Status Code Mismatch (e.g., Expected 201, got 200)
            {
                "pattern": r"assert (\d+) == (\d+).*where \1 = <Response \[(\d+) OK\]>",
                "type": "logic_error",
                "hint": "The test expects status code {1}, but the code returned {0}. Locate the route decorator (e.g., @app.post, @app.get) or the return statement and ensure it explicitly sets status_code={1}."
            },
            # Rule 1b: Simple status code assertion error
            {
                 "pattern": r"assert (\d+) == (\d+)",
                 "type": "logic_error",
                 "hint": "Assertion failed: Found {0}, but expected {1}. Check your logic to ensure the output matches {1}."
            },
            # Rule 2: Syntax Error
            {
                "pattern": r"SyntaxError: (.*)",
                "type": "syntax_error",
                "hint": "Syntax Error detected: {0}. Check for missing parentheses, colons, or indentation."
            },
            # Rule 3: Missing Key/Attribute
            {
                "pattern": r"KeyError: '(.*)'",
                "type": "runtime_error",
                "hint": "KeyError accessing '{0}'. Ensure the dictionary or object contains this key before accessing it, or use .get() with a default value."
            },
            # Rule 4: Attribute Error (General)
            {
                "pattern": r"AttributeError: '(\w+)' object has no attribute '(\w+)'",
                "type": "runtime_error",
                "hint": "The object '{0}' does not have the attribute '{1}'. Check if you have the correct object type or if there is a typo in the attribute name."
            },
            # Rule 5: Attribute Error (NoneType)
            {
                "pattern": r"AttributeError: 'NoneType' object has no attribute '(\w+)'",
                "type": "runtime_error",
                "hint": "You are trying to access '{0}' on a None object. This usually means a previous function returned None unexpectedly. Check where this variable is assigned."
            },
            # Rule 6: Type Error (Not Iterable)
            {
                "pattern": r"TypeError: '(\w+)' object is not iterable",
                "type": "runtime_error",
                "hint": "You are trying to loop over or unpack a '{0}' object, which is not allowed. Check if you missed wrapping it in a list() or if the variable contains what you expect."
            },
             # Rule 7: Import Error
            {
                "pattern": r"(ImportError|ModuleNotFoundError): No module named '(.*)'",
                "type": "import_error",
                "hint": "Missing Import: The module '{1}' is not found. Add `import {1}` or `from ... import {1}` at the top of the file."
            },
            # Rule 8: Index Error
            {
                "pattern": r"IndexError: list index out of range",
                "type": "runtime_error",
                "hint": "IndexError: You are trying to access a list element that does not exist. Check if the list is empty or if your index is too large."
            },
            # --- NEW RULES: Static Analysis Bridges (Simulating LoRA) ---
            # Rule 9: SEC001 (Hardcoded Password)
            {
                "pattern": r"SEC001",
                "type": "security_fix",
                "hint": "SECURITY FIX: Hardcoded password detected. 1. Import os. 2. Replace string literal with os.getenv('PASSWORD_VAR'). 3. Do not leave empty lines."
            },
            # Rule 10: LINT001 (Print Statement)
            {
                "pattern": r"LINT001",
                "type": "lint_fix",
                "hint": "LINT FIX: Console print detected. 1. Import logging if missing. 2. Replace print(...) with logging.info(...). 3. Ensure syntax is valid."
            },
            # Rule 11: PERF001 (Infinite Loop)
            {
                "pattern": r"PERF001",
                "type": "perf_fix",
                "hint": "PERFORMANCE FIX: Infinite loop detected. You MUST add a `break` statement inside the loop or a termination condition."
            },
            # Rule 12: File Not Found
            {
                "pattern": r"FileNotFoundError: \[Errno 2\] No such file or directory: '(.*)'",
                "type": "runtime_error",
                "hint": "FileNotFound: The file '{0}' was not found. 1. Check if the path is correct/absolute. 2. Verify the file exists before opening."
            },
            # Rule 13: Name Error (Undefined Variable)
            {
                "pattern": r"NameError: name '(\w+)' is not defined",
                "type": "runtime_error",
                "hint": "NameError: The variable '{0}' is used but not defined. 1. Check for typos. 2. Ensure it is imported or initialized before use."
            },
            # Rule 14: Indentation Error
            {
                "pattern": r"IndentationError: (.*)",
                "type": "syntax_error",
                "hint": "IndentationError: {0}. Python relies on strict indentation. Ensure all blocks within functions/loops are indented consistently (4 spaces)."
            },
            # Rule 15: Value Error (Unpacking)
            {
                "pattern": r"ValueError: not enough values to unpack \(expected (\d+), got (\d+)\)",
                "type": "runtime_error",
                "hint": "ValueError: Unpacking mismatch. You tried to unpack {1} values into {0} variables. Check the function return value."
            },
            # Rule 16: Type Error (Argument Mismatch)
            {
                 "pattern": r"TypeError: \w+\(\) takes (\d+) positional arguments but (\d+) were given",
                 "type": "runtime_error",
                 "hint": "TypeError: Argument count mismatch. Function expects {0} arguments but received {1}. Check the function signature."
            },
            {
                "pattern": r"json.decoder.JSONDecodeError: (.*)",
                "type": "runtime_error",
                "hint": "JSON Error: Failed to parse JSON. Result might be empty or malformed. Check if the response.text is valid JSON before calling .json()."
            },
            # Rule 18: Zero Division Error
            {
                "pattern": r"ZeroDivisionError: division by zero",
                "type": "runtime_error",
                "hint": "ZeroDivisionError: You are trying to divide by zero. Ensure the denominator is not zero before division."
            },
            # Rule 19: Unbound Local Error
            {
                "pattern": r"UnboundLocalError: local variable '(\w+)' referenced before assignment",
                "type": "runtime_error",
                "hint": "UnboundLocalError: Variable '{0}' is referenced before assignment. Ensure it is initialized in all code paths before use."
            },
            # Rule 20: Recursion Error
            {
                "pattern": r"RecursionError: maximum recursion depth exceeded",
                "type": "runtime_error",
                "hint": "RecursionError: Infinite recursion detected. Check your base case and ensure recursive calls move towards it."
            },
             # Rule 21: Value Error (Invalid Literal)
            {
                "pattern": r"ValueError: invalid literal for int\(\) with base 10: '(.*)'",
                "type": "runtime_error",
                "hint": "ValueError: Impossible to convert string '{0}' to integer. Ensure the string contains only digits."
            },
            # Rule 22: SEC002 (SQL Injection)
            {
                "pattern": r"SEC002",
                "type": "security_fix",
                "hint": "SECURITY FIX: Potential SQL Injection detected. 1. Use parameterized queries (e.g., `cursor.execute('SELECT * FROM users WHERE name = ?', (name,))`). 2. NEVER strictly concatenate strings into SQL queries."
            },
            # Rule 23: Timeout Error
            {
                 "pattern": r"TimeoutError",
                 "type": "runtime_error",
                 "hint": "TimeoutError: Operation timed out. 1. Increase the timeout limit. 2. Optimize the query/request. 3. Ensure the external service is reachable."
            },
            # Rule 24: Permission Error
            {
                 "pattern": r"PermissionError: \[Errno 13\] Permission denied: '(.*)'",
                 "type": "runtime_error",
                 "hint": "PermissionError: Access denied to '{0}'. 1. Check file permissions. 2. Ensure the process has the necessary rights (e.g., Run as Admin/root). 3. Check if file is open in another program."
            },
            # Rule 25: Connection Refused Error
            {
                 "pattern": r"ConnectionRefusedError: \[Errno 111\] Connection refused",
                 "type": "runtime_error",
                 "hint": "ConnectionRefused: Target machine refused the connection. 1. Ensure the server is running. 2. Check the port number. 3. specific firewall rules."
            }
        ]
        
    def analyze_error(self, error_log: str) -> str:
        """
        Analyze error log and return a hint if a pattern matches.
        """
        if not error_log:
            return ""
            
        hints = []
        
        # Check all rules
        for rule in self.rules:
            matches = re.findall(rule["pattern"], error_log, re.MULTILINE | re.DOTALL)
            for match in matches:
                # Format hint with captured groups
                if isinstance(match, tuple):
                    hint_msg = rule["hint"].format(*match)
                else:
                    hint_msg = rule["hint"].format(match)
                
                hints.append(f"BENCHMARK HINT: {hint_msg}")
                logger.info(f"Heuristic Match: {rule['type']} -> {hint_msg}")
        
        if hints:
            # return unique hints joined
            return "\n".join(list(set(hints)))
            
        return ""

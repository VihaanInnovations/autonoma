"""
Autonoma Community Edition - High-Confidence Security Detectors
Strictly high-confidence detection for SEC003 (SQLi), SEC004 (XSS/SSTI), and SEC005 (Deserialization).
"""
import re
from typing import List, Dict, Any

class SecurityDetectors:
    """
    High-confidence security issue detection.
    Community Edition: Returns issues that are explicitly REFUSED for auto-fix.
    """

    @staticmethod
    def analyze_file(content: str, file_path: str) -> List[Dict[str, Any]]:
        """
        Run all high-confidence security checks.
        """
        issues = []
        if not content:
            return issues

        # 1. SQL Injection (SEC003)
        issues.extend(SecurityDetectors._detect_sqli(content, file_path))

        # 2. XSS/SSTI (SEC004)
        issues.extend(SecurityDetectors._detect_ssti(content, file_path))

        # 3. Insecure Deserialization (SEC005)
        issues.extend(SecurityDetectors._detect_deserialization(content, file_path))

        return issues

    @staticmethod
    def _detect_sqli(content: str, file_path: str) -> List[Dict[str, Any]]:
        """
        SEC003: SQL Injection (High Confidence Only)
        Triggers on .execute() with string concatenation/formatting containing variables.
        """
        issues = []
        lines = content.split('\n')
        
        # Regex for .execute() calls
        # Matches: cursor.execute(
        execute_pattern = re.compile(r'\.execute\s*\(')
        
        # Regex for SQL keywords (simple heuristic)
        # Must be present in the line to be considered SQL
        sql_keywords = re.compile(r'(SELECT|INSERT|UPDATE|DELETE|FROM|WHERE)', re.IGNORECASE)
        
        # Regex for dangerous patterns (concat, f-string, format, %)
        # 1. Concatenation: "..." + var
        # 2. F-string: f"...{var}..."
        # 3. Percent: "..." % var
        # 4. Format: "...".format(var)
        
        # We'll check lines that match .execute()
        for i, line in enumerate(lines):
            if execute_pattern.search(line):
                # check for SQL context
                if not sql_keywords.search(line):
                    continue
                
                # Check for danger signals
                is_dangerous = False
                bug_type = ""

                # Danger 1: Plus concatenation
                if '+' in line and ('"' in line or "'" in line):
                    is_dangerous = True
                    bug_type = "Concatenation"
                    
                # Danger 2: F-string
                elif 'f"' in line or "f'" in line:
                    if '{' in line and '}' in line:
                        is_dangerous = True
                        bug_type = "F-String"
                        
                # Danger 3: % formatting (excluding simple %s placeholders alone)
                # pattern: string % var
                elif '%' in line and not re.search(r",\s*\(?.*%s", line): 
                    # This is tricky strictly with regex, but let's look for "..." % 
                    # if % is used as operator, not just in string
                    # Heuristic: if line has % and it's not a param style like .execute("...%s...", (tuple))
                    # If % is outside the quotes... hard to robustly regex
                    # Let's stick to the prompt's high confidence examples
                    if re.search(r'["\'].*?\s*%\s*[a-zA-Z_]', line):
                         is_dangerous = True
                         bug_type = "% Formatting"

                # Danger 4: .format()
                elif '.format(' in line:
                    is_dangerous = True
                    bug_type = ".format()"

                if is_dangerous:
                    issues.append({
                        "id": "SEC003",
                        "line": i + 1,
                        "title": "Possible SQL Injection",
                        "message": f"Potential SQL injection detected via {bug_type} in SQL query construction.",
                        "severity": "HIGH",
                        "confidence": "HIGH",
                        "can_autofix": False,
                        "evidence": line.strip()
                    })

        return issues

    @staticmethod
    def _detect_ssti(content: str, file_path: str) -> List[Dict[str, Any]]:
        """
        SEC004: XSS / SSTI (High Confidence Only)
        Focuses on Flask render_template_string and Jinja2 Template().render() with non-literals.
        """
        issues = []
        lines = content.split('\n')
        
        for i, line in enumerate(lines):
            # Pattern 1: flask.render_template_string(...)
            if 'render_template_string(' in line:
                # Check if argument is a variable (not a string literal)
                # Heuristic: if parens don't immediately contain quotes
                args = line.split('render_template_string(')[1]
                if not args.strip().startswith(('"', "'")):
                    issues.append({
                        "id": "SEC004",
                        "line": i + 1,
                        "title": "Server-Side Template Injection (SSTI)",
                        "message": "Unsafe usage of 'render_template_string' with non-literal template. User input may be executed.",
                        "severity": "HIGH",
                        "confidence": "HIGH",
                        "can_autofix": False,
                        "evidence": line.strip()
                    })
                    continue

            # Pattern 2: jinja2.Template(...).render(...)
            # or just Template(...).render(...)
            # strict check for 'Template(' and ').render' on same line for now implies specific usage
            if 'Template(' in line and ').render(' in line:
                 # Check Template arg
                 t_args = line.split('Template(')[1]
                 if not t_args.strip().startswith(('"', "'")):
                     issues.append({
                        "id": "SEC004",
                        "line": i + 1,
                        "title": "Server-Side Template Injection (SSTI)",
                        "message": "Unsafe 'Template(...).render()' pattern detected with non-literal template.",
                        "severity": "HIGH",
                        "confidence": "HIGH",
                        "can_autofix": False,
                        "evidence": line.strip()
                    })
        
        return issues

    @staticmethod
    def _detect_deserialization(content: str, file_path: str) -> List[Dict[str, Any]]:
        """
        SEC005: Insecure Deserialization (High Confidence Only)
        Detects pickle.loads/load and unsafe yaml.load.
        """
        issues = []
        lines = content.split('\n')
        
        for i, line in enumerate(lines):
            # Pattern 1: pickle.loads() or pickle.load()
            if 'pickle.loads(' in line or 'pickle.load(' in line:
                issues.append({
                    "id": "SEC005",
                    "line": i + 1,
                    "title": "Insecure Deserialization (Pickle)",
                    "message": "Unsafe usage of 'pickle' detected. Pickle data can execute arbitrary code.",
                    "severity": "HIGH",
                    "confidence": "HIGH",
                    "can_autofix": False,
                    "evidence": line.strip()
                })
                continue
            
            # Pattern 2: yaml.load() without SafeLoader
            if 'yaml.load(' in line:
                # Exclude if 'SafeLoader' is present in the same line
                if 'SafeLoader' not in line:
                    issues.append({
                        "id": "SEC005",
                        "line": i + 1,
                        "title": "Insecure Deserialization (YAML)",
                        "message": "Unsafe usage of 'yaml.load' detected without SafeLoader.",
                        "severity": "HIGH",
                        "confidence": "HIGH",
                        "can_autofix": False,
                        "evidence": line.strip()
                    })

        return issues

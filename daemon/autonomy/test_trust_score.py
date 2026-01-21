import ast
import logging

logger = logging.getLogger("TestTrustScore")

class TestTrustScore:
    """
    Calculates Test Trust Score (TTS) to gate autonomy.
    Range: [0.0, 1.0]
    Threshold: 0.6 (Below this = UNVERIFIED_PASS)
    """
    
    def calculate(self, test_content: str) -> float:
        try:
            if not test_content or not test_content.strip():
                return 0.0
                
            tree = ast.parse(test_content)
            
            assertions = 0
            status_code_checks = 0
            mutations = 0 # Updates, Deletes, Creates
            test_funcs = 0
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                    test_funcs += 1
                    
                if isinstance(node, ast.Assert):
                    assertions += 1
                    # Check for status_code
                    if "status_code" in ast.dump(node):
                        status_code_checks += 1
                        
                # Check for mutation verbs in calls
                if isinstance(node, ast.Call) and hasattr(node.func, "attr"):
                    attr = node.func.attr
                    if any(v in attr for v in ["post", "put", "delete", "update", "create"]):
                        mutations += 1

            if test_funcs == 0:
                return 0.0

            # Penalties
            score = 1.0
            
            # 1. Assertion Density
            if assertions == 0:
                return 0.0 # Useless test
            if assertions < 2:
                score -= 0.3
                
            # 2. Shallow Status Checks
            if status_code_checks == assertions:
                score -= 0.6 # Only checked status code
            elif status_code_checks > 0.5 * assertions:
                score -= 0.3
                
            # 3. No Mutation (ReadOnly tests are less risky but less rigorous for autonomy)
            if mutations == 0 and "get" in test_content.lower():
                score -= 0.1 # Mild penalty
            elif mutations == 0: 
                score -= 0.2
                
            # 4. Single Happy Path
            if test_funcs == 1:
                score = min(score, 0.5) # Cap at 0.5 if only one test function
                
            return max(0.0, score)
            
        except Exception as e:
            logger.error(f"TTS Calc Failed: {e}")
            return 0.0

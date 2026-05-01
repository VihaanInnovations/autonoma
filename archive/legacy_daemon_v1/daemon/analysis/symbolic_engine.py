from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from .ast_engine import ASTEngine
from tree_sitter import Query, QueryCursor
import sys

@dataclass
class Interval:
    min_val: float
    max_val: float

    def is_empty(self):
        return self.min_val > self.max_val

    def contains(self, val: float):
        return self.min_val <= val <= self.max_val
    
    def __repr__(self):
        return f"[{self.min_val}, {self.max_val}]"

    @staticmethod
    def universal():
        return Interval(float("-inf"), float("inf"))

@dataclass
class SymbolicValue:
    interval: Interval
    tainted: bool = False
    source: Optional[str] = None

    @staticmethod
    def clean(interval: Interval = None):
        return SymbolicValue(interval if interval else Interval.universal(), False)

    @staticmethod
    def tainted_val(source: str):
        return SymbolicValue(Interval.universal(), True, source)

class SymbolicEngine:
    def __init__(self):
        self.ast_engine = ASTEngine()
        self.sources = {"input", "request.args.get", "request.form.get", "msg.payload"}
        self.sinks = {"eval", "exec", "os.system", "subprocess.call", "sqlite3.execute"}
        
    def analyze(self, content: str) -> List[Dict[str, Any]]:
        if not self.ast_engine.parser:
            return []
            
        tree = self.ast_engine.parser.parse(bytes(content, "utf8"))
        issues = []
        
        func_query = Query(self.ast_engine.PY_LANGUAGE, """
        (function_definition) @func
        """)
        
        cursor = QueryCursor(func_query)
        captures = cursor.captures(tree.root_node)
        
        nodes = []
        if isinstance(captures, dict):
            nodes = captures.get('func', [])
        elif isinstance(captures, list):
            nodes = [n for n, name in captures if name == 'func']
            
        for func_node in nodes:
            func_issues = self._analyze_function(func_node)
            issues.extend(func_issues)
            
        return issues

    def _analyze_function(self, func_node) -> List[Dict[str, Any]]:
        issues = []
        state = {} # var_name -> SymbolicValue
        
        body = func_node.child_by_field_name('body')
        if not body: return []
        
        self._analyze_block(body, state, issues)
        return issues

    def _analyze_block(self, block_node, state: Dict[str, SymbolicValue], issues: List[Dict[str, Any]]):
        for child in block_node.children:
            if child.type == 'expression_statement':
                self._analyze_stmt(child, state, issues)
            elif child.type == 'if_statement':
                self._analyze_if(child, state, issues)
            
    def _analyze_stmt(self, stmt_node, state, issues):
        # Expression statement usually wraps an expression.
        # Check for assignment
        child = stmt_node.child(0)
        
        # 1. Assignment `x = ...`
        if child.type == 'assignment':
            self._handle_assignment(child, state, issues)
            return

        # 2. Call `eval(...)` (void context)
        if child.type == 'call':
            self._check_sink(child, state, issues)

    def _handle_assignment(self, assign_node, state, issues):
        left = assign_node.child_by_field_name('left')
        right = assign_node.child_by_field_name('right')
        
        if left.type == 'identifier':
            var_name = left.text.decode('utf8')
            sym_val = self._eval_expr(right, state)
            state[var_name] = sym_val
            
            # Check if we assigned a sink result? (Unlikely, usually sinks return void/status)
            # But if right is a call, we handled it inside eval_expr? 
            # Actually _eval_expr is pure evaluation.
            # But if right is a CALL, we need to check if that call ITSELF is a sink? 
            # e.g. x = os.system("...") -> still a sink!
            if right.type == 'call':
                self._check_sink(right, state, issues)

    def _check_sink(self, call_node, state, issues):
        func_node = call_node.child_by_field_name('function')
        if not func_node: return
        
        func_name = func_node.text.decode('utf8')
        
        # Helper for attribute calls like os.system
        if func_node.type == 'attribute':
            # split object.method
            func_name = func_node.text.decode('utf8') # e.g. "os.system"
        
        if func_name in self.sinks:
            args = call_node.child_by_field_name('arguments')
            if not args: return
            
            # Check arguments for taint
            for arg in args.children:
                if arg.type == 'identifier':
                    arg_name = arg.text.decode('utf8')
                    val = state.get(arg_name)
                    if val and val.tainted:
                        issues.append({
                            "id": "SYM002",
                            "line": call_node.start_point.row + 1,
                            "message": f"Taint Detected: Unsafe data from '{val.source}' passed to sink '{func_name}'",
                            "type": "security",
                            "severity": "critical",
                            "source": "symbolic_engine"
                        })
                # Check direct string concatenation with tainted vars?
                # e.g. "echo " + x
                elif arg.type == 'binary_operator':
                     self._check_binary_op_taint(arg, state, issues, func_name, call_node)

    def _check_binary_op_taint(self, bin_node, state, issues, sink_name, call_node):
        # Recursively check if binary op involves tainted var
        val = self._eval_expr(bin_node, state)
        if val.tainted:
             issues.append({
                "id": "SYM002",
                "line": call_node.start_point.row + 1,
                "message": f"Taint Detected: Unsafe data from '{val.source}' passed to sink '{sink_name}' (via expression)",
                "type": "security",
                "severity": "critical",
                "source": "symbolic_engine"
            })

    def _analyze_if(self, if_node, state, issues):
        condition = if_node.child_by_field_name('condition')
        consequence = if_node.child_by_field_name('consequence')
        alternative = if_node.child_by_field_name('alternative')
        
        true_state, false_state = self._split_state(condition, state)
        
        if self._is_state_impossible(true_state):
             issues.append({
                "id": "SYM001",
                "line": consequence.start_point.row + 1,
                "message": "Dead Code Detected (Unreachable Branch)",
                "type": "logic",
                "severity": "medium",
                "source": "symbolic_engine"
            })
        else:
            self._analyze_block(consequence, true_state.copy(), issues)
            
        if alternative:
            else_body = alternative.child_by_field_name('body')
            if self._is_state_impossible(false_state):
                issues.append({
                    "id": "SYM001",
                    "line": alternative.start_point.row + 1,
                    "message": "Dead Code Detected (Unreachable Else)",
                    "type": "logic",
                    "severity": "medium",
                    "source": "symbolic_engine"
                })
            elif else_body:
                 self._analyze_block(else_body, false_state.copy(), issues)

    def _eval_expr(self, node, state) -> SymbolicValue:
        if node.type == 'integer':
            val = float(node.text) 
            return SymbolicValue(Interval(val, val))
        elif node.type == 'float' or node.type == 'float_literal':
            val = float(node.text)
            return SymbolicValue(Interval(val, val))
        elif node.type == 'identifier':
            name = node.text.decode('utf8')
            return state.get(name, SymbolicValue.clean())
        elif node.type == 'call':
            # Check if source
            func_node = node.child_by_field_name('function')
            if func_node:
                func_name = func_node.text.decode('utf8')
                if func_name in self.sources:
                    return SymbolicValue.tainted_val(func_name)
        elif node.type == 'binary_operator':
            # Propagate Taint
            left = self._eval_expr(node.child(0), state)
            right = self._eval_expr(node.child(2), state)
            if left.tainted or right.tainted:
                src = left.source if left.tainted else right.source
                return SymbolicValue.tainted_val(src)
                
        return SymbolicValue.clean()

    def _split_state(self, condition, state):
        true_state = state.copy()
        false_state = state.copy()
        
        if condition.type == 'comparison_operator':
            left = condition.child(0)
            op = condition.child(1).type
            right = condition.child(2)
            
            if left.type == 'identifier' and (right.type == 'integer' or right.type == 'float' or right.type == 'float_literal'):
                var = left.text.decode('utf8')
                val = float(right.text)
                
                msg_step = 1.0 if right.type == 'integer' else 1e-9
                current_sym = state.get(var, SymbolicValue.clean())
                current_interval = current_sym.interval

                if op == '>':
                    true_int = self._intersect(current_interval, Interval(val + msg_step, float('inf')))
                    false_int = self._intersect(current_interval, Interval(float('-inf'), val))
                elif op == '<':
                    true_int = self._intersect(current_interval, Interval(float('-inf'), val - msg_step))
                    false_int = self._intersect(current_interval, Interval(val, float('inf')))
                elif op == '>=':
                    true_int = self._intersect(current_interval, Interval(val, float('inf')))
                    false_int = self._intersect(current_interval, Interval(float('-inf'), val - msg_step))
                elif op == '<=':
                    true_int = self._intersect(current_interval, Interval(float('-inf'), val))
                    false_int = self._intersect(current_interval, Interval(val + msg_step, float('inf')))
                elif op == '==':
                    true_int = self._intersect(current_interval, Interval(val, val))
                    if current_interval.min_val == val and current_interval.max_val == val:
                         false_int = Interval(1.0, 0.0) # Empty
                    else:
                         false_int = current_interval 
                elif op == '!=':
                    if current_interval.min_val == val and current_interval.max_val == val:
                        true_int = Interval(1.0, 0.0) # Empty
                    else:
                        true_int = current_interval
                    false_int = self._intersect(current_interval, Interval(val, val))
                else:
                    return true_state, false_state
                
                # Update intervals in states, preserving taint?
                # For splitting logic, we assume checking 'x > 5' doesn't cleanse taint.
                true_state[var] = SymbolicValue(true_int, current_sym.tainted, current_sym.source)
                false_state[var] = SymbolicValue(false_int, current_sym.tainted, current_sym.source)
            
            elif left.type == 'integer' and right.type == 'integer':
                lval = float(left.text)
                rval = float(right.text)
                result = False
                if op == '>': result = lval > rval
                elif op == '<': result = lval < rval
                elif op == '>=': result = lval >= rval
                elif op == '<=': result = lval <= rval
                elif op == '==': result = lval == rval
                elif op == '!=': result = lval != rval
                
                if result:
                    # Condition is True. False path is impossible.
                    false_state["__path__"] = SymbolicValue(Interval(1.0, 0.0))
                else:
                    # Condition is False. True path is impossible.
                    true_state["__path__"] = SymbolicValue(Interval(1.0, 0.0))
                    
        return true_state, false_state

    def _intersect(self, i1: Interval, i2: Interval) -> Interval:
        return Interval(max(i1.min_val, i2.min_val), min(i1.max_val, i2.max_val))

    def _is_state_impossible(self, state: Dict[str, SymbolicValue]) -> bool:
        for sym_val in state.values():
            if sym_val.interval.is_empty():
                return True
        return False

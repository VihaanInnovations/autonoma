from typing import List, Dict, Any

def merge_issues(existing: List[Dict[str, Any]], new_issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge new issues into existing list, avoiding duplicates.
    Deduplication key: line number + simplified message + type.
    """
    merged = list(existing)
    existing_keys = set()
    
    for issue in existing:
        key = make_issue_key(issue)
        existing_keys.add(key)
        
    for issue in new_issues:
        key = make_issue_key(issue)
        if key not in existing_keys:
            merged.append(issue)
            existing_keys.add(key)
            
    return merged

def make_issue_key(issue: Dict[str, Any]) -> str:
    # Create a unique signature for the issue
    line = issue.get("line", 0)
    type_ = issue.get("type", "unknown")
    # Simplify message to avoid minor LLM wording diffs (first 30 chars?)
    msg = issue.get("message", "").strip().lower()[:30]
    return f"{line}:{type_}:{msg}"

from typing import List, Dict, Any


def merge_issues(existing: List[Dict[str, Any]], new_issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge new issues into existing list, avoiding duplicates."""
    merged = list(existing)
    existing_keys = {make_issue_key(i) for i in existing}

    for issue in new_issues:
        key = make_issue_key(issue)
        if key not in existing_keys:
            merged.append(issue)
            existing_keys.add(key)

    return merged


def make_issue_key(issue: Dict[str, Any]) -> str:
    """
    Span-based dedup key.

    Uses (line, col_offset, rule_id) so two detectors that flag the
    exact same token on the same line with the same rule are deduped,
    but different rules or different columns are preserved.

    If col_offset is absent (legacy data), falls back to line:rule_id
    which is still better than message-based dedup.
    """
    line = issue.get("line", 0)
    col = issue.get("col_offset", -1)
    rule_id = issue.get("id", "unknown")
    return f"{line}:{col}:{rule_id}"

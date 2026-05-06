#!/usr/bin/env python3
"""
DEPRECATED: use bench/suggest_labels.py instead.

auto_classify.py wrote directly to findings_classified.csv and treated
heuristic labels as ground truth. That approach is scientifically unsound.

suggest_labels.py writes findings_suggested.csv with structured suggestions
(suggested_label, suggestion_confidence, suggestion_reason) and empty
human_label/review_notes/reviewer columns for human review.
"""
import sys

print(
    "ERROR: auto_classify.py is deprecated.\n"
    "Use: python bench/suggest_labels.py\n"
    "\nWorkflow:\n"
    "  python bench/measure_precision.py\n"
    "  python bench/suggest_labels.py\n"
    "  # fill human_label in findings_suggested.csv\n"
    "  python bench/compute_precision.py bench/findings_suggested.csv",
    file=sys.stderr,
)
sys.exit(1)

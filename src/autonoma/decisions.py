"""Outcomes for autonomous actions."""
from enum import Enum
from dataclasses import dataclass
from typing import Optional
import os


class DecisionOutcome(Enum):
    """Potential outcomes for any action."""
    SUCCESS = "SUCCESS"      # Action completed correctly
    REFUSED = "REFUSED"      # Action declined due to safety/scope
    FAILED = "FAILED"        # Action attempted but errored


class RefusalReason(Enum):
    """Explicit reasons for refusal."""
    # Environment variable contract issues
    ENV_VAR_CONTRACT_NOT_FOUND = "env_var_contract_not_found"
    ENV_VAR_NAME_AMBIGUOUS = "env_var_name_ambiguous"

    # Secret detection issues
    SECRET_PATTERN_AMBIGUOUS = "secret_pattern_ambiguous"
    SECRET_IN_COMMENT = "secret_in_comment"
    SECRET_ALREADY_SAFE = "secret_already_safe"

    # File/language issues
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    FILE_TOO_LARGE = "file_too_large"
    FILE_BINARY = "file_binary"
    FILE_EMPTY = "file_empty"

    # Fix application issues
    FIX_WOULD_BREAK_SYNTAX = "fix_would_break_syntax"
    FIX_NOT_LOCALIZED = "fix_not_localized"
    FIX_VALIDATION_FAILED = "fix_validation_failed"

    # AST-specific stable refusal codes
    REFUSE_NON_CONSTANT_VALUE = "refuse_non_constant_value"
    REFUSE_FSTRING_MIXED_EXPRESSION = "refuse_fstring_mixed_expression"
    REFUSE_STRING_CONCATENATION = "refuse_string_concatenation"
    REFUSE_UNSAFE_REWRITE_BOUNDARY = "refuse_unsafe_rewrite_boundary"
    REFUSE_IMPORT_COLLISION = "refuse_import_collision"
    REFUSE_UNSUPPORTED_NODE_TYPE = "refuse_unsupported_node_type"

    # Scope issues
    ISSUE_TYPE_NOT_SUPPORTED = "issue_type_not_supported"
    REQUIRES_ENTERPRISE = "requires_enterprise"


class FailureReason(Enum):
    """Failure reasons (errors)."""
    PARSE_ERROR = "parse_error"
    IO_ERROR = "io_error"
    TIMEOUT = "timeout"
    UNEXPECTED_ERROR = "unexpected_error"


@dataclass
class AnalysisResult:
    """Result of analyzing a file for secrets."""
    outcome: DecisionOutcome
    issues: list
    refusal_reason: Optional[RefusalReason] = None
    failure_reason: Optional[FailureReason] = None
    message: Optional[str] = None

    @classmethod
    def success(cls, issues: list):
        return cls(outcome=DecisionOutcome.SUCCESS, issues=issues)

    @classmethod
    def refused(cls, reason: RefusalReason, message: str = None):
        return cls(
            outcome=DecisionOutcome.REFUSED,
            issues=[],
            refusal_reason=reason,
            message=message
        )

    @classmethod
    def failed(cls, reason: FailureReason, message: str = None):
        return cls(
            outcome=DecisionOutcome.FAILED,
            issues=[],
            failure_reason=reason,
            message=message
        )


@dataclass
class FixResult:
    """Result of attempting to fix a detected issue."""
    outcome: DecisionOutcome
    fixed_code: Optional[str] = None
    refusal_reason: Optional[RefusalReason] = None
    failure_reason: Optional[FailureReason] = None
    message: Optional[str] = None

    @classmethod
    def success(cls, fixed_code: str):
        return cls(outcome=DecisionOutcome.SUCCESS, fixed_code=fixed_code)

    @classmethod
    def refused(cls, reason: RefusalReason, message: str = None):
        return cls(
            outcome=DecisionOutcome.REFUSED,
            refusal_reason=reason,
            message=message
        )

    @classmethod
    def failed(cls, reason: FailureReason, message: str = None):
        return cls(
            outcome=DecisionOutcome.FAILED,
            failure_reason=reason,
            message=message
        )


# Mapping of unsupported issue types to refusal messages
UNSUPPORTED_ISSUE_RATIONALE = {
    "SEC003": "SQL Injection requires contextual knowledge of query structure and cannot be safely auto-fixed.",
    "SEC004": "XSS/SSTI requires understanding of rendering context and escaping semantics.",
    "SEC005": "Insecure deserialization fixes require behavioral guarantees that cannot be verified statically.",
    "LINT001": "Lint fixes may change program semantics in unexpected ways.",
    "PERF001": "Performance issues like infinite loops require understanding of intended behavior.",
}
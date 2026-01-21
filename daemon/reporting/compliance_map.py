
# Compliance Mapping
# Maps internal issue tags/heuristics to external Standards.

COMPLIANCE_MAP = {
    # Secrets & Auth
    "hardcoded_secret": {
        "owasp": "A07:2021-Identification and Authentication Failures",
        "soc2": "CC6.1 (Logical Access Security)",
        "gdpr": "Art. 32 (Security of Processing)",
        "pci": "Requirement 2.1 (No vendor defaults)"
    },
    "hardcoded_password": {
        "owasp": "A07:2021-Identification and Authentication Failures",
        "soc2": "CC6.1 (Logical Access Security)",
        "gdpr": "Art. 32 (Security of Processing)",
        "pci": "Requirement 8.2 (Unique ID/Auth)"
    },
    
    # Injection
    "sql_injection": {
        "owasp": "A03:2021-Injection",
        "soc2": "CC6.6 (Boundary Protection)",
        "pci": "Requirement 6.5.1 (Injection Flaws)"
    },
    "command_injection": {
         "owasp": "A03:2021-Injection",
         "soc2": "CC6.6 (Boundary Protection)",
         "pci": "Requirement 6.5.1"
    },

    # PII / Privacy
    "pii_leak": {
        "owasp": "A04:2021-Insecure Design (Privacy violation)",
        "soc2": "CC6.1 (Access Control)",
        "gdpr": "Art. 5(1)(c) (Data Minimisation)"
    },
    "sensitive_comment": {
        "owasp": "A01:2021-Broken Access Control (Info Leak)",
        "soc2": "CC6.1 (Access Control)",
        "gdpr": "Art. 32 (Security of Processing)"
    },

    # Logic / Quality
    "high_complexity": {
        "owasp": "A04:2021-Insecure Design",
        "soc2": "CC7.1 (System Operations - Maintainability)"
    }
}

def get_compliance_tags(issue_type: str):
    """Returns dict of compliance tags for a given issue type."""
    default = {
        "owasp": "Uncategorized",
        "soc2": "General Logic",
        "gdpr": "N/A",
        "pci": "N/A"
    }
    result = COMPLIANCE_MAP.get(issue_type, default)
    # Ensure all keys exist (merge with defaults)
    return {**default, **result}

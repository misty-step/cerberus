"""Shared Cerberus review schema constants.

Keep the live reviewer contract in one place so structured extraction and
parse-time validation cannot drift independently.
"""

VERDICT_VALUES = ("PASS", "WARN", "FAIL", "SKIP")
FINDING_SEVERITIES = ("critical", "major", "minor", "info")
AC_COMPLIANCE_STATUSES = ("SATISFIED", "NOT_SATISFIED", "CANNOT_DETERMINE")
REQUIRED_ROOT_FIELDS = (
    "reviewer",
    "perspective",
    "verdict",
    "confidence",
    "summary",
    "findings",
    "stats",
)
OPTIONAL_ROOT_FIELDS = frozenset({"ac_compliance"})
PIPELINE_ROOT_FIELDS = frozenset({"_diagnostics", "_extraction_usage"})
ROOT_FIELDS = frozenset(REQUIRED_ROOT_FIELDS) | OPTIONAL_ROOT_FIELDS | PIPELINE_ROOT_FIELDS
REQUIRED_FINDING_FIELDS = frozenset({
    "severity",
    "category",
    "file",
    "line",
    "title",
    "description",
})
OPTIONAL_FINDING_FIELDS = frozenset({
    "suggestion",
    "evidence",
    "scope",
    "suggestion_verified",
})
FINDING_FIELDS = REQUIRED_FINDING_FIELDS | OPTIONAL_FINDING_FIELDS
REQUIRED_AC_COMPLIANCE_FIELDS = frozenset({
    "total",
    "satisfied",
    "not_satisfied",
    "cannot_determine",
    "details",
})
REQUIRED_AC_COMPLIANCE_DETAIL_FIELDS = frozenset({
    "ac",
    "status",
    "evidence",
})
DEPRECATED_FINDING_FIELDS = frozenset({
    "_unverified",
    "_unverified_reason",
    "_evidence_unverified",
    "_evidence_reason",
})
DEPRECATED_FINDING_TITLE_PREFIXES = ("[unverified] ", "[speculative] ")
VALID_FINDING_SCOPES = ("diff", "defaults-change")


def build_extraction_verdict_schema() -> dict:
    """Return the JSON schema used for structured verdict extraction."""
    return {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": list(VERDICT_VALUES)},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "summary": {"type": "string"},
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {"type": "string", "enum": list(FINDING_SEVERITIES)},
                        "category": {"type": "string"},
                        "file": {"type": "string"},
                        "line": {"type": "integer"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "suggestion": {"type": "string"},
                        "evidence": {"type": "string"},
                        "scope": {"type": "string", "enum": list(VALID_FINDING_SCOPES)},
                        "suggestion_verified": {"type": "boolean"},
                    },
                    "required": sorted(REQUIRED_FINDING_FIELDS | {"suggestion"}),
                    "additionalProperties": False,
                },
            },
            "stats": {
                "type": "object",
                "properties": {
                    "files_reviewed": {"type": "integer"},
                    "files_with_issues": {"type": "integer"},
                    "critical": {"type": "integer"},
                    "major": {"type": "integer"},
                    "minor": {"type": "integer"},
                    "info": {"type": "integer"},
                },
                "required": [
                    "files_reviewed",
                    "files_with_issues",
                    "critical",
                    "major",
                    "minor",
                    "info",
                ],
                "additionalProperties": False,
            },
            "ac_compliance": {
                "type": "object",
                "properties": {
                    "total": {"type": "integer"},
                    "satisfied": {"type": "integer"},
                    "not_satisfied": {"type": "integer"},
                    "cannot_determine": {"type": "integer"},
                    "details": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "ac": {"type": "string"},
                                "status": {"type": "string", "enum": list(AC_COMPLIANCE_STATUSES)},
                                "evidence": {"type": "string"},
                            },
                            "required": sorted(REQUIRED_AC_COMPLIANCE_DETAIL_FIELDS),
                            "additionalProperties": False,
                        },
                    },
                },
                "required": sorted(REQUIRED_AC_COMPLIANCE_FIELDS),
                "additionalProperties": False,
            },
        },
        "required": ["verdict", "confidence", "summary", "findings", "stats"],
        "additionalProperties": False,
    }


EXTRACTION_VERDICT_SCHEMA = build_extraction_verdict_schema()

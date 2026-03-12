"""Shared Cerberus review schema constants.

Keep the live reviewer contract in one place so structured extraction and
parse-time validation cannot drift independently.
"""

VERDICT_VALUES = ("PASS", "WARN", "FAIL", "SKIP")
FINDING_SEVERITIES = ("critical", "major", "minor", "info")
REQUIRED_ROOT_FIELDS = (
    "reviewer",
    "perspective",
    "verdict",
    "confidence",
    "summary",
    "findings",
    "stats",
)
PIPELINE_ROOT_FIELDS = frozenset({"_extraction_usage"})
ROOT_FIELDS = frozenset(REQUIRED_ROOT_FIELDS) | PIPELINE_ROOT_FIELDS
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
            "confidence": {"type": "number"},
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
        },
        "required": ["verdict", "confidence", "summary", "findings", "stats"],
        "additionalProperties": False,
    }


EXTRACTION_VERDICT_SCHEMA = build_extraction_verdict_schema()

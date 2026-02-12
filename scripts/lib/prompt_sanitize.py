"""Sanitization helpers for untrusted inputs.

Cerberus interpolates user-controlled PR fields into prompt templates. Those
fields must be treated as data, not as instructions, and must not be able to
break out of the trust-boundary tags used in templates.
"""

from __future__ import annotations

import html


def escape_untrusted_xml(text: str) -> str:
    """Escape text for inclusion in XML-ish element content.

    We only need to prevent tag breaks, so escaping &, <, > is sufficient.
    """
    return html.escape(text or "", quote=False)


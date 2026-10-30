"""
Section plugins. Each module here registers itself via
`@register_section(...)` at import time. To add a new section, drop a
new file in this directory and import it below — no other change
needed in the report system.
"""
from app.services.report.sections import (  # noqa: F401
    cover,
    summary,
    key_findings,
    entities_table,
    relationships,
    graph_snapshot,
    searches,
    alerts,
    timeline,
    evidence,
    activity,
    captures,
)

"""
PDF report module — Spec §5.3 + §1.4 Phase-1 list.

The report is composed from independent SECTION plugins. Each plugin
declares itself with `@register_section(name=..., order=..., default=...)`
and returns a `SectionData` from its async `build(...)` function.

Adding a new section = drop a new file under
`app/services/report/sections/` and import it in this package's
`__init__.py`. No other code changes required.

Public API:
    from app.services.report import generate_report, list_sections
"""
# Importing the registry exposes register_section/SectionData/etc.
# Importing the sections subpackage triggers each section file's
# top-level `@register_section(...)` decorator → registry populated.
from app.services.report.base import (  # noqa: F401
    SectionData,
    register_section,
    list_sections,
    get_section,
)
from app.services.report.generator import generate_report  # noqa: F401
from app.services.report import sections  # noqa: F401  (registers plugins)

# Exporting a case

Beside the report button, **Export** offers four machine-readable formats. Use the
report when a person will read it; use an export when a *system* or another
agency's analyst will.

| Format | Use it for |
|---|---|
| **CSV** | Spreadsheets, your own case management, quick filtering |
| **Maltego CSV** | Importing the case as a graph into Maltego |
| **MISP event** | Handing indicators to a CERT / threat-intel platform |
| **STIX 2.1** | The international standard for exchanging cyber-threat information |

## What travels with a finding

All four formats carry provenance, because a finding without its origin is not
usable evidence for the receiving side:

* the **tool** that reported it,
* every tool that **independently confirmed** it,
* the **Admiralty rating**,
* the **source URL**, where the tool provided one.

## Two rules that apply to every export

**Placeholders never leave the building.** Nodes that exist only to keep the graph
connected are excluded. Nobody asserted them, and a partner agency receiving them
would have no way of telling them apart from confirmed findings.

**Every export is logged.** The audit trail records who exported which case, when,
in which format, and a SHA-256 checksum of the exact payload. Handing findings to
another agency is precisely the kind of act a case file must be able to prove
later — including proving that what you sent is what they received.

## Format-specific behaviour worth knowing

**MISP: indicators are not armed by default.** Attributes go out with
`to_ids=false` unless you marked the finding as relevant. `to_ids=true` tells the
receiving system to *block or alert on* an indicator — unvetted OSINT must not
arrive ready to fire on a partner's network. Marking a finding relevant is your
statement that you have checked it; that is what flips the flag.

**STIX: findings outside the standard vocabulary are declared.** OSINT produces
object types STIX has no equivalent for. Rather than silently dropping them or
mislabelling them, they ship as `x-osint-entity` and the bundle carries a `note`
object saying how many did so. The receiver can then decide what to do with them
instead of being unaware they exist.

**CSV and Maltego** carry the same field set; the Maltego variant uses the column
names Maltego's import expects, so it maps to entities and links without manual
work.

## What is exported

The same selection rule the report uses:

* If anything in the case is marked **relevant**, the export contains exactly
  those findings.
* Otherwise it contains everything not marked as a false positive.

So the export follows your triage. If you want the full picture, clear the
relevance marks first; if you want the case as you have assessed it, leave them.

## Before you send

1. Check the rating of what you are sending — see
   [Assessing findings](12-assessing-findings.md). Rating **F** means the source
   was never assessed, which the receiving analyst cannot know unless you say so.
2. Consider whether **everything** in the file belongs in someone else's hands.
   The export contains what your case contains, including notes.
3. Remember that the receiving side has no access to your case. What you send is
   all they will ever see of it, so the provenance fields are doing real work.

See also: [Reports](08-reports.md) · [Assessing findings](12-assessing-findings.md)

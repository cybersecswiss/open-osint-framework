/**
 * Display helper: strip a redundant leading "{entity_type}:" prefix from a
 * label so the analyst sees the bare value (e.g. "email:foo@bar" → "foo@bar",
 * "breach:Foo" → "Foo"). New data is already clean (the backend graph_builder
 * canonicalizes labels), but older rows and some runners still carry the
 * prefix — this keeps the UI consistent either way.
 *
 * The prefix only strips when it exactly matches the entity_type, so an
 * intentionally-different prefix like "pwfp:" on a password_fingerprint is
 * left untouched.
 */
export function displayLabel(entityType?: string | null, label?: string | null): string {
  const l = (label || '').trim()
  if (!l || !entityType) return l
  const pfx = `${entityType}:`
  return l.startsWith(pfx) ? l.slice(pfx.length).trim() : l
}

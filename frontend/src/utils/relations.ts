/**
 * The relations an investigator can assert by hand.
 *
 * Two rules this list exists to enforce:
 *
 * 1. **The stored value is language-independent.** What goes in the case is
 *    the snake_case key, never the translated label. Otherwise the same
 *    assertion made by a German and a French investigator would produce two
 *    different `relation_type` values in one tenant, and every export, filter
 *    and cross-case comparison would silently split along the UI language.
 *
 * 2. **`associated_with` is deliberately vague and deliberately offered.**
 *    Often the honest statement is "these two belong together, I do not yet
 *    know how". A list that only offered precise relations would push an
 *    investigator to pick a specific one they cannot support — overstating in
 *    a case file is worse than a link that says plainly it is unspecified.
 *
 * Free text stays possible for what this list does not cover; it is
 * normalised to the same shape so a typed relation cannot masquerade as a
 * different kind of value.
 */

export interface RelationOption {
  /** Stored verbatim in `relation_type`. Never translated. */
  value: string
  /** i18n key under `relations.` for what the investigator reads. */
  labelKey: string
}

export const RELATIONS: RelationOption[] = [
  { value: 'associated_with', labelKey: 'relations.associated_with' },
  { value: 'same_person', labelKey: 'relations.same_person' },
  { value: 'alias_of', labelKey: 'relations.alias_of' },
  { value: 'controls', labelKey: 'relations.controls' },
  { value: 'owns', labelKey: 'relations.owns' },
  { value: 'member_of', labelKey: 'relations.member_of' },
  { value: 'employed_by', labelKey: 'relations.employed_by' },
  { value: 'communicates_with', labelKey: 'relations.communicates_with' },
  { value: 'transacted_with', labelKey: 'relations.transacted_with' },
  { value: 'located_at', labelKey: 'relations.located_at' },
]

/**
 * Bring a hand-typed relation into the same shape as the presets.
 *
 * Without this "Same Person", "same person" and "same_person" would be three
 * relations in the graph that read as one on screen.
 */
export function normaliseRelation(raw: string): string {
  return (raw || '')
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 60)
}

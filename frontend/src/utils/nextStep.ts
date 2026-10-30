/**
 * The one thing worth doing next in this case.
 *
 * The application had every step an investigation needs and no opinion about
 * their order, so a case read as a landscape of tools. This turns the state
 * of the case into a single suggestion.
 *
 * Four rules keep a suggestion from becoming an instruction:
 *
 *  1. **It is derived from facts, never from the phase.** The phase is a note
 *     the investigator writes about their own work; using it as input here
 *     would let a forgotten click decide what the application recommends.
 *  2. **It says WHY.** "14 selectors in this case have never been searched"
 *     is checkable; "next: open selectors" is an order. A suggestion whose
 *     reasoning is hidden cannot be disagreed with.
 *  3. **One suggestion, not a list.** A list of everything outstanding is the
 *     landscape again, only narrower.
 *  4. **It can be wrong and must be dismissible.** These rules encode a
 *     common order of work, not the only one.
 *
 * Explicitly NOT here: anything resembling progress or completeness. There is
 * no measure of when an investigation is finished, and a number claiming
 * otherwise would be read, in a case file, as a statement.
 */

export type NextStepKind = 'start' | 'triage' | 'selectors' | 'report'

export interface NextStep {
  kind: NextStepKind
  /** Number the suggestion is about — findings, selectors. 0 when n/a. */
  count: number
}

export interface CaseFacts {
  /** Entities as the graph endpoint returns them. */
  entities?: any[] | null
  /**
   * From the worklist endpoint, undefined while loading. `total` is the real
   * number of open selectors; `candidates` is only how many the endpoint
   * chose to return. Reporting the latter would state a cap as a fact — five
   * of six cases here return exactly 50 items because 50 is the limit.
   */
  worklist?: { total?: number; candidates?: number } | null
}

/** Placeholders and the search root are bookkeeping, not findings. */
function realFindings(entities: any[]): any[] {
  return entities.filter((e) => {
    const d = e?.data || {}
    return !d.virtual && !d.root
  })
}

export function nextStep(facts: CaseFacts): NextStep | null {
  const entities = facts.entities || []
  const real = realFindings(entities)

  // Nothing has been collected yet. This is the only case where the
  // suggestion is about starting rather than continuing.
  if (real.length === 0) return { kind: 'start', count: 0 }

  // A search just landed and nobody has looked at any of it. Triage first:
  // it is what makes everything after it usable, and marking false
  // positives shrinks the work that follows. Deliberately only when NOTHING
  // is assessed — once triage has begun, nagging about the rest of a
  // 600-finding list would make the bar noise rather than help.
  const assessed = real.filter(
    (e) => e?.is_relevant === true || e?.is_relevant === false).length
  if (assessed === 0) return { kind: 'triage', count: real.length }

  // Still loading — say nothing rather than guess. A suggestion built on
  // half the facts is worse than a moment of silence.
  const w = facts.worklist
  const candidates = w?.total ?? w?.candidates
  if (candidates === undefined || candidates === null) return null

  if (candidates > 0) return { kind: 'selectors', count: candidates }

  // Everything present has been searched and triage has started. Nothing is
  // claimed to be COMPLETE here — only that nothing is outstanding that this
  // application can see.
  return { kind: 'report', count: real.length }
}

/**
 * Dismissal is remembered per case AND per kind of suggestion.
 *
 * Keyed on the kind so that dismissing "triage" does not also silence the
 * later "14 selectors were never searched" — those are different statements,
 * and hiding the second because the first was unwanted would lose a real
 * finding about the case. Kept in the browser: which hint someone wants to
 * see is a preference of that person, not content of the case file.
 */
const KEY = 'osint.nextstep.dismissed'

export function isDismissed(caseId: string, kind: NextStepKind): boolean {
  try {
    const all = JSON.parse(localStorage.getItem(KEY) || '{}')
    return all?.[caseId] === kind
  } catch {
    return false
  }
}

export function dismiss(caseId: string, kind: NextStepKind): void {
  try {
    const all = JSON.parse(localStorage.getItem(KEY) || '{}')
    all[caseId] = kind
    localStorage.setItem(KEY, JSON.stringify(all))
  } catch {
    /* a full or blocked storage must not break the case view */
  }
}

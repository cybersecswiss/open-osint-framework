/**
 * Render an API timestamp correctly. One place, because it was wrong in
 * fourteen.
 *
 * ## The defect this exists to fix
 *
 * The framework's timestamp columns are `timestamp without time zone` and the
 * API serialises them without a zone suffix — `2026-08-02T23:30:00`. Handed
 * to `new Date(...)`, the browser reads a string like that as **local** time.
 * The values are UTC.
 *
 * Measured with `TZ=Europe/Zurich`:
 *
 *     API value (UTC)   2026-08-02T23:30:00
 *     was displayed     02.08.2026, 23:30
 *     correct           03.08.2026, 01:30
 *
 * Two hours in summer, one in winter — and across midnight **the date moves
 * by a day**. "Case opened on 2 August" instead of the 3rd is not a cosmetic
 * problem in a case file.
 *
 * A second, smaller error sat in the same calls: `toLocaleDateString()`
 * without arguments follows the **browser's** language, not the language the
 * investigator selected in this application. A German UI in an English
 * browser showed `8/2/2026`.
 *
 * ## The rules
 *
 * * A string with no zone marker is UTC. That is what the backend means, and
 *   assuming anything else is how the bug arose.
 * * A string that DOES carry a zone (`Z`, `+02:00`) is respected as given —
 *   some sources, notably findings from the modules, are already explicit.
 * * **One Swiss format, in every language.** See the note below — this is
 *   deliberately NOT locale-dependent.
 * * An unparseable or empty value renders as `—`, never as "Invalid Date"
 *   and never as today.
 *
 * ## Why the format does not follow the UI language
 *
 * The first version rendered `L LT` in the user's language. Correct by the
 * book, wrong for this product: the default UI language is English, so a
 * Swiss investigator saw **`08/03/2026 1:30 AM`**. In a case file that is
 * ambiguous — 8 March or 3 August? — and 12-hour time is not used in any of
 * the four languages this product ships in.
 *
 * Switzerland writes `DD.MM.YYYY` and 24-hour time in German, French and
 * Italian alike. So does the rest of the product's audience. Using one fixed
 * format everywhere also means a timestamp reads identically whether the case
 * was worked in Zurich or Lausanne, and whether the report is opened in
 * German or English — which for evidentiary output matters more than locale
 * purity.
 */
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
dayjs.extend(utc)

// Swiss convention, fixed. See the note in the header on why this is not
// locale-dependent. One place to change if that decision is ever revisited.
const DATE_FMT = 'DD.MM.YYYY'
const TIME_FMT = 'HH:mm'

/** Values that already state their offset — do not re-interpret those. */
const HAS_ZONE = /(?:Z|[+-]\d{2}:?\d{2})$/i

export const EMPTY_DATE = '—'

/** Parse an API timestamp into local time, treating naive values as UTC. */
export function parseApiDate(value: unknown): dayjs.Dayjs | null {
  if (value === null || value === undefined || value === '') return null
  if (typeof value !== 'string' && !(value instanceof Date)) return null
  const raw = value instanceof Date ? value.toISOString() : value.trim()
  if (!raw) return null
  const d = HAS_ZONE.test(raw) ? dayjs(raw) : dayjs.utc(raw).local()
  return d.isValid() ? d : null
}

/** Date only, `03.08.2026`. */
export function formatDate(value: unknown): string {
  const d = parseApiDate(value)
  return d ? d.format(DATE_FMT) : EMPTY_DATE
}

/** Date and time, `03.08.2026 01:30` — the default for anything citable. */
export function formatDateTime(value: unknown): string {
  const d = parseApiDate(value)
  return d ? d.format(`${DATE_FMT} ${TIME_FMT}`) : EMPTY_DATE
}

/** Milliseconds between two API timestamps, or null if either is unusable. */
export function durationMs(from: unknown, to: unknown): number | null {
  const a = parseApiDate(from)
  const b = to === null || to === undefined ? dayjs() : parseApiDate(to)
  if (!a || !b) return null
  return b.valueOf() - a.valueOf()
}

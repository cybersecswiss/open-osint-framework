/**
 * Guess the selector type from what was pasted.
 *
 * The search form used to demand a classification before it would do
 * anything: somebody holding `+41 79 …` had to know that is `phone`, and
 * somebody holding "Hans Müller" had to choose between `person_name` and
 * `keyword` — a distinction the TOOL invented, not the investigation. At the
 * start of a case that is a hurdle for no gain, because the type knowledge
 * already exists in this codebase (utils/pivot.ts, the module manifests).
 *
 * Two rules this must obey to be an improvement rather than a trap:
 *
 *  1. **It proposes, it never decides.** The returned type is pre-selected
 *     and stays changeable. A wrong auto-detection that silently sent the
 *     search down another path would be worse than asking.
 *  2. **It says nothing when it is unsure.** Free text is deliberately NOT
 *     classified as person or company — those look identical to a machine,
 *     and guessing wrong picks the wrong module set. `null` means "you
 *     decide", which is the honest answer.
 */

export interface Detected {
  type: string
  /** Short reason, shown to the analyst so the proposal is inspectable. */
  why: string
}

const RULES: Array<{ type: string; why: string; test: RegExp }> = [
  // Order matters: the most specific pattern first. A t.me link is also a
  // URL, and a CVE is also free text.
  { type: 'tg_channel', why: 't.me link', test: /^(https?:\/\/)?(www\.)?t(elegram)?\.me\/[A-Za-z0-9_]{3,32}\/?$/i },
  { type: 'onion_address', why: '.onion address', test: /^(https?:\/\/)?[a-z2-7]{16,56}\.onion\b/i },
  { type: 'cve', why: 'CVE identifier', test: /^CVE-\d{4}-\d{4,7}$/i },
  { type: 'asn', why: 'AS number', test: /^AS\d{1,10}$/i },
  { type: 'email', why: 'e-mail address', test: /^[^\s@]+@[^\s@]+\.[A-Za-z]{2,}$/ },
  { type: 'btc_address', why: 'Bitcoin address', test: /^(bc1[a-z0-9]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$/ },
  { type: 'eth_address', why: 'Ethereum address', test: /^0x[a-fA-F0-9]{40}$/ },
  { type: 'hash', why: 'SHA-256', test: /^[a-fA-F0-9]{64}$/ },
  { type: 'hash', why: 'SHA-1', test: /^[a-fA-F0-9]{40}$/ },
  { type: 'hash', why: 'MD5', test: /^[a-fA-F0-9]{32}$/ },
  { type: 'ip', why: 'IPv4 address', test: /^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$/ },
  { type: 'ip', why: 'IPv6 address', test: /^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$/ },
  { type: 'url', why: 'URL with a path', test: /^https?:\/\/[^\s/]+\/\S*$/i },
  { type: 'domain', why: 'domain name', test: /^(https?:\/\/)?([a-z0-9-]+\.)+[a-z]{2,}\/?$/i },
]

/** International or Swiss national phone number, once separators are gone. */
function isPhone(raw: string): boolean {
  const digits = raw.replace(/[\s\-/().]/g, '')
  if (/^\+\d{8,15}$/.test(digits)) return true
  // 0XX XXX XX XX — national notation, common on a report sheet.
  return /^0\d{9,11}$/.test(digits)
}

export function detectType(input: string): Detected | null {
  const v = (input || '').trim()
  if (v.length < 3) return null

  // An @handle is a username, except when it is an e-mail (caught below by
  // the rule order — an address contains a dot after the @).
  if (/^@[A-Za-z0-9_.]{3,32}$/.test(v)) return { type: 'username', why: '@handle' }

  if (isPhone(v)) return { type: 'phone', why: 'phone number' }

  for (const r of RULES) {
    if (r.test.test(v)) return { type: r.type, why: r.why }
  }

  // Deliberately no guess for free text. "Hans Müller" and "Müller AG" are
  // indistinguishable here, and picking one silently selects the wrong
  // module set — the analyst knows which it is, the parser does not.
  return null
}

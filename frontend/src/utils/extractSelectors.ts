/**
 * Pull the searchable selectors out of a block of text.
 *
 * A case rarely starts with one value. It starts with a report: two numbers,
 * an e-mail, an alias, a wallet. Today those get typed in one at a time.
 *
 * **The text never leaves the browser.** Extraction is deliberately
 * client-side and nothing about the pasted block is sent anywhere or stored —
 * only the selectors the investigator ticks are committed, and those are the
 * same kind of value the case already holds. That is what makes this
 * acceptable where an attachment store is not: a phone number in a case file
 * is a finding; a seized report in a second system is a second case file.
 * Preprocessing (refang, unicode, decode — `textNormalise.ts`) is part of
 * that same local step and does not weaken the promise.
 *
 * Conservative on purpose. Every pattern here is anchored on word boundaries
 * and validated, because a selector list full of fragments is worse than a
 * short one: each false entry costs a search slot and an investigator's
 * attention.
 *
 * ## What may be added here, and what may not
 *
 * A type belongs in this file only if some module's manifest declares it as a
 * `query_type`, or `graph_builder.TYPE_MAP` knows it as an entity type. A
 * candidate nothing can act on is pure noise by the rule above. That is why
 * IBANs, credit-card numbers and Monero addresses are absent despite being
 * easy to match — no runner accepts them today. When one does, they belong
 * here the same day.
 *
 * The reverse failure is what this file was once guilty of: eight
 * types were wired end-to-end through the manifests, the orchestrator and
 * TYPE_MAP, and this list did not know about them — including
 * `pgp_fingerprint`, `jabber_id`, `tox_id` and `session_id`, which are
 * exactly the contact identifiers a copied vendor profile or forum post
 * contains. The gap sat at the worst possible spot: the very text this
 * drawer exists to read. `ImportSelectorsDrawer` now cross-checks the
 * produced types against the live manifests so the two cannot drift again
 * without saying so.
 */

import { isValidBtcAddress } from './cryptoAddress'
import { prepare } from './textNormalise'

export interface Extracted {
  value: string
  type: string
  /** How many times it appeared — repetition is a weak relevance signal. */
  count: number
  /**
   * True when the value was only found inside a base64/hex blob rather than
   * in the visible text. Surfaced in the UI: an investigator must be able to
   * explain a selector they cannot see in their own paste.
   */
  decoded?: boolean
}

/** Words that look like domains but are file names or sentence noise. */
const NOT_DOMAIN = /\.(png|jpe?g|gif|pdf|docx?|xlsx?|zip|txt|csv|exe|dll|js|ts|html?|css|json|xml|md)$/i

/** Image extensions that make a URL worth handing to the image module. */
const IMAGE_EXT = /\.(png|jpe?g|gif|webp|bmp|tiff?|heic)(?:[?#].*)?$/i

const PATTERNS: Array<{ type: string; re: RegExp; clean?: (s: string) => string }> = [
  // --- unambiguous fixed-shape identifiers, first so they claim their text
  //     before the generic hash patterns can eat a prefix of it ---

  // IMO number — ONLY in its labelled form. A bare seven-digit run is far
  // more often something else (a case number, an amount, a fragment of a
  // phone number), and claiming it would poison every text paste. The label
  // is how it is written wherever it matters: bills of lading, registry
  // extracts, sanctions notices.
  //
  // The check digit is verified server-side, not here: a typo must produce
  // "this is not a valid IMO", not silence.
  { type: 'imo_number', re: /\bIMO[\s:]*([0-9]{7})\b/gi, clean: (s) => s.replace(/\D/g, '') },

  // Swiss health-professional GLN — ONLY in its labelled form, for exactly
  // the reason the IMO number is: prefix 76 is GS1 SWITZERLAND, not GS1
  // health, so a bare 13-digit 76… run is far more often the barcode of a
  // Swiss product than a doctor's number. The label is how it is written
  // where it matters: prescriptions, insurance invoices, MedReg extracts.
  { type: 'gln', re: /\bGLN[\s:]*([0-9]{13})\b/gi, clean: (s) => s.replace(/\D/g, '') },

  // Tox ID: 76 uppercase hex (32-byte key + nospam + checksum). Nothing else
  // in this vocabulary is 76 hex characters long.
  { type: 'tox_id', re: /\b[A-Fa-f0-9]{76}\b/g, clean: (s) => s.toUpperCase() },

  // Session (Oxen) ID: 66 hex starting with the 05 prefix.
  { type: 'session_id', re: /\b05[a-fA-F0-9]{64}\b/g, clean: (s) => s.toLowerCase() },

  // PGP fingerprint, spaced form — five groups of four, twice. This is how
  // keyservers and mail clients print it, and it is unambiguous.
  {
    type: 'pgp_fingerprint',
    re: /\b[0-9A-Fa-f]{4}(?:\s+[0-9A-Fa-f]{4}){9}\b/g,
    clean: (s) => s.replace(/\s+/g, '').toUpperCase(),
  },
  // PGP fingerprint, labelled form. A bare 40-hex run stays a SHA-1 `hash`:
  // that is what it is far more often, and `0x`+40hex is an Ethereum address,
  // so neither may be claimed here.
  {
    type: 'pgp_fingerprint',
    re: /\b(?:pgp|gpg|openpgp|fingerprint|fpr|key\s*id)\b[^\n]{0,20}?\b([0-9A-Fa-f]{40})\b/gi,
    clean: (s) => (s.match(/[0-9A-Fa-f]{40}/) || [''])[0].toUpperCase(),
  },

  // Jabber/XMPP. A JID is shaped exactly like an e-mail address, so it is
  // only claimed where the text says so — via the URI scheme, an explicit
  // label, or an .onion host, which is never a mailbox. Everything else
  // stays an `email`, which is the safer wrong answer of the two.
  //
  // These MUST precede the e-mail rule: the blanking pass gives the text to
  // whichever pattern reaches it first, and `email` matches every JID.
  {
    type: 'jabber_id',
    re: /\bxmpp:([^\s"'<>)\]]+@[^\s"'<>)\]]+)/gi,
    clean: (s) => s.replace(/^xmpp:/i, '').toLowerCase(),
  },
  {
    type: 'jabber_id',
    re: /\b(?:jabber|xmpp|jid)\b\s*[:=]?\s*([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})/gi,
    clean: (s) => (s.match(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/) || [''])[0].toLowerCase(),
  },
  {
    type: 'jabber_id',
    re: /\b[A-Za-z0-9._%+-]+@[a-z2-7]{16,56}\.onion\b/g,
    clean: (s) => s.toLowerCase(),
  },

  { type: 'email', re: /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g },

  { type: 'tg_channel', re: /\bhttps?:\/\/t\.me\/([A-Za-z0-9_]{3,32})\b/g, clean: (s) => s.replace(/.*t\.me\//i, '') },

  // Discord invite — the shareable form an investigator is handed.
  {
    type: 'discord_invite',
    re: /\b(?:https?:\/\/)?(?:www\.)?(?:discord\.gg|discord(?:app)?\.com\/invite)\/([A-Za-z0-9-]{2,32})\b/gi,
    clean: (s) => s.replace(/.*\//, ''),
  },
  // Discord snowflake. Labelled only: a bare 17-20 digit run is also a
  // plausible reference number, order number or account number, and an
  // unlabelled match would put one in every commercial-fraud report.
  {
    type: 'discord_id',
    re: /\b(?:discord|snowflake)\b[^\n]{0,24}?\b(\d{17,20})\b/gi,
    clean: (s) => (s.match(/\d{17,20}/) || [''])[0],
  },

  { type: 'onion_address', re: /\b[a-z2-7]{56}\.onion\b/g },

  { type: 'btc_address', re: /\b(?:bc1[a-z0-9]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b/g },
  { type: 'eth_address', re: /\b0x[a-fA-F0-9]{40}\b/g },
  { type: 'hash', re: /\b[a-fA-F0-9]{64}\b/g },
  { type: 'hash', re: /\b[a-fA-F0-9]{40}\b/g },
  { type: 'hash', re: /\b[a-fA-F0-9]{32}\b/g },
  { type: 'cve', re: /\bCVE-\d{4}-\d{4,7}\b/gi, clean: (s) => s.toUpperCase() },
  // Autonomous system number. Four digits minimum, which is a measured
  // trade-off rather than the spec: `AS400` (the IBM midrange), `AS9` and
  // `AS12` turn up in ordinary prose and in part numbers, while AS1–AS999 is
  // legacy IANA space that no cybercrime case pivots on. Real targets —
  // AS13335, AS15169, 32-bit numbers — are all four digits or more.
  { type: 'asn', re: /\bAS\d{4,10}\b/g, clean: (s) => s.toUpperCase() },
  { type: 'ip', re: /\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b/g },
  // An image URL is a selector the image module can actually run (EXIF/GPS,
  // visual geolocation); as a plain `url` it reaches nothing.
  { type: 'image_url', re: /\bhttps?:\/\/[^\s"'<>)\]]+\.(?:png|jpe?g|gif|webp|bmp|tiff?|heic)(?:[?#][^\s"'<>)\]]*)?/gi },
  // t.me links are already captured as a channel above; reporting them again
  // as a URL gives the analyst the same lead twice in two shapes.
  { type: 'url', re: /\bhttps?:\/\/(?!t\.me\/)[^\s"'<>)\]]+/g },
  { type: 'username', re: /(?:^|[\s(,;])@([A-Za-z0-9_]{3,32})\b/g, clean: (s) => s.replace(/^[\s(,;]*@/, '') },
  { type: 'domain', re: /\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}\b/gi },
]

/** Swiss and international phone numbers as they appear on a report sheet. */
const PHONE_RE = /(?:\+\d{1,3}[\s./-]?)?(?:\(?\d{2,4}\)?[\s./-]?){2,5}\d{2,4}/g

function extractPhones(text: string): string[] {
  const out: string[] = []
  for (const m of text.matchAll(PHONE_RE)) {
    const raw = m[0]
    const digits = raw.replace(/[^\d+]/g, '')
    // A run of digits is only a phone number if it has a plausible length AND
    // a phone-like shape. Without this every date, amount and case number in
    // a report arrives as a "phone number".
    if (/^\+\d{8,15}$/.test(digits)) out.push(digits)
    else if (/^0\d{9,11}$/.test(digits)) out.push(digits)
  }
  return out
}

type Bucket = Map<string, { type: string; value: string; count: number; decoded: boolean }>

/** Run every pattern over one body of text, folding results into `counts`. */
function scan(src: string, counts: Bucket, fromDecoded: boolean): void {
  const add = (type: string, value: string) => {
    const v = value.trim().replace(/[.,;:)\]]+$/, '')
    if (!v) return
    if (type === 'domain' && NOT_DOMAIN.test(v)) return
    // A regex says an address looks right; only the checksum says it is one.
    if (type === 'btc_address' && !isValidBtcAddress(v)) return
    // An image URL that lost its extension to the trailing-punctuation trim
    // is just a URL again.
    if (type === 'image_url' && !IMAGE_EXT.test(v)) return
    const key = `${type}::${v.toLowerCase()}`
    const cur = counts.get(key)
    if (cur) {
      cur.count += 1
      // Seen in the visible text at least once ⇒ no longer "decoded only".
      if (!fromDecoded) cur.decoded = false
    } else {
      counts.set(key, { type, value: v, count: 1, decoded: fromDecoded })
    }
  }

  // Everything except domains first, blanking each match out of a working
  // copy as we go. Domains are then scanned on what is LEFT.
  //
  // Two problems this solves, both found by running it on a realistic report:
  // scanning the raw text pulled `protonmail.com` out of an e-mail address as
  // if it were a separate lead, while a simple "skip anything contained in an
  // earlier match" was too blunt and dropped a domain that was ALSO written
  // out on its own line. Blanking the consumed spans keeps the standalone
  // mention and loses only the parts that really are inside something else.
  //
  // The same mechanism resolves the new overlaps by pattern ORDER: a jabber
  // JID is consumed before the e-mail rule sees it, an image URL before the
  // generic URL rule, a Session ID before the 64-hex hash rule.
  let residual = src
  for (const p of PATTERNS) {
    if (p.type === 'domain') continue
    p.re.lastIndex = 0
    for (const m of residual.matchAll(p.re)) {
      const whole = m[0]
      add(p.type, p.clean ? p.clean(whole) : whole)
      residual = residual.split(whole).join(' ')
    }
  }
  const domainRule = PATTERNS.filter((p) => p.type === 'domain')[0]
  domainRule.re.lastIndex = 0
  for (const m of residual.matchAll(domainRule.re)) add('domain', m[0])
  for (const ph of extractPhones(src)) add('phone', ph)
}

export function extractSelectors(text: string): Extracted[] {
  if (!String(text || '').trim()) return []

  // Refang, normalise, and decode any base64/hex layers — all in-browser.
  const { clean, decoded } = prepare(text)

  const counts: Bucket = new Map()
  scan(clean, counts, false)
  if (decoded) scan(decoded, counts, true)

  return [...counts.values()]
    .map(({ type, value, count, decoded: d }) => (d ? { type, value, count, decoded: true } : { type, value, count }))
    .sort((a, b) => b.count - a.count || a.type.localeCompare(b.type)
      || a.value.localeCompare(b.value))
}

/**
 * entity_type to store a selector as — mirrors utils/pivot.ts in reverse.
 *
 * The right-hand side must be a type `graph_builder.TYPE_MAP` canonicalises,
 * or the committed node lands beside the one a search would create instead of
 * merging with it.
 */
export const TYPE_TO_ENTITY: Record<string, string> = {
  // Transport assets. `vessel` and `aircraft` have no extraction pattern —
  // a ship's name is ordinary text and a tail number looks like a hundred
  // other short codes, so they are typed deliberately in the search form
  // rather than guessed out of a paste. `imo_number` IS extractable,
  // because its labelled form is unambiguous.
  imo_number: 'imo_number',
  gln: 'gln',
  vessel: 'vessel',
  aircraft: 'aircraft',
  email: 'email_address',
  username: 'username',
  domain: 'domain',
  ip: 'ip',
  url: 'url',
  phone: 'phone',
  btc_address: 'btc_address',
  eth_address: 'eth_address',
  hash: 'hash',
  // canonical_entity() maps cve -> vulnerability server-side; naming it
  // that way here keeps the drawer's label and the stored node identical.
  cve: 'vulnerability',
  onion_address: 'onion_service',
  tg_channel: 'telegram_channel',
  // Wired end-to-end in the backend since long before the extractor learnt
  // to see them — see the header note.
  pgp_fingerprint: 'pgp_key',
  jabber_id: 'jabber_id',
  tox_id: 'tox_id',
  session_id: 'session_id',
  discord_invite: 'discord_invite',
  discord_id: 'discord_guild',
  asn: 'asn',
  image_url: 'image',
}

/**
 * The query_type a module would need to declare for this selector to be
 * searchable. Almost always the extractor's own type; `email` and a couple of
 * others differ from their entity name.
 */
export const TYPE_TO_QUERY_TYPE: Record<string, string> = {
  imo_number: 'imo_number',
  gln: 'gln',
  vessel: 'vessel',
  aircraft: 'aircraft',
  email: 'email',
  username: 'username',
  domain: 'domain',
  ip: 'ip',
  url: 'url',
  phone: 'phone',
  btc_address: 'btc_address',
  eth_address: 'eth_address',
  hash: 'hash',
  cve: 'cve',
  onion_address: 'onion_address',
  tg_channel: 'tg_channel',
  pgp_fingerprint: 'pgp_fingerprint',
  jabber_id: 'jabber_id',
  tox_id: 'tox_id',
  session_id: 'session_id',
  discord_invite: 'discord_invite',
  discord_id: 'discord_id',
  asn: 'asn',
  image_url: 'image_url',
}

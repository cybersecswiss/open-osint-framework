/**
 * Make pasted text extractable before anything tries to read selectors out
 * of it. Three transformations, each of which was silently costing findings.
 *
 * **All of this runs in the browser and nothing leaves it** — the same
 * promise the import drawer makes about the raw text applies to every
 * intermediate form produced here.
 *
 * 1. **Refanging.** CERT bulletins, NCSC advisories, vendor reports and
 *    inter-agency mail write indicators defanged so they are not clickable:
 *    `evil[.]com`, `hxxp://x`, `user[at]mail.com`. Every pattern in
 *    extractSelectors expects a real dot and a real `http`, so a pasted
 *    advisory — one of the most likely documents an investigator has in the
 *    clipboard — yielded *nothing at all*. Not a few missed values: an empty
 *    list, which reads as "this tool found nothing" rather than "this tool
 *    cannot read this".
 *
 * 2. **Unicode normalisation.** Zero-width characters inside handles and
 *    addresses are a deliberate anti-scraping measure on the boards this
 *    product is pointed at, and homoglyphs (Cyrillic `а` in a domain) are a
 *    standard evasion. Without NFKC and a zero-width strip, the same handle
 *    arrives as two different selectors, or as none.
 *
 * 3. **Decoding.** Base64 and hex blobs carry the actual selector one layer
 *    down: forwarded mail, config dumps, ransom notes, contact details a
 *    vendor posted encoded. Borrowed from AIL's "decoded files" idea, which
 *    re-feeds decoded content through the same extraction — cheap here
 *    because `atob` is native and the work stays local.
 *
 * Deliberately NOT done: rot13/atbash guessing, gzip, or anything that needs
 * to try a key. Those turn extraction into cryptanalysis, and a wrong guess
 * produces plausible garbage that an analyst then has to disprove.
 */

/** Zero-width and bidi controls that hide inside handles and addresses. */
const INVISIBLE = /[​-‏‪-‮⁠-⁤﻿]/g

/**
 * NFKC-fold and strip invisibles.
 *
 * NFKC also folds full-width forms (`ｅｖｉｌ.ｃｏｍ`) and ligatures onto their
 * ASCII equivalents, which is what makes the patterns match. It does NOT map
 * Cyrillic to Latin — nothing standard does, because they are genuinely
 * different letters. A homoglyph domain therefore still extracts as its own
 * distinct value, which is the honest outcome: it IS a different domain, and
 * showing it next to the lookalike is how an analyst notices.
 */
export function normaliseUnicode(text: string): string {
  return text.normalize('NFKC').replace(INVISIBLE, '')
}

/** Ordered refang rules. Applied to a working copy only. */
const REFANG: Array<[RegExp, string]> = [
  // Scheme: hxxp, hxxps, h**p, hXXp — with or without the brackets around ://
  [/\bh(?:xx|XX|\*\*)p(s?)\b/g, 'http$1'],
  [/:\s*\/\s*\//g, '://'],
  [/\[:\/\/\]/g, '://'],
  [/\[:\]/g, ':'],
  // Dot: [.] (.) {.} [dot] (dot) [punkt] — bracketed forms only.
  // A bare " dot " is NOT refanged: too much ordinary prose says "dot".
  [/\s*[[({]\s*(?:\.|dot|punkt|d0t)\s*[\])}]\s*/gi, '.'],
  // At: [@] (at) [at] — same rule, brackets required.
  [/\s*[[({]\s*(?:@|at)\s*[\])}]\s*/gi, '@'],
  // Backslash-escaped dots, as produced when someone pastes out of a regex
  // or a Markdown editor that escaped the text.
  [/\\\./g, '.'],
]

export function refang(text: string): string {
  let out = text
  for (const [re, to] of REFANG) out = out.replace(re, to)
  return out
}

// --- decoding layer ------------------------------------------------------

/** Base64 runs long enough to be a payload rather than a word. */
const B64_RE = /\b[A-Za-z0-9+/]{24,}={0,2}/g
/** Hex runs of at least 16 bytes. Hashes match this too — see _printable. */
const HEX_RE = /\b(?:[0-9a-fA-F]{2}){16,}\b/g

/** Total decoded characters appended, across all layers. Keeps the tab live. */
const MAX_DECODED = 200_000
/** How many times a decoded result is itself scanned for more layers. */
const MAX_DEPTH = 2

/**
 * Is this decoded byte string worth handing back to the extractor?
 *
 * The check does most of the work of avoiding nonsense: a SHA-256 hash is a
 * perfectly valid 32-byte hex string, and decoding it yields binary noise
 * that would otherwise be scanned for selectors and occasionally produce a
 * "domain" out of thin air.
 */
function printable(s: string): boolean {
  if (s.length < 8) return false
  let ok = 0
  for (const ch of s) {
    const c = ch.charCodeAt(0)
    if ((c >= 0x20 && c <= 0x7e) || c === 9 || c === 10 || c === 13) ok++
  }
  return ok / s.length >= 0.85
}

function b64decode(s: string): string | null {
  try {
    // atob yields a byte string; decode as UTF-8 so non-ASCII survives.
    const bin = atob(s.replace(/=+$/, '').padEnd(Math.ceil(s.replace(/=+$/, '').length / 4) * 4, '='))
    const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0))
    return new TextDecoder('utf-8', { fatal: false }).decode(bytes)
  } catch {
    return null
  }
}

function hexdecode(s: string): string | null {
  try {
    const bytes = new Uint8Array(s.length / 2)
    for (let i = 0; i < bytes.length; i++) {
      bytes[i] = parseInt(s.substr(i * 2, 2), 16)
    }
    return new TextDecoder('utf-8', { fatal: false }).decode(bytes)
  } catch {
    return null
  }
}

/**
 * Decode base64/hex blobs found in `text` and return the decoded content as
 * additional text to scan. The original is not modified — a value that
 * appears both in the clear and inside a blob should still be found twice,
 * because that repetition is a real signal.
 *
 * Returns the concatenated decoded layers, capped. Empty string when there
 * is nothing decodable, which is the common case.
 */
export function decodeLayers(text: string, depth = MAX_DEPTH): string {
  const out: string[] = []
  let budget = MAX_DECODED

  const walk = (src: string, left: number) => {
    if (left <= 0 || budget <= 0) return
    for (const re of [B64_RE, HEX_RE]) {
      re.lastIndex = 0
      for (const m of src.matchAll(re)) {
        if (budget <= 0) return
        const raw = m[0]
        const dec = re === B64_RE ? b64decode(raw) : hexdecode(raw)
        if (!dec || !printable(dec)) continue
        // A blob that decodes to itself (or to a superset of the source) is
        // a loop, not a layer.
        if (dec === raw || src.includes(dec)) continue
        const slice = dec.slice(0, budget)
        budget -= slice.length
        out.push(slice)
        walk(slice, left - 1)
      }
    }
  }

  walk(text, depth)
  return out.join('\n')
}

/**
 * The full preprocessing chain: what the extractor should actually read.
 *
 * Returns the cleaned text plus the decoded layers separately, so a caller
 * can tell an analyst that a finding came from a decoded blob rather than
 * from something visible in the pasted document. That distinction matters:
 * a value the investigator cannot see in their own paste needs to be
 * explainable.
 */
export function prepare(text: string): { clean: string; decoded: string } {
  const clean = refang(normaliseUnicode(String(text || '')))
  return { clean, decoded: decodeLayers(clean) }
}

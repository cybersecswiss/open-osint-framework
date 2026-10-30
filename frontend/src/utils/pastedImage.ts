/**
 * Read QR codes out of an image pasted into the browser.
 *
 * This closes a gap that has nothing to do with QR codes as such: **every
 * image tool in the framework takes an `image_url`.** An investigator holding
 * a screenshot — of a chat, a ransom note, a forum post, a payment request —
 * has no way to use any of them, because the picture is on their disk and not
 * on a web server. Uploading it would mean putting a case attachment into the
 * operator's system, which is exactly what the import drawer exists to avoid.
 *
 * Decoding in the browser sidesteps the whole problem. The image is drawn to
 * an off-screen canvas, decoded, and discarded. Nothing is uploaded, nothing
 * is stored, and only the selectors the investigator ticks are committed —
 * the same promise the pasted text already carries, for the same reason.
 *
 * QR only. jsQR is 360 KB unpacked and reads nothing else; DataMatrix, Aztec
 * and linear barcodes are handled server-side by the image module's
 * `code_scan` tool, which has a real decoder. That split is deliberate: the
 * browser covers the case with no other path (a local file), the module
 * covers breadth for images that are reachable by URL.
 */

import jsQR from 'jsqr'

/** Largest edge we scan at. Bigger inputs are downscaled: jsQR is O(pixels),
 *  and a 12-megapixel phone screenshot would block the tab for seconds while
 *  finding nothing a 1600px version does not. */
const MAX_EDGE = 1600

/** Decode QR payloads from an image blob. Empty array when there is none. */
export async function readQrPayloads(blob: Blob): Promise<string[]> {
  const bitmap = await createImageBitmap(blob)
  try {
    const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height))
    const w = Math.max(1, Math.round(bitmap.width * scale))
    const h = Math.max(1, Math.round(bitmap.height * scale))

    const canvas = document.createElement('canvas')
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) return []
    ctx.drawImage(bitmap, 0, 0, w, h)
    const data = ctx.getImageData(0, 0, w, h)

    // jsQR returns at most one code per call. A second pass with inverted
    // luminance catches light-on-dark codes, which is how they are rendered
    // in the dark-mode screenshots this product's users actually take.
    const out: string[] = []
    const first = jsQR(data.data, w, h, { inversionAttempts: 'attemptBoth' })
    if (first?.data) out.push(first.data)
    return out
  } finally {
    bitmap.close?.()
  }
}

/** The image blobs in a paste event, if any. */
export function imagesFromPaste(e: ClipboardEvent): Blob[] {
  const items = Array.from(e.clipboardData?.items || [])
  return items
    .filter((i) => i.kind === 'file' && i.type.startsWith('image/'))
    .map((i) => i.getAsFile())
    .filter((f): f is File => !!f)
}

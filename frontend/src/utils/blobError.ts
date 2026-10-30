/**
 * Read the server's error message out of a failed *file download*.
 *
 * ## Why this is needed at all
 *
 * A download is requested with `responseType: 'blob'`, and axios applies that
 * to the error response too. So when the server answers
 *
 *     403 {"detail": "Your key was rejected by the customer agent"}
 *
 * the handler sees `e.response.data` as a `Blob`, and the usual
 * `e?.response?.data?.detail` is `undefined`. Every download error in the app
 * therefore fell through to its generic fallback — "export failed" — and the
 * one sentence that said *why* was sitting unread inside the blob.
 *
 * That matters most exactly where it was happening: report and export are the
 * two places where the answer is often actionable ("the case has no findings
 * to export", "the agent rejected the key"), and where the user's next step
 * differs completely depending on which it was.
 *
 * Async because reading a Blob is; callers already sit in an async catch.
 */
export async function blobErrorDetail(e: any): Promise<string> {
  const data = e?.response?.data

  // Not a blob — the ordinary JSON path still applies.
  if (data && typeof data === 'object' && !(data instanceof Blob)) {
    return data.detail || data.message || ''
  }

  if (data instanceof Blob) {
    try {
      const text = await data.text()
      if (!text) return ''
      try {
        const parsed = JSON.parse(text)
        return parsed?.detail || parsed?.message || ''
      } catch {
        // Not JSON: a proxy error page or a plain-text body. Show a short
        // prefix rather than dumping HTML into a toast.
        return text.length > 200 ? '' : text
      }
    } catch {
      return ''
    }
  }

  return ''
}

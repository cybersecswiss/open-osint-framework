// The last stated purpose per case, in this browser only. An order or file
// number usually covers a whole series of searches in one case; retyping it
// for every selector invites "s.o." — which is worse than no field at all.
// Per case on purpose: carrying one case's order into another would put a
// wrong legal basis on record.

const KEY = 'searchPurpose:'

export function lastPurpose(caseId: string): string | null {
  try {
    return localStorage.getItem(KEY + caseId)
  } catch {
    return null
  }
}

export function rememberPurpose(caseId: string, purpose: string): void {
  try {
    localStorage.setItem(KEY + caseId, purpose.slice(0, 500))
  } catch {
    // storage blocked: the field simply starts empty next time
  }
}

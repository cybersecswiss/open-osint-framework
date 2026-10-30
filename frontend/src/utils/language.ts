// Which UI language a user sees, in order of precedence:
//
//   1. their own choice from the header switch (localStorage 'lang')
//   2. the tenant default the tenant admin set (applied once settings load)
//   3. the browser's preferred languages
//   4. German
//
// Starting everyone without a stored choice in English would show a user in
// Lausanne or Bellinzona the first screen in the one language the product is
// not primarily written for. German is the last resort rather than English
// because the platform targets Swiss users, and German is the language the
// handbook and help text are maintained in alongside English.

export const SUPPORTED_LANGS = ['de', 'fr', 'it', 'en'] as const
export type Lang = (typeof SUPPORTED_LANGS)[number]

const STORAGE_KEY = 'lang'

function isLang(v: unknown): v is Lang {
  return typeof v === 'string' && (SUPPORTED_LANGS as readonly string[]).includes(v)
}

export function storedLang(): Lang | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    return isLang(v) ? v : null
  } catch {
    return null
  }
}

export function storeLang(lang: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, lang)
  } catch {
    // Private window / blocked storage: the switch still works for this tab.
  }
}

export function browserLang(): Lang | null {
  const prefs = (typeof navigator !== 'undefined'
    ? (navigator.languages?.length ? navigator.languages : [navigator.language])
    : []) as readonly string[]
  for (const p of prefs) {
    const base = (p || '').toLowerCase().split('-')[0]
    if (isLang(base)) return base
  }
  return null
}

/** The language to start with, before tenant settings are known. */
export function initialLang(): Lang {
  return storedLang() ?? browserLang() ?? 'de'
}

/**
 * Once tenant settings arrive: the tenant default wins over the browser, but
 * never over a choice the user made themselves. Returns the language to
 * switch to, or null if nothing should change.
 */
export function tenantLangOverride(tenantDefault: string | null | undefined, current: string): Lang | null {
  if (storedLang()) return null
  if (!isLang(tenantDefault)) return null
  return tenantDefault === current ? null : tenantDefault
}

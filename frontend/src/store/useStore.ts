import { create } from 'zustand'
import { initialLang, storeLang } from '../utils/language'

interface User {
  user_id: string
  username: string
  email: string
  roles: string[]
  tenant: string
}

interface AppStore {
  user: User | null
  setUser: (user: User | null) => void
  lang: string
  setLang: (lang: string) => void
  applyLang: (lang: string) => void
  /**
   * 'light' | 'dark' | 'system'. Investigative work is screen work over
   * long shifts; 'system' is the default so the app follows the operating
   * system rather than imposing a choice nobody made.
   */
  themeMode: ThemeMode
  setThemeMode: (m: ThemeMode) => void
}

export type ThemeMode = 'light' | 'dark' | 'system'

function storedTheme(): ThemeMode {
  const v = localStorage.getItem('themeMode')
  return v === 'light' || v === 'dark' || v === 'system' ? v : 'system'
}

export const useStore = create<AppStore>((set) => ({
  user: null,
  setUser: (user) => set({ user }),
  lang: initialLang(),
  // An explicit pick from the header switch: remembered, and from then on
  // it outranks the tenant default.
  setLang: (lang) => {
    storeLang(lang)
    set({ lang })
  },
  // A language applied on the user's behalf (tenant default). Not stored, so
  // a later change of the tenant default still reaches this user.
  applyLang: (lang) => set({ lang }),
  themeMode: storedTheme(),
  setThemeMode: (themeMode) => {
    localStorage.setItem('themeMode', themeMode)
    set({ themeMode })
  },
}))

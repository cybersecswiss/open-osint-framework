import { RouterProvider } from 'react-router-dom'
import { ConfigProvider, App as AntdApp, theme } from 'antd'
import { useEffect, useState } from 'react'
import { useStore } from './store/useStore'
import { useTranslation } from 'react-i18next'
import deDE from 'antd/locale/de_DE'
import enUS from 'antd/locale/en_US'
import frFR from 'antd/locale/fr_FR'
import itIT from 'antd/locale/it_IT'
import { router } from './router'

// Bind AntD's own built-in strings (pagination, table filter buttons,
// date pickers, Popconfirm defaults …) to the user's chosen language —
// previously these stayed English regardless of the DE/FR/IT switch.
const ANTD_LOCALES: Record<string, typeof enUS> = {
  de: deDE, en: enUS, fr: frFR, it: itIT,
}

export default function App() {
  const { i18n } = useTranslation()
  const lang = (i18n.language || 'en').split('-')[0]
  const locale = ANTD_LOCALES[lang] || enUS
  const themeMode = useStore((s) => s.themeMode)

  // The <html lang> attribute drove nothing but the initial "en": a screen
  // reader pronounced a German case file with English phonemes regardless of
  // the language switch. It is also the first thing an accessibility audit
  // looks at. Kept in sync with the actual UI language.
  useEffect(() => {
    document.documentElement.setAttribute('lang', lang)
  }, [lang])

  // 'system' follows the OS and keeps following it while the app is open.
  const [prefersDark, setPrefersDark] = useState(
    () => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false)
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!mq) return
    const on = (e: MediaQueryListEvent) => setPrefersDark(e.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  const dark = themeMode === 'dark' || (themeMode === 'system' && prefersDark)

  // Antd paints its own surfaces; the page behind them is ours, and without
  // this a dark UI sits on a white body during scroll overshoot.
  useEffect(() => {
    document.body.style.background = dark ? '#141414' : '#f5f5f5'
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
  }, [dark])

  return (
    <ConfigProvider
      locale={locale}
      theme={{
        algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm,
        token: {
          colorPrimary: '#1677ff',
          borderRadius: 6,
        },
      }}
    >
      {/* AntD App context provides theme-aware message/Modal/notification. */}
      <AntdApp>
        <RouterProvider router={router} />
      </AntdApp>
    </ConfigProvider>
  )
}

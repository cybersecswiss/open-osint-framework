import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import HttpBackend from 'i18next-http-backend'
import { initialLang } from './utils/language'

i18n
  .use(HttpBackend)
  .use(initReactI18next)
  .init({
    lng: initialLang(),
    fallbackLng: 'en',
    ns: ['common'],
    defaultNS: 'common',
    // Cache-busted per build — see the BUILD_ID comment in vite.config.ts.
    // Without it a browser (and Cloudflare in front of it) keeps serving the
    // previous translation file, because the URL is identical and nginx
    // sends no Cache-Control. The symptom is raw keys like
    // `admin.tab_notifications` in one language and correct text in the
    // others, which reads like a broken translation rather than a cache.
    backend: { loadPath: `/locales/{{lng}}/{{ns}}.json?v=${__BUILD_ID__}` },
    interpolation: { escapeValue: false },
  })

export default i18n

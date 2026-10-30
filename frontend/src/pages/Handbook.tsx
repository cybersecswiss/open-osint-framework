import { useCallback, useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Spin, Alert } from 'antd'
import { useTranslation } from 'react-i18next'
import ChangelogView from '../components/changelog/ChangelogView'

// In-app user wiki. The content is plain Markdown served from
// /wiki/<lang>/<slug>.md (bind-mounted from frontend/public/wiki —
// editable live, no rebuild). Adding a page = drop a new .md there + one
// line in that language's index.json. This component just renders
// whatever the index lists.
//
// Language handling: the handbook follows the app's language switch. Each
// locale is a directory; a page that has not been translated yet falls
// back to the English original AND SAYS SO, because silently serving
// English under a German menu leaves the reader unsure whether they are
// looking at the current text or an outdated one. The index falls back
// wholesale, so a new locale can be added one page at a time.

type WikiPage = { slug: string; title: string }

// The changelog is part of the handbook's navigation but not a Markdown page.
const CHANGELOG_SLUG = '__changelog'
type WikiIndex = { title: string; pages: WikiPage[] }

const WIKI_BASE = '/wiki'
const LANGS = ['en', 'de', 'fr', 'it'] as const
const FALLBACK_LANG = 'en'

function wikiLang(appLang: string): string {
  const base = (appLang || '').split('-')[0].toLowerCase()
  return (LANGS as readonly string[]).includes(base) ? base : FALLBACK_LANG
}

export default function Handbook() {
  const { t, i18n } = useTranslation()
  const lang = wikiLang(i18n.language)
  const [index, setIndex] = useState<WikiIndex | null>(null)
  // `?page=changelog` opens the changelog directly (linked from the update hint).
  const [active, setActive] = useState<string>(() =>
    new URLSearchParams(window.location.search).get('page') === 'changelog' ? CHANGELOG_SLUG : '')
  const [content, setContent] = useState<string>('')
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<'index' | 'page' | null>(null)
  // True while the reader is looking at the English original because this
  // page has no translation in the selected language yet.
  const [fellBack, setFellBack] = useState(false)

  useEffect(() => {
    // `cache: 'no-cache'` → always revalidate with the server. The wiki
    // is live-editable (bind-mounted), so a stale HTTP-cached index.json
    // must never hide a newly-added page. A page-load hard-refresh does
    // NOT reset the cache mode of JS-issued fetches, so we set it here.
    let cancelled = false
    const load = async () => {
      for (const l of [lang, FALLBACK_LANG]) {
        try {
          const r = await fetch(`${WIKI_BASE}/${l}/index.json`, { cache: 'no-cache' })
          if (!r.ok) continue
          // Same trap as the page fetch: a catch-all route answers 200 with
          // HTML, and .json() would throw — caught below and retried against
          // English, which is the behaviour we want, but be explicit about it.
          const idx: WikiIndex = await r.json()
          if (!idx || !Array.isArray(idx.pages) || !idx.pages.length) continue
          if (cancelled) return
          setIndex(idx)
          // Keep the reader on the same page across a language switch —
          // landing back on the overview every time would be hostile.
          setActive((cur) => (cur === CHANGELOG_SLUG || (cur && idx.pages.some((p) => p.slug === cur))
            ? cur : idx.pages[0]?.slug || ''))
          return
        } catch {
          /* try the fallback locale */
        }
      }
      if (!cancelled) { setError('index'); setLoading(false) }
    }
    load()
    return () => { cancelled = true }
  }, [lang])

  useEffect(() => {
    if (!active) return
    if (active === CHANGELOG_SLUG) { setLoading(false); setError(null); return }
    let cancelled = false
    setLoading(true); setError(null)
    const load = async () => {
      for (const l of [lang, FALLBACK_LANG]) {
        try {
          const r = await fetch(`${WIKI_BASE}/${l}/${active}.md`, { cache: 'no-cache' })
          if (!r.ok) continue
          const md = await r.text()
          // A missing file must not be mistaken for a page. Any SPA-style
          // catch-all in front of us answers 200 with index.html, and
          // rendering that as Markdown would show the reader HTML source
          // instead of falling back to the English original.
          if (!md || /^\s*<(!doctype|html)\b/i.test(md)) continue
          if (cancelled) return
          setContent(md)
          setFellBack(l !== lang)
          setLoading(false)
          return
        } catch {
          /* try the fallback locale */
        }
      }
      if (!cancelled) { setError('page'); setLoading(false) }
    }
    load()
    return () => { cancelled = true }
  }, [active, lang])

  const openPage = useCallback((slug: string) => {
    setActive(slug)
    const el = document.getElementById('wiki-scroll')
    if (el) el.scrollTop = 0
  }, [])

  // Turn in-wiki "…/05-telegram.md" links into in-app page switches;
  // leave real external links to open in a new tab.
  const Anchor = (props: any) => {
    const href: string = props.href || ''
    // `09-reference.md#query-types` too: headings carry no ids, and in a
    // translated page the anchor would not match the heading anyway, so the
    // link opens the page rather than going nowhere.
    if (/\.md(#.*)?$/.test(href) && !/^https?:\/\//.test(href)) {
      const slug = href.replace(/#.*$/, '').replace(/^.*\//, '').replace(/\.md$/, '')
      return (
        <a href={`#${slug}`} onClick={(e) => { e.preventDefault(); openPage(slug) }}>
          {props.children}
        </a>
      )
    }
    const external = /^https?:\/\//.test(href)
    return (
      <a href={href} target={external ? '_blank' : undefined} rel={external ? 'noopener noreferrer' : undefined}>
        {props.children}
      </a>
    )
  }

  if (error === 'index') {
    return <Alert type="error" showIcon message={t('handbook.load_error')} />
  }

  return (
    <div className="wiki-root">
      <style>{WIKI_CSS}</style>
      <aside className="wiki-nav">
        <div className="wiki-nav-title">{index?.title || t('nav.handbook')}</div>
        <nav>
          {index?.pages.map((p, i) => (
            <button
              key={p.slug}
              type="button"
              className={p.slug === active ? 'active' : ''}
              onClick={() => openPage(p.slug)}
            >
              <span className="n">{String(i).padStart(2, '0')}</span>
              <span>{p.title}</span>
            </button>
          ))}
          {/* Not a Markdown page: rendered from /wiki/changelog.json. */}
          <button
            type="button"
            className={active === CHANGELOG_SLUG ? 'active' : ''}
            onClick={() => openPage(CHANGELOG_SLUG)}
            style={{ marginTop: 8, borderTop: '1px solid var(--w-border)', borderRadius: 0, paddingTop: 10 }}
          >
            <span className="n">✎</span>
            <span>{t('changelog.title')}</span>
          </button>
        </nav>
      </aside>
      <div className="wiki-scroll" id="wiki-scroll">
        <div className="wiki-doc">
          {active === CHANGELOG_SLUG ? (
            <ChangelogView />
          ) : loading ? (
            <div style={{ padding: 48, textAlign: 'center' }}><Spin /></div>
          ) : error === 'page' ? (
            <Alert type="error" showIcon message={t('handbook.load_error')} />
          ) : (
            <>
              {fellBack && (
                <Alert
                  type="info" showIcon style={{ marginBottom: 20 }}
                  message={t('handbook.untranslated')}
                />
              )}
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: Anchor }}>
                {content}
              </ReactMarkdown>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

const WIKI_CSS = `
.wiki-root {
  --w-accent: #235c8c; --w-accent-soft: #e9f1f8; --w-ink: #1f2733;
  --w-soft: #4a5563; --w-muted: #7a8493; --w-border: #e6eaf0; --w-code-bg: #f2f5f8;
  display: grid; grid-template-columns: 15rem minmax(0,1fr);
  height: calc(100vh - 160px); min-height: 420px; gap: 0;
  border: 1px solid var(--w-border); border-radius: 8px; overflow: hidden; background: #fff;
}
.wiki-nav { border-right: 1px solid var(--w-border); background: #fafbfc; overflow-y: auto; padding: 14px 10px; }
.wiki-nav-title { font-size: 12px; text-transform: uppercase; letter-spacing: .08em; color: var(--w-muted); font-weight: 700; padding: 4px 8px 10px; }
.wiki-nav nav { display: flex; flex-direction: column; gap: 2px; }
.wiki-nav button { display: flex; gap: 8px; align-items: baseline; text-align: left; width: 100%;
  background: none; border: none; cursor: pointer; padding: 7px 8px; border-radius: 6px;
  font-size: 13.5px; color: var(--w-soft); line-height: 1.3; font-family: inherit; }
.wiki-nav button:hover { background: #eef1f5; color: var(--w-ink); }
.wiki-nav button.active { background: var(--w-accent-soft); color: var(--w-accent); font-weight: 600; }
.wiki-nav button .n { font-family: ui-monospace, Menlo, monospace; font-size: 11px; color: var(--w-muted); min-width: 16px; }
.wiki-nav button.active .n { color: var(--w-accent); }
.wiki-scroll { overflow-y: auto; }
.wiki-doc { max-width: 46rem; padding: 28px clamp(20px, 4vw, 44px) 64px; color: var(--w-ink); font-size: 15.5px; line-height: 1.68; }
.wiki-doc h1 { font-size: 1.9rem; letter-spacing: -.02em; margin: .2em 0 .3em; line-height: 1.15; }
.wiki-doc h2 { font-size: 1.35rem; letter-spacing: -.01em; margin: 1.8em 0 .3em; padding-top: .8em; border-top: 1px solid var(--w-border); }
.wiki-doc h3 { font-size: 1.08rem; margin: 1.6em 0 .2em; }
.wiki-doc p, .wiki-doc li { max-width: 42rem; }
.wiki-doc a { color: var(--w-accent); text-decoration: none; border-bottom: 1px solid rgba(35,92,140,.3); }
.wiki-doc a:hover { border-bottom-color: var(--w-accent); }
.wiki-doc code { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: .85em; background: var(--w-code-bg);
  border: 1px solid var(--w-border); border-radius: 5px; padding: .06em .38em; color: var(--w-accent); white-space: nowrap; }
.wiki-doc pre { background: var(--w-code-bg); border: 1px solid var(--w-border); border-radius: 8px; padding: 14px 16px; overflow-x: auto; }
.wiki-doc pre code { background: none; border: none; padding: 0; white-space: pre; color: var(--w-ink); }
.wiki-doc blockquote { margin: 1.2em 0; padding: .7em 1.1em; background: var(--w-accent-soft);
  border-left: 3px solid var(--w-accent); border-radius: 6px; color: var(--w-soft); }
.wiki-doc blockquote p { margin: .3em 0; }
.wiki-doc table { border-collapse: collapse; width: 100%; font-size: .9em; margin: 1.1em 0; display: block; overflow-x: auto; }
.wiki-doc th, .wiki-doc td { border: 1px solid var(--w-border); padding: 7px 11px; text-align: left; vertical-align: top; }
.wiki-doc thead th { background: #f4f6f9; font-size: .82em; text-transform: uppercase; letter-spacing: .04em; color: var(--w-muted); }
.wiki-doc hr { border: none; border-top: 1px solid var(--w-border); margin: 2em 0; }
.wiki-doc ul, .wiki-doc ol { padding-left: 1.3em; }
.wiki-doc li { margin: .3em 0; }
.wiki-doc strong { color: var(--w-ink); }
@media (max-width: 720px) {
  .wiki-root { grid-template-columns: 1fr; height: auto; }
  .wiki-nav { border-right: none; border-bottom: 1px solid var(--w-border); }
  .wiki-nav nav { flex-flow: row wrap; }
}
`

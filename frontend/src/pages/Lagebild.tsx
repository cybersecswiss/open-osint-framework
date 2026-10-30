import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Card, Row, Col, Typography, Tag, Space, Alert, Spin, Button, Empty, Tooltip,
} from 'antd'
import { SearchOutlined, LinkOutlined } from '@ant-design/icons'
import DigestPanel from '../components/lagebild/DigestPanel'

const { Title, Paragraph, Text } = Typography

/**
 * "Lagebild" — a curated entry point for analysts facing an empty search box.
 *
 * Content comes from /threat-catalog/catalog.json, bind-mounted into the
 * nginx container (see docker-compose.yml) exactly like the in-app wiki:
 * an authority can edit the catalogue live, without a rebuild, and keep it in
 * step with the reports it cites.
 *
 * The data path deliberately differs from the route (/lagebild): a mounted
 * directory of the same name shadows the SPA route, and nginx answers the
 * page with a 301 into an empty directory instead of the app. Same reason
 * the wiki lives at /wiki/ while its page is /handbook.
 *
 * Deliberate framing: the
 * catalogue lists FIELDS OF CRIME with their source, never organisations as
 * "threats". A government tool that labels a named, lawful association a
 * threat makes a judgement it cannot substantiate. Every card therefore
 * carries its source and date, and the suggestions are research entry
 * points, not findings.
 */

interface Localised { de?: string; en?: string; fr?: string; it?: string }
interface Topic { title: Localised; queries: string[]; facets: string[] }
interface Source { name: string; date: string; url: string }
interface Category {
  key: string
  icon?: string
  title: Localised
  summary: Localised
  source: Source
  topics: Topic[]
}
interface Catalog {
  version: string
  disclaimer: Localised
  categories: Category[]
}

/** Pick the analyst's language, falling back to German then any value.
 *  A partially translated catalogue must still render — an authority adding
 *  a category in one language should not blank the page for the others. */
function pick(v: Localised | undefined, lang: string): string {
  if (!v) return ''
  return (v as any)[lang] || v.de || v.en || Object.values(v)[0] || ''
}

/**
 * Keep an editing mistake in the catalogue from breaking the page.
 *
 * The file is bind-mounted and **meant to be edited live** by the authority
 * — that is its whole point. It was read structurally without guards, so a
 * category missing its `source`, or a topic missing `queries`, threw during
 * render. With no error boundary in the app at the time, React 18 unmounted
 * the entire tree: the whole product went white, navigation included, and
 * nothing said which file was at fault.
 *
 * There is a boundary now (`components/ErrorBoundary.tsx`), but a boundary
 * turns a crash into an apology. Validating here turns it into a sentence
 * that names the broken category — which is what somebody who just edited
 * the file actually needs.
 *
 * Deliberately lenient where it can be: a category with two good topics and
 * one broken one shows the two. Dropping the whole card would punish the
 * reader for the editor's slip.
 */
function sanitise(raw: any): { catalog: Catalog; problems: string[] } {
  const problems: string[] = []
  const categories: Category[] = []

  for (const [i, c] of (Array.isArray(raw?.categories) ? raw.categories : []).entries()) {
    const where = c?.key || `#${i + 1}`
    if (!c?.title) { problems.push(`${where}: title`); continue }
    // `source` carries the citation the whole page is built on — a card
    // without it would assert a field of crime with nothing behind it.
    const url = typeof c?.source?.url === 'string' ? c.source.url.trim() : ''
    // Only http(s). The file is operator-edited, but `javascript:` in an
    // href executes, and this is the one file the product invites edits to.
    const safeUrl = /^https?:\/\//i.test(url) ? url : ''
    if (!safeUrl) problems.push(`${where}: source.url`)

    const topics: Topic[] = []
    for (const t of Array.isArray(c?.topics) ? c.topics : []) {
      const queries = (Array.isArray(t?.queries) ? t.queries : [])
        .filter((q: any) => typeof q === 'string' && q.trim())
      if (!t?.title || !queries.length) {
        problems.push(`${where} → ${pick(t?.title, 'de') || '?'}: queries`)
        continue
      }
      topics.push({ title: t.title, queries, facets: Array.isArray(t.facets) ? t.facets : [] })
    }

    categories.push({
      key: c.key || `cat-${i}`,
      icon: c.icon,
      title: c.title,
      summary: c.summary,
      source: { name: c?.source?.name || '', date: c?.source?.date || '', url: safeUrl },
      topics,
    })
  }
  return {
    catalog: {
      version: typeof raw?.version === 'string' ? raw.version : '?',
      disclaimer: raw?.disclaimer || {},
      categories,
    },
    problems,
  }
}

export default function Lagebild() {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [problems, setProblems] = useState<string[]>([])
  const [error, setError] = useState(false)
  const lang = (i18n.language || 'de').slice(0, 2)

  useEffect(() => {
    // no-cache: the catalogue is bind-mounted and edited live, so a stale
    // browser copy would hide exactly the updates it exists for.
    fetch('/threat-catalog/catalog.json', { cache: 'no-cache' })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((raw) => {
        const { catalog: c, problems: p } = sanitise(raw)
        setCatalog(c)
        setProblems(p)
      })
      .catch(() => setError(true))
  }, [])

  /** Hand the topic to the News page: a Lagebild entry is a research
   *  starting point, and the first thing an analyst wants is to read what
   *  the sources say — not to write nodes into a case. From there the
   *  "Add to case" button leads on to the ordinary search. */
  const startSearch = (topic: Topic) => {
    navigate('/news', {
      state: {
        prefill: {
          query: topic.queries[0],
          query_type: 'keyword',
          facets: topic.facets || [],
        },
      },
    })
  }

  // The situation report does not depend on the threat catalogue, so it is
  // rendered before it. It used to sit behind two early returns, which meant
  // a missing or slow-loading catalogue file hid the day's reporting as well
  // — the difference between "still loading" and "nothing to report".
  if (error || !catalog) {
    return (
      <div>
        <DigestPanel />
        <div style={{ height: 28 }} />
        {error ? (
          <Alert
            type="warning"
            showIcon
            message={t('lagebild.unavailable_title')}
            description={t('lagebild.unavailable_desc')}
          />
        ) : <Spin />}
      </div>
    )
  }

  return (
    <div>
      <DigestPanel />
      <div style={{ height: 28 }} />
      <Title level={3} style={{ marginBottom: 4 }}>{t('lagebild.title')}</Title>
      <Paragraph type="secondary" style={{ marginBottom: 16 }}>
        {t('lagebild.intro')}
      </Paragraph>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 20 }}
        message={t('lagebild.disclaimer_title')}
        description={
          <>
            {pick(catalog.disclaimer, lang)}
            <div style={{ marginTop: 6 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {t('lagebild.catalog_version', { version: catalog.version })}
              </Text>
            </div>
          </>
        }
      />

      {problems.length > 0 && (
        // Names the broken entries instead of silently dropping them: the
        // person who sees this is usually the person who just edited the file.
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={t('lagebild.catalog_problems', { n: problems.length })}
          description={
            <Text style={{ fontSize: 12 }} code>{problems.join(' · ')}</Text>
          }
        />
      )}

      {!catalog.categories?.length && <Empty description={t('lagebild.empty')} />}

      <Row gutter={[16, 16]}>
        {catalog.categories.map((cat) => (
          <Col xs={24} lg={12} key={cat.key}>
            <Card
              title={
                <Space>
                  <span style={{ fontSize: 18 }}>{cat.icon}</span>
                  <span>{pick(cat.title, lang)}</span>
                </Space>
              }
              size="small"
              style={{ height: '100%' }}
            >
              <Paragraph style={{ marginBottom: 12 }}>
                {pick(cat.summary, lang)}
              </Paragraph>

              <Space direction="vertical" size={6} style={{ width: '100%' }}>
                {cat.topics.map((topic) => (
                  <div
                    key={pick(topic.title, lang)}
                    style={{
                      display: 'flex', alignItems: 'center',
                      justifyContent: 'space-between', gap: 8,
                    }}
                  >
                    <Space size={4} wrap>
                      <Text>{pick(topic.title, lang)}</Text>
                      {(topic.facets || []).map((f) => (
                        <Tag key={f} color="blue" style={{ marginInlineEnd: 0 }}>
                          {f}
                        </Tag>
                      ))}
                    </Space>
                    <Tooltip
                      title={t('lagebild.search_hint', {
                        query: topic.queries[0],
                      })}
                    >
                      <Button
                        size="small"
                        icon={<SearchOutlined />}
                        onClick={() => startSearch(topic)}
                      >
                        {t('lagebild.search_action')}
                      </Button>
                    </Tooltip>
                  </div>
                ))}
              </Space>

              <div style={{ marginTop: 14, paddingTop: 10, borderTop: '1px solid #f0f0f0' }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {t('lagebild.source')}:{' '}
                  {cat.source.url ? (
                    <a href={cat.source.url} target="_blank" rel="noreferrer">
                      {cat.source.name || cat.source.url} <LinkOutlined />
                    </a>
                  ) : (
                    <Text type="danger" style={{ fontSize: 12 }}>
                      {t('lagebild.source_missing')}
                    </Text>
                  )}{' '}
                  {cat.source.date ? `(${cat.source.date})` : ''}
                </Text>
              </div>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  )
}

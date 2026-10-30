import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  Input, Select, Button, Space, Tag, List, Typography, Alert, Empty,
  Collapse, Badge, Spin, Tooltip, Card, Checkbox, Divider, message,
} from 'antd'
import {
  SearchOutlined, LinkOutlined, PlusOutlined, RobotOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import {
  newsApi, NewsArticle, NewsSource, newsAiApi, AiNewsResult,
  casesApi, tenantApi,
} from '../api/client'
import { facetOptions, MAX_FACETS } from '../utils/facets'
import LoadFailed from '../components/LoadFailed'

const { Title, Paragraph, Text } = Typography

/**
 * News & RSS — an analyst's reading surface over the configured feeds.
 *
 * Deliberately NOT the case search form. Here the analyst looks through
 * sources first and decides afterwards whether something belongs in a
 * case; requiring a case up front would turn exploration into bookkeeping.
 * A hit worth keeping goes to the ordinary search via "Add to case",
 * which runs the same term through module-news and persists it.
 *
 * The source list is shown on purpose: an empty result only means
 * "not in these feeds", and that is only interpretable if you can see
 * which feeds were searched.
 */

const KIND_COLOR: Record<string, string> = {
  authority: 'blue', police: 'geekblue', media: 'orange',
  cyber: 'purple', other: 'default',
}

/** Split a query into highlight/match terms, honouring "quoted phrases"
 *  (one phrase = one term) and stripping the quote characters so they are
 *  never highlighted or matched literally. Mirrors the backend parse. */
function parseTerms(q: string): string[] {
  const s = (q || '').trim().replace(/[„“”»«]/g, '"')
  const phrases: string[] = []
  const rest = s.replace(/"([^"]+)"/g, (_m, p) => { phrases.push(p.trim()); return ' ' })
  return [...phrases, ...rest.split(/\s+/)].map((t) => t.trim()).filter(Boolean)
}

/** Highlight every search term inside the matched passage. Case-insensitive
 *  and escaped, because a term like "C++" would otherwise be a broken regex. */
function highlight(text: string, terms: string[]) {
  if (!text) return null
  const clean = terms.map((s) => s.trim()).filter((s) => s.length > 1)
  if (!clean.length) return text
  const rx = new RegExp(`(${clean.map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'gi')
  return text.split(rx).map((part, i) =>
    clean.some((c) => c.toLowerCase() === part.toLowerCase())
      ? <mark key={i} style={{ background: '#fff1a8', padding: '0 1px' }}>{part}</mark>
      : <span key={i}>{part}</span>,
  )
}

export default function News() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  const [sources, setSources] = useState<NewsSource[]>([])
  const [query, setQuery] = useState('')
  const [facets, setFacets] = useState<string[]>([])
  const [articles, setArticles] = useState<NewsArticle[] | null>(null)
  const [notes, setNotes] = useState<string[]>([])
  const [kindFilter, setKindFilter] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [sourcesFailed, setSourcesFailed] = useState(false)
  const [licenceFailed, setLicenceFailed] = useState(false)
  const [casesFailed, setCasesFailed] = useState(false)
  // AI news analysis (licensed per authority via ai_enabled).
  const [aiEnabled, setAiEnabled] = useState(false)
  const [cases, setCases] = useState<{ id: string; title: string }[]>([])
  const [aiCaseId, setAiCaseId] = useState<string | undefined>()
  const [aiRunning, setAiRunning] = useState(false)
  const [aiResult, setAiResult] = useState<AiNewsResult | null>(null)
  const [aiError, setAiError] = useState('')
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const [applying, setApplying] = useState(false)

  // These three used to end in `.catch(() => {})`, which turned every
  // failure into a wrong statement rather than no statement:
  //   * sources  -> the page said "no sources configured", which is a claim
  //                 about the configuration, not about the request;
  //   * licence  -> the AI button silently vanished, indistinguishable from
  //                 "your authority is not licensed for it";
  //   * cases    -> the target list for "apply to case" stayed empty, so the
  //                 button could never work and nothing said why.
  // Same failure mode as elsewhere (see LoadFailed.tsx): a failure that looks
  // like an ordinary empty result.
  useEffect(() => {
    newsApi.sources()
      .then((d) => { setSources(d.sources || []); setSourcesFailed(false) })
      .catch(() => setSourcesFailed(true))
    tenantApi.getLicense()
      .then((l) => { setAiEnabled(!!l?.ai_enabled); setLicenceFailed(false) })
      .catch(() => setLicenceFailed(true))
    casesApi.list().then((d) => {
      const list = Array.isArray(d) ? d : (d?.cases || d?.items || [])
      setCases(list.map((c: any) => ({ id: c.id, title: c.title || c.name || c.id })))
      setCasesFailed(false)
    }).catch(() => setCasesFailed(true))
  }, [])

  // Arriving from a Lagebild topic: adopt the term + narrowing and run it
  // straight away — the analyst clicked a topic to READ about it.
  useEffect(() => {
    const pre = (location.state as any)?.prefill
    if (!pre?.query) return
    setQuery(pre.query)
    setFacets(pre.facets || [])
    navigate(location.pathname, { replace: true, state: null })
    void runWith(pre.query, pre.facets || [])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const runWith = async (q: string, fs: string[]) => {
    q = q.trim()
    if (q.length < 2) return
    setLoading(true); setError(''); setArticles(null)
    try {
      const res = await newsApi.search(q, fs)
      setArticles(res.articles || [])
      setNotes(res.notes || [])
    } catch {
      setError(t('news.search_failed'))
    } finally {
      setLoading(false)
    }
  }

  const run = () => runWith(query, facets)

  /** Run the AI analysis over the cached feeds for the current keyword.
   *  Async job on the backend (Gemini can exceed the proxy timeout), so we
   *  poll the job id until it is done or errors. */
  const runAi = async () => {
    const q = query.trim()
    if (q.length < 2) return
    setAiRunning(true); setAiError(''); setAiResult(null); setPicked(new Set())
    try {
      const { job_id } = await newsAiApi.analyze(q, facets)
      for (let i = 0; i < 140; i++) {
        await new Promise((r) => setTimeout(r, 1500))
        const st = await newsAiApi.status(job_id)
        if (st.status === 'done') {
          setAiResult(st)
          setPicked(new Set((st.entities || []).map((_, idx) => idx)))  // preselect all
          return
        }
        if (st.status === 'error') { setAiError(st.detail || t('news.ai_failed')); return }
      }
      setAiError(t('news.ai_timeout'))
    } catch (e: any) {
      setAiError(e?.response?.status === 403 ? t('news.ai_not_licensed') : t('news.ai_failed'))
    } finally {
      setAiRunning(false)
    }
  }

  const togglePick = (i: number) => setPicked((prev) => {
    const n = new Set(prev)
    if (n.has(i)) n.delete(i); else n.add(i)
    return n
  })

  /** Commit the selected AI entities (+ the connections among them) to the
   *  chosen case, through the normal graph-commit path. */
  const applyAi = async () => {
    if (!aiCaseId || !aiResult?.entities) return
    const ents = aiResult.entities.filter((_, i) => picked.has(i))
    if (!ents.length) { message.info(t('news.ai_pick_some')); return }
    const labels = new Set(ents.map((e) => e.label.toLowerCase()))
    const kw = (aiResult.query || query).trim()
    const kwLow = kw.toLowerCase()
    const inSet = (l?: string) => {
      const s = (l || '').toLowerCase()
      return labels.has(s) || s === kwLow
    }
    const conns = (aiResult.connections || []).filter((c) => inSet(c.from_label) && inSet(c.to_label))
    setApplying(true)
    try {
      const res = await newsAiApi.apply({
        case_id: aiCaseId, keyword: kw, link_keyword: true,
        entities: ents.map((e) => ({
          entity_type: e.entity_type, label: e.label,
          confidence: e.confidence, source_url: e.source_url,
          data: e.context ? { context: e.context } : {},
        })),
        connections: conns.map((c) => ({
          from_label: c.from_label, to_label: c.to_label,
          relation: c.relation, confidence: c.confidence,
        })),
      })
      message.success(t('news.ai_applied', { e: res.added_entities, x: res.added_edges }))
    } catch (e: any) {
      message.error(e?.response?.status === 403 ? t('news.ai_not_licensed') : t('news.ai_apply_failed'))
    } finally {
      setApplying(false)
    }
  }

  /** Send the term to the normal search so the hits land in a case. */
  const addToCase = () => {
    navigate('/search', {
      state: { prefill: { query: query.trim(), type: 'keyword', facets, modules: ['news'] } },
    })
  }

  const byKind = useMemo(() => {
    const m: Record<string, number> = {}
    sources.forEach((s) => { m[s.kind] = (m[s.kind] || 0) + 1 })
    return m
  }, [sources])

  const shown = useMemo(() => {
    if (!articles) return null
    return kindFilter.length
      ? articles.filter((a) => kindFilter.includes(a.source_kind))
      : articles
  }, [articles, kindFilter])

  return (
    <div>
      <Title level={3} style={{ marginBottom: 4 }}>{t('news.title')}</Title>
      <Paragraph type="secondary">{t('news.browse_intro')}</Paragraph>

      <Space.Compact style={{ width: '100%', maxWidth: 720 }}>
        <Input
          size="large"
          allowClear
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onPressEnter={run}
          placeholder={t('news.query_ph')}
          prefix={<SearchOutlined style={{ color: '#bfbfbf' }} />}
        />
        <Button size="large" type="primary" onClick={run} loading={loading}
                disabled={query.trim().length < 2}>
          {t('news.search')}
        </Button>
      </Space.Compact>

      <div style={{ maxWidth: 720, marginTop: 10 }}>
        <Select
          mode="tags"
          allowClear
          style={{ width: '100%' }}
          value={facets}
          onChange={(v) => setFacets(v.slice(0, MAX_FACETS))}
          maxCount={MAX_FACETS}
          placeholder={t('news.facets_ph')}
          options={facetOptions(t)}
          optionFilterProp="label"
        />
      </div>

      {/* AI analysis over the cached feeds — licensed per authority. Only
          public news content leaves the boundary, never case data. */}
      {licenceFailed && (
        <Alert type="warning" showIcon style={{ marginTop: 12 }}
               message={t('news.licence_failed')} />
      )}
      {aiEnabled && (
        <div style={{ maxWidth: 900, marginTop: 12 }}>
          <Space wrap>
            <Tooltip title={t('news.ai_hint')}>
              <Button icon={<RobotOutlined />} onClick={runAi}
                      loading={aiRunning} disabled={query.trim().length < 2}>
                {t('news.ai_analyze')}
              </Button>
            </Tooltip>
            <Select
              allowClear showSearch optionFilterProp="label"
              style={{ minWidth: 240 }}
              status={casesFailed ? 'warning' : undefined}
              placeholder={casesFailed
                ? t('news.cases_failed') : t('news.ai_case_ph')}
              value={aiCaseId}
              onChange={setAiCaseId}
              notFoundContent={casesFailed ? t('news.cases_failed') : undefined}
              options={cases.map((c) => ({ value: c.id, label: c.title }))}
            />
          </Space>

          {aiError && (
            <Alert type="error" showIcon style={{ marginTop: 10 }} message={aiError} />
          )}

          {aiResult && aiResult.status === 'done' && (
            <Card size="small" style={{ marginTop: 12 }}
                  title={
                    <Space>
                      <RobotOutlined />
                      {t('news.ai_result_title', { q: aiResult.query })}
                      <Text type="secondary" style={{ fontWeight: 400 }}>
                        {t('news.ai_analyzed', { n: aiResult.articles_analyzed || 0 })}
                      </Text>
                    </Space>
                  }>
              {aiResult.summary && (
                <Paragraph style={{ whiteSpace: 'pre-wrap' }}>{aiResult.summary}</Paragraph>
              )}

              {(aiResult.entities?.length ?? 0) > 0 && (
                <>
                  <Divider orientation="left" style={{ margin: '8px 0' }}>
                    {t('news.ai_entities', { n: aiResult.entities!.length })}
                  </Divider>
                  <List
                    size="small"
                    dataSource={aiResult.entities}
                    renderItem={(e, i) => (
                      <List.Item>
                        <Checkbox checked={picked.has(i)} onChange={() => togglePick(i)}>
                          <Space size={6} wrap>
                            <Tag color="blue" style={{ marginInlineEnd: 0 }}>{e.entity_type}</Tag>
                            <Text strong>{e.label}</Text>
                            {e.context && <Text type="secondary">— {e.context}</Text>}
                            {e.source_url && (
                              <a href={e.source_url} target="_blank" rel="noreferrer"
                                 onClick={(ev) => ev.stopPropagation()}>
                                <LinkOutlined />
                              </a>
                            )}
                          </Space>
                        </Checkbox>
                      </List.Item>
                    )}
                  />
                </>
              )}

              {(aiResult.connections?.length ?? 0) > 0 && (
                <>
                  <Divider orientation="left" style={{ margin: '8px 0' }}>
                    {t('news.ai_connections')}
                  </Divider>
                  <List
                    size="small"
                    dataSource={aiResult.connections}
                    renderItem={(c) => (
                      <List.Item>
                        <Space size={4} wrap>
                          <Text strong>{c.from_label}</Text>
                          <Text type="secondary">→ {c.relation} →</Text>
                          <Text strong>{c.to_label}</Text>
                          {c.rationale && <Text type="secondary">({c.rationale})</Text>}
                        </Space>
                      </List.Item>
                    )}
                  />
                </>
              )}

              {(aiResult.case_suggestions?.length ?? 0) > 0 && (
                <>
                  <Divider orientation="left" style={{ margin: '8px 0' }}>
                    {t('news.ai_suggestions')}
                  </Divider>
                  <ul style={{ marginTop: 0, marginBottom: 4 }}>
                    {aiResult.case_suggestions!.map((s, i) => <li key={i}>{s}</li>)}
                  </ul>
                </>
              )}

              <Divider style={{ margin: '8px 0' }} />
              <Space wrap>
                <Button type="primary" icon={<PlusOutlined />} onClick={applyAi}
                        loading={applying} disabled={!aiCaseId || picked.size === 0}>
                  {t('news.ai_apply', { n: picked.size })}
                </Button>
                {!aiCaseId && <Text type="secondary">{t('news.ai_pick_case')}</Text>}
              </Space>
              <div style={{ marginTop: 8 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>{t('news.ai_sovereignty')}</Text>
              </div>
            </Card>
          )}
        </div>
      )}

      {/* Which feeds this searches — an empty result is only meaningful
          if you can see the coverage behind it. */}
      <Collapse
        ghost
        style={{ marginTop: 12, maxWidth: 900 }}
        items={[{
          key: 'src',
          label: (
            <Space size={6}>
              <Text strong>{t('news.sources_title', { count: sources.length })}</Text>
              {Object.entries(byKind).map(([k, n]) => (
                <Tag key={k} color={KIND_COLOR[k] || 'default'} style={{ marginInlineEnd: 0 }}>
                  {t(`glbadmin.feeds.kind_${k}`, { defaultValue: k })} {n}
                </Tag>
              ))}
            </Space>
          ),
          children: sources.length === 0 ? (
            sourcesFailed
              ? <LoadFailed compact what={t('loadfail.what.sources')}
                            hint={t('news.sources_failed')} />
              : <Alert type="info" showIcon message={t('news.no_sources')} />
          ) : (
            <List
              size="small"
              dataSource={sources}
              renderItem={(s) => (
                <List.Item>
                  <Space size={8} wrap>
                    <Tag color={KIND_COLOR[s.kind] || 'default'}>
                      {t(`glbadmin.feeds.kind_${s.kind}`, { defaultValue: s.kind })}
                    </Tag>
                    <Text>{s.name}</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {s.lang?.toUpperCase()}
                    </Text>
                  </Space>
                </List.Item>
              )}
            />
          ),
        }]}
      />

      {error && <Alert type="error" showIcon style={{ marginTop: 12 }} message={error} />}

      {loading && (
        <div style={{ marginTop: 24, textAlign: 'center' }}>
          <Spin /> <Text type="secondary" style={{ marginLeft: 8 }}>{t('news.searching')}</Text>
        </div>
      )}

      {shown && !loading && (
        <div style={{ marginTop: 20 }}>
          <Space wrap style={{ marginBottom: 10 }}>
            <Badge count={shown.length} showZero color="#1677ff" overflowCount={999} />
            <Text strong>{t('news.results')}</Text>
            <Select
              mode="multiple"
              allowClear
              size="small"
              style={{ minWidth: 220 }}
              placeholder={t('news.filter_kind')}
              value={kindFilter}
              onChange={setKindFilter}
              options={Object.keys(byKind).map((k) => ({
                value: k,
                label: t(`glbadmin.feeds.kind_${k}`, { defaultValue: k }),
              }))}
            />
            <Tooltip title={t('news.add_hint')}>
              <Button size="small" icon={<PlusOutlined />} onClick={addToCase}
                      disabled={!query.trim()}>
                {t('news.add_to_case')}
              </Button>
            </Tooltip>
          </Space>

          {notes.map((n, i) => (
            <Alert key={i} type="info" showIcon style={{ marginBottom: 8 }}
                   message={n.replace('[note] ', '')} />
          ))}

          {shown.length === 0 ? (
            <Empty description={t('news.no_hits')} />
          ) : (
            <List
              itemLayout="vertical"
              dataSource={shown}
              pagination={shown.length > 20 ? { pageSize: 20 } : false}
              renderItem={(a) => (
                <List.Item
                  key={(a.url || a.title) as string}
                  extra={a.published ? <Text type="secondary">{a.published}</Text> : null}
                >
                  <List.Item.Meta
                    title={
                      a.url
                        ? <a href={a.url} target="_blank" rel="noreferrer">
                            {a.title} <LinkOutlined />
                          </a>
                        : a.title
                    }
                    description={
                      <Space size={6} wrap>
                        <Tag color={KIND_COLOR[a.source_kind] || 'default'}>
                          {t(`glbadmin.feeds.kind_${a.source_kind}`, { defaultValue: a.source_kind })}
                        </Tag>
                        <Text type="secondary">{a.source_name}</Text>
                        {a.matched && a.matched.length > 1 && (
                          <Tooltip title={a.matched.join(' · ')}>
                            <Tag>{t('news.matched_n', { count: a.matched.length })}</Tag>
                          </Tooltip>
                        )}
                      </Space>
                    }
                  />
                  {(a.match_context || a.summary) && (
                    <Text type="secondary">
                      {highlight(
                        a.match_context || a.summary || '',
                        [...parseTerms(query), ...(a.matched_terms || [])],
                      )}
                    </Text>
                  )}
                </List.Item>
              )}
            />
          )}
        </div>
      )}
    </div>
  )
}

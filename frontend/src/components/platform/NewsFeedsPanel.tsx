import { useEffect, useMemo, useState } from 'react'
import {
  Table, Button, Input, Select, Switch, Space, Alert, Tag, Popconfirm,
  Typography, Collapse, Badge, Tooltip, InputNumber, Divider, message,
  Card, Statistic,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, ExperimentOutlined, SearchOutlined,
  CheckCircleTwoTone, CloseCircleTwoTone, ReloadOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import {
  newsFeedsApi, NewsFeed, FeedTestResult, NewsSettings, FeedHealth,
  newsHarvesterApi, HarvesterStatus,
} from '../../api/client'

const { Text, Paragraph } = Typography

/**
 * Operator-maintained RSS/news feed list for module-news.
 *
 * Grouped by source kind rather than shown as one flat table: with ~60
 * feeds a single list makes it impossible to see coverage per category or
 * to add a source to the right place. Each group has its own counter, its
 * own "add" button (which pre-sets the kind) and a "test all" action.
 *
 * Stored operator-globally in the license-server, effective on the next
 * search — no rebuild, no restart. An empty list is a valid state: the
 * module then falls back to its own verified defaults, so clearing this
 * table degrades to "the built-in sources", not to "no news search".
 *
 * The Test button is not decoration. The common failure when adding a feed
 * is a URL that answers HTTP 200 with an HTML page: it looks fine and
 * silently contributes nothing to every future search. The probe reports
 * the entry COUNT so that case is visible immediately.
 */

/** Bytes as an operator reads them. Binary units, because that is what
 *  `df` and every disk figure on the host reports. */
function fmtBytes(n: number | null | undefined): string {
  if (!n || n < 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1 }
  return `${v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`
}

const KIND_COLOR: Record<string, string> = {
  authority: 'blue', police: 'geekblue', media: 'orange',
  tech: 'cyan', cyber: 'purple', other: 'default',
}
const KIND_ORDER = ['authority', 'police', 'media', 'tech', 'cyber', 'other']

export default function NewsFeedsPanel() {
  const { t } = useTranslation()
  const [feeds, setFeeds] = useState<NewsFeed[]>([])
  const [kinds, setKinds] = useState<string[]>(KIND_ORDER)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [filter, setFilter] = useState('')
  const [tests, setTests] = useState<Record<string, FeedTestResult | 'running'>>({})
  const [cfg, setCfg] = useState<NewsSettings | null>(null)
  const [placeholder, setPlaceholder] = useState('{{max}}')
  const [cfgDirty, setCfgDirty] = useState(false)
  const [health, setHealth] = useState<Record<string, FeedHealth>>({})
  const [harvest, setHarvest] = useState<HarvesterStatus | null>(null)
  const [hDirty, setHDirty] = useState(false)
  const [hSaving, setHSaving] = useState(false)
  const [running, setRunning] = useState(false)

  const loadHarvest = () => newsHarvesterApi.get().then(setHarvest).catch(() => {})

  useEffect(() => {
    newsFeedsApi.list()
      .then((d) => {
        setFeeds(d.feeds || [])
        if (d.kinds?.length) setKinds(d.kinds)
        if (d.settings) setCfg(d.settings)
        if (d.max_placeholder) setPlaceholder(d.max_placeholder)
        setHealth(d.health || {})
      })
      .catch(() => message.error(t('glbadmin.feeds.load_failed')))
      .finally(() => setLoading(false))
    loadHarvest()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /** Patch one harvest-schedule field and mark it unsaved. */
  const setHs = (patch: Partial<HarvesterStatus['settings']>) => {
    if (!harvest) return
    setHarvest({ ...harvest, settings: { ...harvest.settings, ...patch } })
    setHDirty(true)
  }

  const saveHarvest = async () => {
    if (!harvest) return
    setHSaving(true)
    try {
      const res = await newsHarvesterApi.saveSettings(harvest.settings)
      setHarvest({ ...harvest, settings: res.settings }); setHDirty(false)
      message.success(t('glbadmin.harvest.saved'))
    } catch {
      message.error(t('glbadmin.harvest.save_failed'))
    } finally { setHSaving(false) }
  }

  const runHarvest = async () => {
    setRunning(true)
    try {
      const res = await newsHarvesterApi.run()
      const s = res.summary || {}
      message.success(t('glbadmin.harvest.run_done',
        { inserted: s.inserted ?? 0, fetched: s.fetched ?? 0 }))
      await loadHarvest()
    } catch {
      message.error(t('glbadmin.harvest.run_failed'))
    } finally { setRunning(false) }
  }

  /** Rows are addressed by feed id — index would shift as groups filter. */
  const patch = (id: string, changes: Partial<NewsFeed>) => {
    setFeeds((prev) => prev.map((f) => (f.id === id ? { ...f, ...changes } : f)))
    setDirty(true)
  }
  const remove = (id: string) => {
    setFeeds((prev) => prev.filter((f) => f.id !== id))
    setDirty(true)
  }
  const add = (kind: string) => {
    const id = `new-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
    setFeeds((prev) => [...prev, { id, name: '', url: '', kind, lang: 'de', enabled: true }])
    setDirty(true)
  }

  const testOne = async (f: NewsFeed) => {
    if (!f.url?.trim() || !f.id) return
    setTests((p) => ({ ...p, [f.id!]: 'running' }))
    try {
      const res = await newsFeedsApi.test(f.url.trim())
      setTests((p) => ({ ...p, [f.id!]: res }))
    } catch {
      setTests((p) => ({ ...p, [f.id!]: { ok: false, detail: 'request failed' } }))
    }
  }

  /** Sequentially, not in parallel: these are public bodies and a burst of
   *  60 requests from one IP is the fastest way to get rate-limited. */
  const testGroup = async (rows: NewsFeed[]) => {
    for (const f of rows) await testOne(f)
  }

  const saveCfg = async () => {
    if (!cfg) return
    try {
      const res = await newsFeedsApi.saveSettings(cfg)
      setCfg(res.settings); setCfgDirty(false)
      message.success(t('glbadmin.feeds.cfg_saved'))
    } catch { message.error(t('glbadmin.feeds.save_failed')) }
  }

  const save = async () => {
    if (feeds.some((f) => !f.url.trim())) {
      message.error(t('glbadmin.feeds.url_required')); return
    }
    setSaving(true)
    try {
      const res = await newsFeedsApi.save(feeds)
      setFeeds(res.feeds || [])
      setDirty(false)
      message.success(t('glbadmin.feeds.saved'))
    } catch {
      message.error(t('glbadmin.feeds.save_failed'))
    } finally { setSaving(false) }
  }

  /** Compact "3 d" / "5 h" / "12 min" for how long something has been down. */
  const since = (ts?: number | null) => {
    if (!ts) return ''
    const mins = Math.max(1, Math.round((Date.now() / 1000 - ts) / 60))
    if (mins < 60) return t('glbadmin.feeds.since_min', { n: mins })
    if (mins < 1440) return t('glbadmin.feeds.since_hour', { n: Math.round(mins / 60) })
    return t('glbadmin.feeds.since_day', { n: Math.round(mins / 1440) })
  }

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return feeds
    return feeds.filter((f) =>
      f.name.toLowerCase().includes(q) || f.url.toLowerCase().includes(q))
  }, [feeds, filter])

  const columns = [
    {
      title: t('glbadmin.feeds.col_enabled'), width: 80,
      render: (_: any, r: NewsFeed) => (
        <Switch aria-label={t('a11y.toggle_row_enabled')} size="small" checked={r.enabled}
                onChange={(v) => patch(r.id!, { enabled: v })} />
      ),
    },
    {
      title: t('glbadmin.feeds.col_name'), width: 210,
      render: (_: any, r: NewsFeed) => (
        <Input size="small" value={r.name} placeholder={t('glbadmin.feeds.name_ph')}
               onChange={(e) => patch(r.id!, { name: e.target.value })} />
      ),
    },
    {
      title: t('glbadmin.feeds.col_url'),
      render: (_: any, r: NewsFeed) => (
        <Input size="small" value={r.url} placeholder="https://…/rss"
               onChange={(e) => patch(r.id!, { url: e.target.value })} />
      ),
    },
    {
      title: t('glbadmin.feeds.col_kind'), width: 125,
      render: (_: any, r: NewsFeed) => (
        <Select aria-label={t('a11y.feed_kind')} size="small" style={{ width: '100%' }} value={r.kind}
                onChange={(v) => patch(r.id!, { kind: v })}
                options={kinds.map((k) => ({
                  value: k, label: t(`glbadmin.feeds.kind_${k}`, { defaultValue: k }),
                }))} />
      ),
    },
    {
      title: t('glbadmin.feeds.col_lang'), width: 82,
      render: (_: any, r: NewsFeed) => (
        <Select aria-label={t('a11y.feed_language')} size="small" style={{ width: '100%' }} value={r.lang}
                onChange={(v) => patch(r.id!, { lang: v })}
                options={['de', 'fr', 'it', 'en'].map((l) => ({ value: l, label: l.toUpperCase() }))} />
      ),
    },
    {
      // Health from real searches — distinct from the manual Test button,
      // which only reflects the moment it was pressed.
      title: t('glbadmin.feeds.col_status'), width: 150,
      render: (_: any, r: NewsFeed) => {
        const h = health[r.url]
        if (!h || (!h.last_ok && !h.last_error)) {
          return <Text type="secondary" style={{ fontSize: 12 }}>—</Text>
        }
        if (h.failing_since) {
          return (
            <Tooltip title={`${h.error || ''} · ${h.fails}×`}>
              <Tag color="red" style={{ marginInlineEnd: 0 }}>
                {t('glbadmin.feeds.failing_since', { since: since(h.failing_since) })}
              </Tag>
            </Tooltip>
          )
        }
        return (
          <Tooltip title={t('glbadmin.feeds.last_ok_at', { since: since(h.last_ok) })}>
            <Tag color="green" style={{ marginInlineEnd: 0 }}>
              {h.entries ? t('glbadmin.feeds.ok_entries', { n: h.entries }) : 'OK'}
            </Tag>
          </Tooltip>
        )
      },
    },
    {
      title: t('glbadmin.feeds.col_test'), width: 172,
      render: (_: any, r: NewsFeed) => {
        const res = tests[r.id || '']
        return (
          <Space size={4}>
            <Button aria-label={t('a11y.test_feed')} size="small" icon={<ExperimentOutlined />}
                    loading={res === 'running'} onClick={() => testOne(r)} />
            {res && res !== 'running' && (
              res.ok
                ? <Tag color="green" icon={<CheckCircleTwoTone twoToneColor="#52c41a" />}>
                    {res.entries}
                  </Tag>
                : <Tooltip title={res.detail}>
                    <Tag color="red" icon={<CloseCircleTwoTone twoToneColor="#ff4d4f" />}>
                      {(res.detail || '').slice(0, 16)}
                    </Tag>
                  </Tooltip>
            )}
          </Space>
        )
      },
    },
    {
      title: '', width: 44,
      render: (_: any, r: NewsFeed) => (
        <Popconfirm title={t('glbadmin.feeds.confirm_delete')} onConfirm={() => remove(r.id!)}>
          <Button aria-label={t('a11y.delete_row')} size="small" danger type="text" icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ]

  const groups = kinds.map((kind) => {
    const rows = visible.filter((f) => f.kind === kind)
    const total = feeds.filter((f) => f.kind === kind)
    const active = total.filter((f) => f.enabled).length
    const failed = total.filter((f) => {
      if (health[f.url]?.failing_since) return true
      const r = tests[f.id || '']
      return r && r !== 'running' && !r.ok
    }).length
    return { kind, rows, total: total.length, active, failed }
  })

  return (
    <div>
      <Paragraph type="secondary">{t('glbadmin.feeds.intro')}</Paragraph>

      {/* Background harvester: schedule + article stats + manual run.
          The cache is what makes analyst searches fast and stops the
          authority feeds from rate-limiting us. */}
      {harvest && (
        <Card
          size="small"
          style={{ marginBottom: 14 }}
          title={t('glbadmin.harvest.title')}
          extra={
            <Tooltip title={t('glbadmin.harvest.run_hint')}>
              <Button type="primary" icon={<ReloadOutlined />} loading={running}
                      onClick={runHarvest}>
                {t('glbadmin.harvest.run')}
              </Button>
            </Tooltip>
          }
        >
          <Space size={40} wrap style={{ marginBottom: 12 }}>
            <Statistic title={t('glbadmin.harvest.stat_articles')}
                       value={harvest.stats.total_articles} />
            <Statistic title={t('glbadmin.harvest.stat_feeds')}
                       value={harvest.stats.feeds_enabled} />
            <Statistic title={t('glbadmin.harvest.stat_due')}
                       value={harvest.stats.feeds_due} />
            <Statistic title={t('glbadmin.harvest.stat_last')}
                       value={harvest.stats.last_harvest
                         ? since(harvest.stats.last_harvest)
                         : t('glbadmin.harvest.never')} />
          </Space>

          {/* Disk footprint. The cache has no retention rule, so the only
              thing standing between it and a full disk is somebody seeing
              the number — which is why the projection sits next to it and
              says how long it actually watched. */}
          {harvest.storage && (
            <div style={{ marginBottom: 12 }}>
              <Space size={40} wrap>
                <Statistic
                  title={t('glbadmin.harvest.stat_storage')}
                  value={fmtBytes(harvest.storage.bytes)}
                />
                <Statistic
                  title={t('glbadmin.harvest.stat_growth')}
                  value={harvest.storage.projected_bytes_per_month
                    ? t('glbadmin.harvest.per_month',
                        { size: fmtBytes(harvest.storage.projected_bytes_per_month) })
                    : t('glbadmin.harvest.growth_unknown')}
                  valueStyle={{ fontSize: 20 }}
                />
                <Statistic
                  title={t('glbadmin.harvest.stat_per_article')}
                  value={fmtBytes(harvest.storage.bytes_per_article)}
                  valueStyle={{ fontSize: 20 }}
                />
              </Space>
              <div style={{ marginTop: 6 }}>
                <Space wrap size={6}>
                  {harvest.storage.per_table.map((tb) => (
                    <Tooltip key={tb.table}
                             title={t('glbadmin.harvest.table_split', {
                               heap: fmtBytes(tb.heap_bytes),
                               index: fmtBytes(tb.index_bytes),
                             })}>
                      <Tag>{tb.table}: {fmtBytes(tb.bytes)}</Tag>
                    </Tooltip>
                  ))}
                  <Tag color="blue">
                    {t('glbadmin.harvest.added_recent', {
                      d7: harvest.storage.added_7d.toLocaleString(),
                      d30: harvest.storage.added_30d.toLocaleString(),
                    })}
                  </Tag>
                  {harvest.storage.retention_days === null && (
                    <Tooltip title={t('glbadmin.harvest.no_retention_hint')}>
                      <Tag color="orange">{t('glbadmin.harvest.no_retention')}</Tag>
                    </Tooltip>
                  )}
                  {harvest.storage.observed_days < 30 && (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {t('glbadmin.harvest.observed',
                         { days: harvest.storage.observed_days })}
                    </Text>
                  )}
                </Space>
              </div>
            </div>
          )}

          {harvest.stats.per_kind.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <Space wrap size={6}>
                {harvest.stats.per_kind.map((pk) => (
                  <Tag key={pk.kind} color={KIND_COLOR[pk.kind] || 'default'}>
                    {t(`glbadmin.feeds.kind_${pk.kind}`, { defaultValue: pk.kind })}
                    {': '}{pk.count.toLocaleString()}
                  </Tag>
                ))}
              </Space>
            </div>
          )}

          <Divider style={{ margin: '4px 0 12px' }} />

          <Space wrap size={20} align="start">
            <div>
              <Text strong style={{ display: 'block', marginBottom: 2 }}>
                {t('glbadmin.harvest.authority_interval')}
              </Text>
              <InputNumber aria-label={t('a11y.interval_authority')} min={5} max={1440} step={5} addonAfter="min"
                value={harvest.settings.authority_interval_min}
                onChange={(v) => setHs({ authority_interval_min: Number(v) || 60 })} />
              <div><Text type="secondary" style={{ fontSize: 12 }}>
                {t('glbadmin.harvest.authority_hint')}
              </Text></div>
            </div>
            <div>
              <Text strong style={{ display: 'block', marginBottom: 2 }}>
                {t('glbadmin.harvest.other_interval')}
              </Text>
              <InputNumber aria-label={t('a11y.interval_other')} min={5} max={1440} step={5} addonAfter="min"
                value={harvest.settings.other_interval_min}
                onChange={(v) => setHs({ other_interval_min: Number(v) || 30 })} />
              <div><Text type="secondary" style={{ fontSize: 12 }}>
                {t('glbadmin.harvest.other_hint')}
              </Text></div>
            </div>
            <div>
              <Text strong style={{ display: 'block', marginBottom: 2 }}>
                {t('glbadmin.harvest.enabled')}
              </Text>
              <Switch aria-label={t('a11y.toggle_harvest')} checked={harvest.settings.enabled}
                      onChange={(v) => setHs({ enabled: v })} />
              <div><Text type="secondary" style={{ fontSize: 12 }}>
                {t('glbadmin.harvest.enabled_hint')}
              </Text></div>
            </div>
            <Button type="primary" onClick={saveHarvest}
                    loading={hSaving} disabled={!hDirty}>
              {t('glbadmin.harvest.save')}
            </Button>
          </Space>
        </Card>
      )}

      {/* Search limits. Kept next to the feeds because they only make
          sense together: how much each feed delivers, and how much of it
          reaches the analyst. */}
      {cfg && (
        <div style={{ background: '#fafafa', border: '1px solid #f0f0f0',
                      borderRadius: 6, padding: '12px 14px', marginBottom: 14 }}>
          <Space wrap size={18} align="start">
            <div>
              <Text strong style={{ display: 'block', marginBottom: 2 }}>
                {t('glbadmin.feeds.cfg_entries')}
              </Text>
              <InputNumber aria-label={t('a11y.max_entries_per_feed')} min={10} max={1000} step={10} value={cfg.max_entries_per_feed}
                onChange={(v) => { setCfg({ ...cfg, max_entries_per_feed: Number(v) || 200 }); setCfgDirty(true) }} />
              <div><Text type="secondary" style={{ fontSize: 12 }}>
                {t('glbadmin.feeds.cfg_entries_hint', { ph: placeholder })}
              </Text></div>
            </div>
            <div>
              <Text strong style={{ display: 'block', marginBottom: 2 }}>
                {t('glbadmin.feeds.cfg_results')}
              </Text>
              <InputNumber aria-label={t('a11y.max_results')} min={5} max={500} step={5} value={cfg.max_results}
                onChange={(v) => { setCfg({ ...cfg, max_results: Number(v) || 60 }); setCfgDirty(true) }} />
              <div><Text type="secondary" style={{ fontSize: 12 }}>
                {t('glbadmin.feeds.cfg_results_hint')}
              </Text></div>
            </div>
            <div>
              <Text strong style={{ display: 'block', marginBottom: 2 }}>
                {t('glbadmin.feeds.cfg_age')}
              </Text>
              <InputNumber aria-label={t('a11y.max_age_days')} min={0} max={10000} step={30} value={cfg.max_age_days}
                onChange={(v) => { setCfg({ ...cfg, max_age_days: Number(v) || 0 }); setCfgDirty(true) }} />
              <div><Text type="secondary" style={{ fontSize: 12 }}>
                {t('glbadmin.feeds.cfg_age_hint')}
              </Text></div>
            </div>
            <Button type="primary" onClick={saveCfg} disabled={!cfgDirty}>
              {t('glbadmin.feeds.cfg_save')}
            </Button>
          </Space>
          <Divider style={{ margin: '12px 0 8px' }} />
          <Alert type="info" showIcon
                 message={t('glbadmin.feeds.howto_title')}
                 description={
                   <div style={{ fontSize: 13 }}>
                     <div>{t('glbadmin.feeds.howto_1')}</div>
                     <div>{t('glbadmin.feeds.howto_2')}</div>
                     <div>{t('glbadmin.feeds.howto_3', { ph: placeholder })}</div>
                     <div style={{ marginTop: 4, fontFamily: 'monospace', fontSize: 12,
                                   background: '#fff', padding: '4px 6px', borderRadius: 4,
                                   overflowX: 'auto', whiteSpace: 'nowrap' }}>
                       https://www.newsd.admin.ch/newsd/feeds/rss?lang=de&org-nr=408&…&end_index={placeholder}
                     </div>
                   </div>
                 } />
        </div>
      )}

      <Space wrap style={{ marginBottom: 12 }}>
        <Input
          allowClear
          prefix={<SearchOutlined style={{ color: '#bfbfbf' }} />}
          placeholder={t('glbadmin.feeds.filter_ph')}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          style={{ width: 280 }}
        />
        <Button type="primary" onClick={save} loading={saving} disabled={!dirty}>
          {t('glbadmin.feeds.save')}
        </Button>
        {dirty && <Text type="warning">{t('glbadmin.feeds.unsaved')}</Text>}
        <Text type="secondary">
          {t('glbadmin.feeds.total', { count: feeds.length })}
        </Text>
      </Space>

      {feeds.length === 0 && !loading && (
        <Alert type="info" showIcon style={{ marginBottom: 12 }}
               message={t('glbadmin.feeds.empty_title')}
               description={t('glbadmin.feeds.empty_desc')} />
      )}

      <Collapse
        defaultActiveKey={['authority', 'police']}
        items={groups.map((g) => ({
          key: g.kind,
          label: (
            <Space size={8}>
              <Tag color={KIND_COLOR[g.kind] || 'default'} style={{ marginInlineEnd: 0 }}>
                {t(`glbadmin.feeds.kind_${g.kind}`, { defaultValue: g.kind })}
              </Tag>
              <Badge count={g.total} showZero color="#8c8c8c" overflowCount={999} />
              {g.active !== g.total && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {t('glbadmin.feeds.n_active', { active: g.active, total: g.total })}
                </Text>
              )}
              {g.failed > 0 && (
                <Tag color="red">{t('glbadmin.feeds.n_failed', { count: g.failed })}</Tag>
              )}
            </Space>
          ),
          extra: (
            <Space size={4} onClick={(e) => e.stopPropagation()}>
              <Tooltip title={t('glbadmin.feeds.test_all_hint')}>
                <Button size="small" icon={<ExperimentOutlined />}
                        disabled={!g.rows.length}
                        onClick={() => testGroup(g.rows)}>
                  {t('glbadmin.feeds.test_all')}
                </Button>
              </Tooltip>
              <Button size="small" type="dashed" icon={<PlusOutlined />}
                      onClick={() => add(g.kind)}>
                {t('glbadmin.feeds.add_here')}
              </Button>
            </Space>
          ),
          children: (
            <Table
              rowKey={(r) => r.id || r.url}
              size="small"
              loading={loading}
              dataSource={g.rows}
              columns={columns as any}
              pagination={false}
              scroll={{ x: 880 }}
              locale={{ emptyText: t('glbadmin.feeds.group_empty') }}
            />
          ),
        }))}
      />
    </div>
  )
}

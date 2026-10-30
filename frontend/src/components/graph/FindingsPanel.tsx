import { useMemo, useState } from 'react'
import { graphApi } from '../../api/client'
import {
  Row, Col, Card, Collapse, List, Input, Button, Space, Tag, Empty, Spin,
  Typography, Tooltip, Badge, Segmented, Checkbox, message, Modal,
} from 'antd'
import {
  ApartmentOutlined, PartitionOutlined,
  UserOutlined, MailOutlined, GlobalOutlined, PhoneOutlined,
  EnvironmentOutlined, BankOutlined, SendOutlined, TagOutlined,
  ArrowRightOutlined, RightOutlined, LinkOutlined, SearchOutlined,
  AimOutlined, DeleteOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { NODE_COLORS } from './GraphView'
import NodeDetail from './NodeDetail'
import { displayLabel } from '../../utils/label'

const { Text } = Typography

interface Entity {
  id: string
  entity_type: string
  label: string
  data: Record<string, any>
  is_relevant?: boolean | null
  [k: string]: any
}
interface Edge { id: string; from_entity: string; to_entity: string; relation_type: string }
interface GraphData { entities: Entity[]; edges: Edge[] }

interface Props {
  data: GraphData | null
  loading: boolean
  /** Currently selected node (shared with the Graph tab). */
  selected: any
  onSelect: (node: any) => void
  onExpand?: (node: any) => void
  onAddMonitoring?: (node: any) => void
  onToggleRelevant?: (node: any) => void
  onDeleteEntity?: (node: any) => void
  /** Switch the parent to the Graph tab. */
  onOpenGraph?: () => void
  /** Open the advanced/pivot search ("Erweiterte Suche") from a finding. */
  onPivot?: (node: any) => void
  /** Needed for bulk triage — the endpoint is case-scoped. */
  caseId?: string
  /** Reload the graph after a bulk change. */
  onRefresh?: () => void
}

// One icon per entity-type family — a quick visual anchor next to the
// coloured dot. Anything unmapped falls back to a neutral tag icon.
const TYPE_ICON: Record<string, JSX.Element> = {
  person: <UserOutlined />,
  social_account: <UserOutlined />,
  username: <UserOutlined />,
  email_address: <MailOutlined />,
  email: <MailOutlined />,
  domain: <GlobalOutlined />,
  ip_address: <PartitionOutlined />,
  phone_number: <PhoneOutlined />,
  location: <EnvironmentOutlined />,
  organization: <BankOutlined />,
  telegram_channel: <SendOutlined />,
  telegram_message: <SendOutlined />,
  telegram_user: <SendOutlined />,
  telegram_media: <SendOutlined />,
  telegram_linked_channel: <SendOutlined />,
}

function typeIcon(t: string) {
  return TYPE_ICON[t] || <TagOutlined />
}

// Strip a leading "type:" prefix some labels carry (e.g. "breach:Foo",
// "btc_address:1A2b…") so we can build a clean target URL / query.
function bareLabel(e: Entity): string {
  const l = (e.label || '').trim()
  const pfx = `${e.entity_type}:`
  return l.startsWith(pfx) ? l.slice(pfx.length) : l
}

interface ResolvedLink { url: string; direct: boolean }

// First candidate that is a non-empty string and NOT an abbreviated
// value (some labels are truncated with an ellipsis, e.g.
// "btc:1A1zP1eP5Q…" — building an explorer URL from that would 404).
function firstClean(...cands: any[]): string | null {
  for (const c of cands) {
    if (typeof c === 'string') {
      const s = c.trim()
      if (s && !/[…]|\.\.\./.test(s)) return s
    }
  }
  return null
}

const searchLink = (v: string): ResolvedLink => ({
  url: `https://duckduckgo.com/?q=${encodeURIComponent(`"${v}"`)}`,
  direct: false,
})

// Give every finding a fast "open" target so the analyst can jump
// straight to the account/resource instead of copy-pasting.
//  - direct=true  → a canonical page for this exact entity (the account
//    profile, a blockchain explorer, the domain itself). Built from the
//    structured data field where possible, never from a truncated label.
//  - direct=false → a web search for the value, the universal fallback
//    for types without a canonical URL (usernames, names, phones …).
function resolveLink(e: Entity): ResolvedLink | null {
  const d = e.data || {}
  const stored = d.url || d.final_url || d.link || d.profile_url
  if (typeof stored === 'string' && /^https?:\/\//.test(stored)) {
    return { url: stored, direct: true }
  }
  // Passwords are not something you "open" or usefully web-search —
  // they're shown as copyable cleartext in the row instead.
  if (e.entity_type === 'password_fingerprint') return null

  switch (e.entity_type) {
    case 'domain':
    case 'dns_a': case 'dns_aaaa': case 'dns_mx':
    case 'dns_ns': case 'dns_txt': case 'dns_cname': {
      const v = firstClean(d.domain, d.host, bareLabel(e))
      if (v) return { url: `https://${v.replace(/^https?:\/\//, '')}`, direct: true }
      break
    }
    case 'ip': case 'ip_address': {
      const v = firstClean(d.ip, (d.key || '').replace(/^ip:/, ''), bareLabel(e))
      if (v) return { url: `https://ipinfo.io/${encodeURIComponent(v)}`, direct: true }
      break
    }
    case 'btc_address': {
      const v = firstClean(d.address, bareLabel(e))
      if (v) return { url: `https://www.blockchain.com/explorer/addresses/btc/${encodeURIComponent(v)}`, direct: true }
      break
    }
    case 'eth_address': {
      const v = firstClean(d.address, bareLabel(e))
      if (v) return { url: `https://etherscan.io/address/${encodeURIComponent(v)}`, direct: true }
      break
    }
    case 'telegram_channel': case 'telegram_linked_channel': case 'telegram_user': {
      const v = firstClean(d.handle, d.username, bareLabel(e))
      if (v) return { url: `https://t.me/${v.replace(/^@/, '')}`, direct: true }
      break
    }
  }
  // Universal fallback: quoted web search on a clean value.
  const v = firstClean(bareLabel(e))
  return v ? searchLink(v) : null
}
function dot(type: string) {
  return (
    <span
      style={{
        display: 'inline-block', width: 10, height: 10, borderRadius: '50%',
        background: NODE_COLORS[type] || NODE_COLORS.default, flex: '0 0 10px',
      }}
    />
  )
}

export default function FindingsPanel({
  caseId, onRefresh,
  data, loading, selected, onSelect, onExpand,
  onAddMonitoring, onToggleRelevant, onDeleteEntity, onOpenGraph, onPivot,
}: Props) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  // 'all' | 'relevant' — a quick way to cut the list down to flagged hits.
  const [scope, setScope] = useState<'all' | 'relevant'>('all')
  // Bulk triage. `is_relevant` drives BOTH the report's selection rule and
  // the relevance ranking, so a triage nobody finishes leaves the
  // investigative product resting on a half-made judgement — and the report
  // cannot tell that the filtering was incomplete. One at a time, on 609
  // entities, is a triage nobody finishes.
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [marking, setMarking] = useState(false)

  // Degree per node → "N connections" badge, computed once per data change.
  const degree = useMemo(() => {
    const m: Record<string, number> = {}
    for (const e of data?.edges || []) {
      m[e.from_entity] = (m[e.from_entity] || 0) + 1
      m[e.to_entity] = (m[e.to_entity] || 0) + 1
    }
    return m
  }, [data])

  // Neighbours of the selected node, for the "Relationships" card.
  const relations = useMemo(() => {
    if (!selected || !data) return []
    const byId = new Map(data.entities.map((e) => [e.id, e]))
    const out: Array<{ edgeId: string; relation: string; dir: 'out' | 'in'; other: Entity }> = []
    for (const e of data.edges) {
      if (e.from_entity === selected.id) {
        const other = byId.get(e.to_entity)
        if (other) out.push({ edgeId: e.id, relation: e.relation_type, dir: 'out', other })
      } else if (e.to_entity === selected.id) {
        const other = byId.get(e.from_entity)
        if (other) out.push({ edgeId: e.id, relation: e.relation_type, dir: 'in', other })
      }
    }
    return out
  }, [selected, data])

  // Group entities by type, apply the text filter + relevant scope, and
  // sort groups by size (biggest first) so the fullest buckets lead.
  const groups = useMemo(() => {
    const q = query.trim().toLowerCase()
    const buckets: Record<string, Entity[]> = {}
    for (const e of data?.entities || []) {
      if (scope === 'relevant' && e.is_relevant !== true) continue
      if (q && !(e.label || '').toLowerCase().includes(q) &&
          !(e.entity_type || '').toLowerCase().includes(q)) continue
      ;(buckets[e.entity_type] ||= []).push(e)
    }
    for (const k of Object.keys(buckets)) {
      buckets[k].sort((a, b) => {
        // Relevant first (the analyst's own judgement always wins), then by
        // the server-computed relevance score — the SAME ranking the report
        // uses, so the list and the PDF cannot disagree about what leads.
        // Degree alone put the loudest source on top; the score weighs
        // corroboration and source reliability above connectedness.
        const r = Number(!!b.is_relevant) - Number(!!a.is_relevant)
        if (r) return r
        const sc = (b.relevance_score || 0) - (a.relevance_score || 0)
        if (sc) return sc
        const d = (degree[b.id] || 0) - (degree[a.id] || 0)
        if (d) return d
        return (a.label || '').localeCompare(b.label || '')
      })
    }
    return Object.entries(buckets).sort((a, b) => b[1].length - a[1].length)
  }, [data, query, scope, degree])

  const mark = async (value: boolean | null) => {
    if (!caseId || !picked.size) return
    setMarking(true)
    try {
      const r = await graphApi.bulkRelevance(caseId, [...picked], value)
      // The response says how many rows actually changed — a partial result
      // must never be reported as a complete one.
      if (r.failed) {
        message.warning(t('findings.marked_partial', { n: r.changed, failed: r.failed }))
      } else {
        message.success(t('findings.marked', { n: r.changed }))
      }
      setPicked(new Set())
      onRefresh?.()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || t('findings.mark_failed'))
    } finally { setMarking(false) }
  }

  /**
   * Remove the picked findings from the case, with their edges.
   *
   * Deliberately separate from "als Rauschen markieren": that keeps the row
   * and the judgement can be revisited, this takes it out of the case. Both
   * are legitimate — a hundred Tor mirrors of one search page are clutter,
   * not a judgement worth preserving — but the analyst has to choose, so the
   * confirmation says plainly which one this is.
   */
  const removePicked = () => {
    if (!caseId || !picked.size) return
    const ids = [...picked]
    Modal.confirm({
      title: t('findings.remove_confirm_title', { count: ids.length }),
      content: t('findings.remove_confirm_body', { count: ids.length }),
      okText: t('findings.remove_ok', { count: ids.length }),
      okType: 'danger',
      cancelText: t('cases.cancel'),
      onOk: async () => {
        setMarking(true)
        try {
          const r = await graphApi.bulkDelete(caseId, ids)
          // "not_found" is not an error — a second click, or a colleague got
          // there first. Reported apart from what actually went, because a
          // partial result must never read as a complete one.
          if (r.not_found || r.invalid) {
            message.warning(t('findings.removed_partial', {
              n: r.deleted, skipped: (r.not_found || 0) + (r.invalid || 0) }))
          } else {
            message.success(t('findings.removed', { n: r.deleted }))
          }
          setPicked(new Set())
          onRefresh?.()
        } catch (e: any) {
          message.error(e?.response?.data?.detail || t('findings.remove_failed'))
        } finally { setMarking(false) }
      },
    })
  }

  const totalShown = useMemo(
    () => groups.reduce((n, [, list]) => n + list.length, 0),
    [groups],
  )
  const totalAll = data?.entities.length ?? 0

  if (loading && !data) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 64 }}>
        <Spin size="large" />
      </div>
    )
  }
  if (!loading && totalAll === 0) {
    return <Empty description={t('graph.no_data')} style={{ padding: 48 }} />
  }

  // Default-open the first (biggest) two groups so the panel isn't a wall
  // of collapsed headers on first view.
  const defaultOpen = groups.slice(0, 2).map(([type]) => type)

  return (
    <Row gutter={16}>
      {/* ── Left: grouped, collapsible findings list ── */}
      <Col xs={24} md={selected ? 14 : 24} lg={selected ? 15 : 24}>
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <Space style={{ width: '100%', justifyContent: 'space-between' }} wrap>
            <Space wrap>
              <Input.Search
                allowClear
                placeholder={t('findings.search_placeholder')}
                onChange={(e) => setQuery(e.target.value)}
                style={{ width: 240 }}
                size="small"
              />
              {picked.size > 0 && (
                <Space size={6}>
                  <Text strong style={{ fontSize: 12 }}>
                    {t('findings.picked', { count: picked.size })}
                  </Text>
                  <Button size="small" type="primary" loading={marking}
                          onClick={() => mark(true)}>
                    {t('findings.mark_relevant')}
                  </Button>
                  <Button size="small" danger loading={marking}
                          onClick={() => mark(false)}>
                    {t('findings.mark_noise')}
                  </Button>
                  {/* "I looked and I am not sure" is a legitimate third
                      state and has to stay reachable. */}
                  <Button size="small" loading={marking} onClick={() => mark(null)}>
                    {t('findings.mark_clear')}
                  </Button>
                  <Button size="small" danger type="primary" loading={marking}
                          icon={<DeleteOutlined />} onClick={removePicked}>
                    {t('findings.remove_picked')}
                  </Button>
                  <Button size="small" type="text" onClick={() => setPicked(new Set())}>
                    {t('findings.clear_pick')}
                  </Button>
                </Space>
              )}
              <Segmented aria-label={t('a11y.findings_scope')}
                size="small"
                value={scope}
                onChange={(v) => setScope(v as 'all' | 'relevant')}
                options={[
                  { label: t('findings.scope_all'), value: 'all' },
                  { label: <><ApartmentOutlined /> {t('findings.scope_relevant')}</>, value: 'relevant' },
                ]}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>
                {t('findings.count', { shown: totalShown, total: totalAll })}
              </Text>
            </Space>
            {onOpenGraph && (
              <Button size="small" icon={<ApartmentOutlined />} onClick={onOpenGraph}>
                {t('findings.open_graph')}
              </Button>
            )}
          </Space>

          {groups.length === 0 ? (
            <Empty description={t('findings.no_match')} style={{ padding: 32 }} />
          ) : (
            <Collapse
              defaultActiveKey={defaultOpen}
              items={groups.map(([type, list]) => ({
                key: type,
                label: (
                  <Space>
                    {/* Select the whole type in one click. Without it,
                        "remove every onion_service" meant ticking a hundred
                        boxes — which is why nobody did it. Counts only what
                        is CURRENTLY SHOWN, so a filter or the relevant-only
                        scope can never select rows that are out of sight. */}
                    {caseId && (
                      <Checkbox aria-label={t('a11y.select_all_findings')}
                        checked={list.every((e: any) => picked.has(e.id))}
                        indeterminate={
                          list.some((e: any) => picked.has(e.id))
                          && !list.every((e: any) => picked.has(e.id))}
                        onClick={(ev) => ev.stopPropagation()}
                        onChange={(ev) => setPicked((prev) => {
                          const n = new Set(prev)
                          list.forEach((e: any) =>
                            ev.target.checked ? n.add(e.id) : n.delete(e.id))
                          return n
                        })}
                      />
                    )}
                    {dot(type)}
                    <span style={{ color: '#8c8c8c' }}>{typeIcon(type)}</span>
                    <Text strong>{type}</Text>
                    <Badge count={list.length} showZero
                           style={{ backgroundColor: '#f0f0f0', color: '#595959' }} />
                  </Space>
                ),
                children: (
                  <List
                    size="small"
                    dataSource={list}
                    rowKey="id"
                    pagination={list.length > 25 ? { pageSize: 25, size: 'small' } : false}
                    renderItem={(e) => {
                      const isSel = selected?.id === e.id
                      const deg = degree[e.id] || 0
                      const link = resolveLink(e)
                      return (
                        <List.Item
                          onClick={() => onSelect(e)}
                          style={{
                            cursor: 'pointer', paddingLeft: 8, paddingRight: 8,
                            background: isSel ? '#e6f4ff' : undefined,
                            borderRadius: 6,
                          }}
                          actions={[
                            link ? (
                              <Tooltip
                                key="open"
                                title={link.direct ? t('findings.open_link') : t('findings.web_search')}
                              >
                                <Button aria-label={link.direct ? t('findings.open_link') : t('findings.web_search')}
                                  size="small"
                                  type={link.direct ? 'link' : 'text'}
                                  icon={link.direct ? <LinkOutlined /> : <SearchOutlined />}
                                  onClick={(ev) => {
                                    ev.stopPropagation()
                                    window.open(link.url, '_blank', 'noopener,noreferrer')
                                  }}
                                  style={link.direct ? undefined : { color: '#8c8c8c' }}
                                />
                              </Tooltip>
                            ) : null,
                            onPivot ? (
                              <Tooltip key="pivot" title={t('pivot.button')}>
                                <Button aria-label={t('pivot.button')}
                                  size="small" type="text" icon={<AimOutlined />}
                                  onClick={(ev) => { ev.stopPropagation(); onPivot(e) }}
                                />
                              </Tooltip>
                            ) : null,
                            e.admiralty ? (
                              <Tooltip key="rating" title={t('graph.admiralty_hint')}>
                                <Tag
                                  color={(e.corroborated_by?.length || 0) > 1 ? 'green' : undefined}
                                  style={{ marginInlineEnd: 0, fontSize: 11 }}
                                >
                                  {e.admiralty}
                                </Tag>
                              </Tooltip>
                            ) : null,
                            (e.corroborated_by?.length || 0) > 1 ? (
                              <Tooltip key="corr" title={e.corroborated_by.join(', ')}>
                                <span style={{ color: '#389e0d', fontSize: 12 }}>
                                  ✓ {e.corroborated_by.length}
                                </span>
                              </Tooltip>
                            ) : null,
                            <Tooltip title={t('findings.connections', { count: deg })} key="deg">
                              <span style={{ color: '#8c8c8c', fontSize: 12 }}>
                                <PartitionOutlined /> {deg}
                              </span>
                            </Tooltip>,
                            onExpand ? (
                              <Button
                                key="exp" size="small" type="link"
                                onClick={(ev) => { ev.stopPropagation(); onExpand(e) }}
                              >
                                {t('graph.ctx_expand')}
                              </Button>
                            ) : null,
                          ].filter(Boolean) as any}
                        >
                          <Space size={6} wrap>
                            {caseId && (
                              <Checkbox aria-label={t('a11y.select_finding')}
                                checked={picked.has(e.id)}
                                onClick={(ev) => ev.stopPropagation()}
                                onChange={(ev) => setPicked((prev) => {
                                  const n = new Set(prev)
                                  ev.target.checked ? n.add(e.id) : n.delete(e.id)
                                  return n
                                })}
                              />
                            )}
                            {onToggleRelevant && (
                              <Tooltip title={e.is_relevant ? t('graph_map.remove') : t('graph_map.add')}>
                                <Button aria-label={t('a11y.toggle_relevant')}
                                  size="small"
                                  type={e.is_relevant ? 'primary' : 'default'}
                                  ghost={!!e.is_relevant}
                                  icon={<ApartmentOutlined />}
                                  onClick={(ev) => { ev.stopPropagation(); onToggleRelevant(e) }}
                                >
                                  {e.is_relevant ? t('graph_map.on_short') : t('graph_map.add_short')}
                                </Button>
                              </Tooltip>
                            )}
                            <Text style={{ wordBreak: 'break-all' }}>
                              {displayLabel(e.entity_type, e.label) || <Text type="secondary">—</Text>}
                            </Text>
                          </Space>
                        </List.Item>
                      )
                    }}
                  />
                ),
              }))}
            />
          )}
        </Space>
      </Col>

      {/* ── Right: detail card + relationships for the selected finding.
             Sticky so it follows the page scroll — clicking a finding far
             down the list keeps the detail in view instead of jumping to
             the top of the column. ── */}
      {selected && (
        <Col xs={24} md={10} lg={9}>
          <Space
            direction="vertical"
            style={{ width: '100%', position: 'sticky', top: 16 }}
            size={12}
          >
            <NodeDetail
              node={selected}
              onMonitor={(n) => onAddMonitoring?.(n)}
              onToggleRelevant={onToggleRelevant}
              onDelete={onDeleteEntity}
              onPivot={onPivot}
            />
            <Card
              size="small"
              title={
                <Space>
                  <PartitionOutlined />
                  {t('findings.relationships')}
                  <Badge count={relations.length} showZero
                         style={{ backgroundColor: '#f0f0f0', color: '#595959' }} />
                </Space>
              }
            >
              {relations.length === 0 ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
                       description={t('findings.no_relationships')} />
              ) : (
                <List
                  size="small"
                  dataSource={relations}
                  rowKey="edgeId"
                  renderItem={(r) => (
                    <List.Item
                      onClick={() => onSelect(r.other)}
                      style={{ cursor: 'pointer', borderRadius: 6, paddingLeft: 4, paddingRight: 4 }}
                    >
                      <Space size={6} style={{ width: '100%' }} align="start">
                        {r.dir === 'out'
                          ? <ArrowRightOutlined style={{ color: '#bfbfbf', marginTop: 4 }} />
                          : <RightOutlined rotate={180} style={{ color: '#bfbfbf', marginTop: 4 }} />}
                        <div style={{ minWidth: 0 }}>
                          <Tag color="default" style={{ marginBottom: 2 }}>{r.relation}</Tag>
                          <div>
                            <Space size={4}>
                              {dot(r.other.entity_type)}
                              <Text style={{ wordBreak: 'break-all' }}>
                                {displayLabel(r.other.entity_type, r.other.label) || r.other.id}
                              </Text>
                            </Space>
                          </div>
                        </div>
                      </Space>
                    </List.Item>
                  )}
                />
              )}
            </Card>
          </Space>
        </Col>
      )}
    </Row>
  )
}

import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import {
  Drawer, Input, Select, Checkbox, Button, Space, Tag, Badge, Collapse,
  List, Empty, Spin, Typography, Alert, message, Tooltip, Segmented,
} from 'antd'
import {
  SearchOutlined, PlusOutlined, PartitionOutlined, AimOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { searchApi, entityApi } from '../../api/client'
import { NODE_COLORS } from '../graph/GraphView'
import { displayLabel } from '../../utils/label'
import { pivotSeed, type PivotSeed } from '../../utils/pivot'
import { queryTypeGroupedOptions, availableQueryTypes } from '../../utils/queryTypes'

const { Text } = Typography

interface Props {
  open: boolean
  caseId: string
  seed: PivotSeed | null
  /** Entity ids already in the case graph — used to badge/skip existing. */
  existingIds: Set<string>
  onClose: () => void
  /** Called after a successful commit so the parent can refresh the graph. */
  onCommitted: () => void
}

/** How deep a pivot searches — a cost choice, not a source choice.
 *
 * Measured on a username pivot (15 matching tools) before settling on three
 * levels rather than two: dropping only the `slow` tools still took **180 s**,
 * because eleven `medium` tools remain and several of them run 30-60 s. A
 * two-level switch would therefore have labelled three minutes as "quick".
 *
 *   fast     — only tools their module declares `fast`: seconds
 *   standard — + `medium`: a minute or three
 *   full     — everything, including the multi-probe sweeps
 */
type Depth = 'fast' | 'standard' | 'full'

const _CLASS_RANK: Record<string, number> = { fast: 0, medium: 1, slow: 2 }
const _DEPTH_LIMIT: Record<Depth, number> = { fast: 0, standard: 1, full: 2 }
const _DEPTHS: Depth[] = ['fast', 'standard', 'full']

function dot(type: string) {
  return (
    <span style={{
      display: 'inline-block', width: 10, height: 10, borderRadius: '50%',
      background: NODE_COLORS[type] || NODE_COLORS.default, flex: '0 0 10px',
    }} />
  )
}

export default function PivotDrawer({
  open, caseId, seed, existingIds, onClose, onCommitted,
}: Props) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [queryType, setQueryType] = useState('email')
  const [selModules, setSelModules] = useState<string[]>([])
  const [preview, setPreview] = useState<any | null>(null)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [scope, setScope] = useState<'all' | 'new'>('new')
  // How deep to search. Default "quick": every module, minus the tools their
  // own manifest declares as slow. See `toolPlan`.
  const [depth, setDepth] = useState<Depth>('fast')
  const [skipped, setSkipped] = useState<string[]>([])
  const [progress, setProgress] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [committing, setCommitting] = useState(false)
  // Holds the in-flight run so a new search, a cancel, or closing the drawer
  // can stop it — the backend cancels its whole module fan-out with it.
  const abortRef = useRef<AbortController | null>(null)

  // Closing the drawer must not leave a five-minute sweep running.
  useEffect(() => {
    if (!open) { abortRef.current?.abort(); abortRef.current = null }
  }, [open])
  useEffect(() => () => { abortRef.current?.abort() }, [])

  const { data: modulesData } = useQuery({
    queryKey: ['search-modules'], queryFn: searchApi.modules, staleTime: 60_000,
  })
  const manifests = modulesData?.manifests || {}
  const moduleList = useMemo(() => Object.values(manifests) as any[], [modulesData])

  const supportModules = useMemo(
    () => moduleList.filter((m) => m.tools.some((tl: any) => tl.query_types.includes(queryType))),
    [moduleList, queryType],
  )

  // Every module that can answer this selector type.
  //
  // This used to return `['leaks']` whenever leaks supported the type — which
  // is most of them (email, username, phone, domain, hash, password). A pivot
  // on a username therefore ran the breach sources and NOT sherlock,
  // whatsmyname, user_scanner, linkook or the 830k-handle index, while the
  // ordinary search form ran all of them. The pivot, the tool meant to be the
  // fast deep one, searched shallower than the main entry point and said
  // nothing about it — an investigator read the thin result as "nothing
  // there".
  //
  // The narrowing itself was not wrong, only invisible and module-shaped: it
  // was really about TIME. That is now expressed as a cost choice (see
  // `depth` below), so the same speed is available while nothing is hidden.
  const computeModules = useCallback((qt: string): string[] => (
    moduleList
      .filter((m) => m.tools.some((tl: any) => tl.query_types.includes(qt)))
      .map((m) => m.name)
  ), [moduleList])

  // Which tools to actually run, and which were left out.
  //
  // "quick" drops the tools their own module declares as `slow` — sweeps like
  // handle_sweep (~600 probes) or sherlock, which take one to three minutes.
  // Everything else runs. That keeps a pivot as fast as the old leaks-only
  // shortcut while searching far wider, and the skipped tools are named in
  // the UI and one click away.
  //
  // An empty list means "all" to the backend, so it is returned whenever
  // nothing is actually being dropped — including the case where EVERY
  // matching tool is slow, where quick has nothing cheaper to offer and
  // running nothing would be the wrong answer.
  const toolPlan = useCallback((qt: string, mods: string[], d: Depth) => {
    const matching = moduleList
      .filter((m) => mods.includes(m.name))
      .flatMap((m) => m.tools.filter((tl: any) => tl.query_types.includes(qt)))
    const limit = _DEPTH_LIMIT[d]
    // An undeclared tool counts as `medium` — the same honest default the
    // backend applies, so the count shown here matches what actually runs.
    const rank = (tl: any) => _CLASS_RANK[tl.latency_class ?? 'medium'] ?? 1
    const included = matching.filter((tl: any) => rank(tl) <= limit)
    const dropped = matching.filter((tl: any) => rank(tl) > limit)
    // A level that would run NOTHING is not a level — fall back to running
    // everything rather than returning an empty result the analyst would
    // read as "the sources know nothing about this selector".
    const usable = included.length ? included : matching
    return {
      // Empty means ALL to the backend, so send it whenever nothing is
      // actually being dropped.
      send: (dropped.length && included.length)
        ? included.map((tl: any) => tl.tool) : [],
      skipped: included.length ? dropped.map((tl: any) => tl.tool) : [],
      count: usable.length,
    }
  }, [moduleList])

  // How many tools each level would run, for the switch labels. Factual, not
  // an estimate: the analyst picks depth by what it costs.
  const depthCounts = useMemo(() => {
    const out = {} as Record<Depth, number>
    for (const d of _DEPTHS) out[d] = toolPlan(queryType, selModules, d).count
    return out
  }, [queryType, selModules, toolPlan])

  // Streaming run. Candidates appear as they are found and the tool table
  // fills live; before this the drawer showed a spinner for up to five
  // minutes and there was no way to stop a run started by mistake.
  const doPreview = useCallback(async (
    q: string, qt: string, mods: string[], d: Depth,
  ) => {
    if (!q.trim() || !mods.length) return
    const plan = toolPlan(qt, mods, d)
    // A new run supersedes the old one — and actually stops it server-side.
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl

    setLoading(true); setPreview(null); setChecked(new Set())
    setSkipped(plan.skipped); setProgress([])
    try {
      await searchApi.previewStream(
        { query: q.trim(), query_type: qt, case_id: caseId, modules: mods,
          tools: plan.send },
        (msg) => {
          if (msg.type === 'progress') {
            setProgress((prev) => {
              const next = [...prev]
              const i = next.findIndex((x) => x.tool === msg.tool)
              if (i >= 0) next[i] = msg; else next.push(msg)
              return next
            })
          } else if (msg.type === 'partial' || msg.type === 'done') {
            // Candidates only ever REPLACE — each message carries the full
            // ranked list, so a re-rank never leaves a stale row behind.
            setPreview((prev: any) => ({ ...(prev || {}), ...msg }))
          } else if (msg.type === 'error') {
            message.error(msg.detail || t('pivot.search_failed'))
          }
        },
        ctrl.signal,
      )
    } catch (e: any) {
      // An abort is a user action, not a failure.
      if (e?.name !== 'AbortError') {
        message.error(e?.message || t('pivot.search_failed'))
      }
    } finally {
      if (abortRef.current === ctrl) { abortRef.current = null; setLoading(false) }
    }
  }, [caseId, t, toolPlan])

  const cancelRun = () => {
    abortRef.current?.abort()
    abortRef.current = null
    setLoading(false)
  }

  // Drawer opened with a fresh seed → prefill + auto-run once manifests load.
  useEffect(() => {
    if (!open || !seed) return
    setQuery(seed.query)
    setQueryType(seed.type)
    const mods = computeModules(seed.type)
    setSelModules(mods)
    if (mods.length) doPreview(seed.query, seed.type, mods, depth)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, seed, modulesData])

  // Pivot from a result row: reseed + auto-run immediately.
  const pivotFrom = (entity: any) => {
    const s = pivotSeed(entity)
    if (!s) { message.info(t('pivot.not_pivotable')); return }
    setQuery(s.query); setQueryType(s.type)
    const mods = computeModules(s.type)
    setSelModules(mods)
    doPreview(s.query, s.type, mods, depth)
  }

  // Switching depth re-runs immediately: the switch exists to answer "and
  // what do the slow tools add?", and making the analyst press search again
  // just to see that is a step with no decision in it.
  const onDepthChange = (d: Depth) => {
    setDepth(d)
    if (preview || loading) doPreview(query, queryType, selModules, d)
  }

  const onTypeChange = (qt: string) => {
    setQueryType(qt)
    setSelModules(computeModules(qt))
  }

  // Group candidates by type; hide the ones already in the case unless the
  // scope toggle asks for all. Existing rows are never pre-checked.
  //
  // Ordering is by RELEVANCE, not by bucket size. Sorting groups by count put
  // the noisiest source on top — 300 single-source theharvester hits ahead of
  // the five subdomains two tools independently confirmed — which is the exact
  // problem `services/relevance.py` was written for. The score is computed
  // server-side (same function as the case graph and the report), so the
  // browser only sorts by it and never recomputes a second ranking.
  const groups = useMemo(() => {
    const buckets: Record<string, any[]> = {}
    for (const e of preview?.entities || []) {
      if (scope === 'new' && existingIds.has(e.id)) continue
      ;(buckets[e.entity_type] ||= []).push(e)
    }
    for (const k of Object.keys(buckets)) {
      buckets[k].sort((a, b) => {
        const sc = (b.relevance_score || 0) - (a.relevance_score || 0)
        if (sc) return sc
        return (a.label || '').localeCompare(b.label || '')
      })
    }
    // Group order: best candidate in the group first; size only breaks ties,
    // so a big bucket of weak hits can no longer bury a small strong one.
    return Object.entries(buckets).sort((a, b) => {
      const sc = (b[1][0]?.relevance_score || 0) - (a[1][0]?.relevance_score || 0)
      if (sc) return sc
      return b[1].length - a[1].length
    })
  }, [preview, scope, existingIds])

  const shownIds = useMemo(
    () => groups.flatMap(([, list]) => list.map((e) => e.id)),
    [groups],
  )
  const totalNew = useMemo(
    () => (preview?.entities || []).filter((e: any) => !existingIds.has(e.id)).length,
    [preview, existingIds],
  )

  const toggle = (id: string) => setChecked((prev) => {
    const n = new Set(prev)
    n.has(id) ? n.delete(id) : n.add(id)
    return n
  })
  const setGroup = (ids: string[], on: boolean) => setChecked((prev) => {
    const n = new Set(prev)
    ids.forEach((id) => (on ? n.add(id) : n.delete(id)))
    return n
  })
  const selectAllShown = (on: boolean) => setChecked(on ? new Set(shownIds) : new Set())

  const commit = async () => {
    const ents = (preview?.entities || []).filter((e: any) => checked.has(e.id))
    if (!ents.length) return
    const keep = new Set<string>([...checked, ...existingIds])
    // Keep only edges whose BOTH endpoints will exist (selected now or
    // already in the case) — the source node the user pivoted from stays
    // connected, orphan edges are dropped.
    const edges = (preview?.edges || []).filter(
      (e: any) => keep.has(e.from_entity) && keep.has(e.to_entity),
    )
    setCommitting(true)
    try {
      const r = await entityApi.commit(caseId, { entities: ents, edges })
      message.success(t('pivot.committed', { count: r.committed_entities }))
      onCommitted()
      setChecked(new Set())
    } catch (e: any) {
      message.error(e?.response?.data?.detail || t('pivot.commit_failed'))
    } finally {
      setCommitting(false)
    }
  }

  const checkedCount = checked.size

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={560}
      title={<Space><AimOutlined />{t('pivot.title')}</Space>}
      styles={{ body: { paddingTop: 12 } }}
      footer={
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Text type="secondary">
            {t('pivot.selected', { count: checkedCount })}
          </Text>
          <Button
            type="primary" icon={<PlusOutlined />}
            disabled={!checkedCount} loading={committing}
            onClick={commit}
          >
            {t('pivot.add_selected', { count: checkedCount })}
          </Button>
        </Space>
      }
    >
      {/* ── Query controls ── */}
      <Space direction="vertical" style={{ width: '100%' }} size={8}>
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onPressEnter={() => doPreview(query, queryType, selModules, depth)}
          placeholder={t('pivot.query_placeholder')}
          allowClear
        />
        <Space wrap>
          <Select aria-label={t('a11y.pivot_query_type')}
            value={queryType}
            style={{ width: 210 }}
            showSearch
            optionFilterProp="label"
            onChange={onTypeChange}
            options={queryTypeGroupedOptions(availableQueryTypes(moduleList), t)}
          />
          <Tooltip title={t('pivot.depth_hint')}>
            <Segmented aria-label={t('a11y.pivot_depth')}
              size="small"
              value={depth}
              onChange={(v) => onDepthChange(v as Depth)}
              options={_DEPTHS.map((d) => ({
                label: `${t(`pivot.depth_${d}`)} · ${depthCounts[d] ?? 0}`,
                value: d,
              }))}
            />
          </Tooltip>
          {loading ? (
            <Button danger onClick={cancelRun}>{t('pivot.cancel_run')}</Button>
          ) : (
            <Button
              type="primary" icon={<SearchOutlined />}
              disabled={!query.trim() || !selModules.length}
              onClick={() => doPreview(query, queryType, selModules, depth)}
            >
              {t('pivot.search')}
            </Button>
          )}
        </Space>
        {/* Name what was left out. A narrowed search that does not say it is
            narrowed reads as "there is nothing else" — the exact failure the
            old silent leaks-only shortcut produced. */}
        {skipped.length > 0 && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('pivot.depth_skipped', { count: skipped.length, tools: skipped.join(', ') })}{' '}
            <a onClick={() => onDepthChange(depth === 'fast' ? 'standard' : 'full')}>
              {t('pivot.depth_run_all')}
            </a>
          </Text>
        )}
        {supportModules.length === 0 ? (
          <Alert type="info" showIcon message={t('search.no_modules_for_type', { type: queryType })} />
        ) : (
          <Checkbox.Group
            value={selModules}
            onChange={(v) => setSelModules(v as string[])}
          >
            <Space wrap size={4}>
              {supportModules.map((m) => {
                const tools = m.tools
                  .filter((tl: any) => tl.query_types.includes(queryType))
                  .map((tl: any) => t(tl.label_key)).join(', ')
                return (
                  <Checkbox key={m.name} value={m.name}>
                    <Tooltip title={tools}>{t(m.label_key)}</Tooltip>
                  </Checkbox>
                )
              })}
            </Space>
          </Checkbox.Group>
        )}
      </Space>

      {/* ── Live tool status ──
          Replaces the blind spinner: the analyst sees WHICH source is still
          working and what each one returned, and can decide to stop. */}
      {progress.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <Space size={[4, 4]} wrap>
            {progress.map((p) => {
              const done = !['pending', 'running'].includes(p.status)
              const colour = p.status === 'error' ? 'error'
                : p.status === 'partial' ? 'warning'
                : done ? 'success' : 'processing'
              return (
                <Tooltip
                  key={p.tool}
                  title={(p.errors?.[0] || p.notes?.[0] || '') ||
                         (done ? `${p.duration}s` : t(`pivot.tool_${p.status}`, p.status))}
                >
                  <Tag color={colour} style={{ marginInlineEnd: 0, fontSize: 11 }}>
                    {p.tool}{done ? ` ${p.findings}` : ' …'}
                  </Tag>
                </Tooltip>
              )
            })}
          </Space>
        </div>
      )}

      {/* ── Results ── */}
      <div style={{ marginTop: 16 }}>
        {loading && !preview?.entities?.length ? (
          <div style={{ textAlign: 'center', padding: 48 }}><Spin /></div>
        ) : !preview ? (
          <Empty description={t('pivot.hint')} image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: 32 }} />
        ) : (
          <>
            <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 8 }} wrap>
              <Space size={8} wrap>
                <Segmented aria-label={t('a11y.pivot_scope')}
                  size="small"
                  value={scope}
                  onChange={(v) => setScope(v as 'all' | 'new')}
                  options={[
                    { label: t('pivot.scope_new', { count: totalNew }), value: 'new' },
                    { label: t('pivot.scope_all', { count: preview.entities.length }), value: 'all' },
                  ]}
                />
                <Button size="small" onClick={() => selectAllShown(true)} disabled={!shownIds.length}>
                  {t('pivot.select_all')}
                </Button>
                <Button size="small" onClick={() => selectAllShown(false)} disabled={!checkedCount}>
                  {t('pivot.clear')}
                </Button>
              </Space>
            </Space>

            {(preview.errors?.length || preview.notes?.length) ? (
              <Alert
                type={preview.errors?.length ? 'warning' : 'info'}
                showIcon style={{ marginBottom: 8 }}
                message={(preview.errors?.[0] || preview.notes?.[0] || '').slice(0, 140)}
              />
            ) : null}

            {groups.length === 0 ? (
              <Empty description={t('pivot.no_results')} style={{ padding: 24 }} />
            ) : (
              <Collapse
                defaultActiveKey={groups.slice(0, 3).map(([type]) => type)}
                items={groups.map(([type, list]) => {
                  const ids = list.map((e) => e.id)
                  const allOn = ids.every((id) => checked.has(id))
                  return {
                    key: type,
                    label: (
                      <Space onClick={(e) => e.stopPropagation()}>
                        <Checkbox aria-label={t('a11y.select_all_candidates')}
                          checked={allOn}
                          indeterminate={!allOn && ids.some((id) => checked.has(id))}
                          onChange={(e) => setGroup(ids, e.target.checked)}
                        />
                        {dot(type)}
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
                        pagination={list.length > 20 ? { pageSize: 20, size: 'small' } : false}
                        renderItem={(e: any) => {
                          const exists = existingIds.has(e.id)
                          return (
                            <List.Item
                              actions={[
                                // Same rating chips as the findings list
                                // (FindingsPanel) on purpose: one visual
                                // language for "how well is this supported",
                                // wherever the investigator looks at it.
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
                                <Tooltip key="pv" title={t('pivot.pivot_from')}>
                                  <Button aria-label={t('pivot.pivot_from')}
                                    size="small" type="text" icon={<AimOutlined />}
                                    onClick={() => pivotFrom(e)}
                                  />
                                </Tooltip>,
                              ].filter(Boolean) as any}
                            >
                              <Space size={8} align="start">
                                <Checkbox aria-label={t('a11y.select_candidate')}
                                  checked={checked.has(e.id)}
                                  onChange={() => toggle(e.id)}
                                />
                                <Text style={{ wordBreak: 'break-all' }}>
                                  {displayLabel(e.entity_type, e.label) || '—'}
                                </Text>
                                {exists && <Tag color="default">{t('pivot.in_case')}</Tag>}
                              </Space>
                            </List.Item>
                          )
                        }}
                      />
                    ),
                  }
                })}
              />
            )}
          </>
        )}
      </div>
    </Drawer>
  )
}

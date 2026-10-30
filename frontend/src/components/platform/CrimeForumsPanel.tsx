import { useEffect, useMemo, useState } from 'react'
import {
  Table, Button, Input, Select, Switch, Space, Alert, Tag, Popconfirm,
  Typography, Statistic, Card, Row, Col, Modal, Checkbox, message, Tooltip,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, CloudDownloadOutlined, ReloadOutlined,
  ThunderboltOutlined, SafetyCertificateOutlined, ClearOutlined,
  GlobalOutlined, LockOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import {
  crimeForumsApi, CrimeForum, forumIndexesApi, ForumIndexInfo,
} from '../../api/client'

const { Text, Paragraph } = Typography

/**
 * Operator-maintained crime-forum list for the forum hunt.
 *
 * Two things this screen has to make impossible to misunderstand:
 *
 *  1. The pool and the searched set are not the same list. Every hunt spends
 *     one search-engine query per ENABLED forum, so the counter is always
 *     "enabled / cap" and going over the cap is called out rather than left
 *     to be discovered when results quietly stop appearing.
 *  2. An EMPTY store does not mean "search nothing" — the module then falls
 *     back to its built-in list. A blank table would otherwise read as a
 *     broken panel, or worse, as a hunt that covers nothing.
 */
export default function CrimeForumsPanel() {
  const { t } = useTranslation()
  const [rows, setRows] = useState<CrimeForum[]>([])
  const [cap, setCap] = useState(40)
  const [builtin, setBuiltin] = useState(0)
  const [cats, setCats] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [filter, setFilter] = useState('')
  const [catFilter, setCatFilter] = useState<string | undefined>()
  const [onlyEnabled, setOnlyEnabled] = useState(false)
  const [addOpen, setAddOpen] = useState(false)
  const [bulkText, setBulkText] = useState('')
  const [bulkCat, setBulkCat] = useState('other')
  const [bulkEnabled, setBulkEnabled] = useState(true)
  const [busy, setBusy] = useState('')
  const [surfaces, setSurfaces] = useState({ clearnet: 0, onion: 0, enabled_clearnet: 0 })
  const [indexes, setIndexes] = useState<Record<string, ForumIndexInfo>>({})
  const [refreshDays, setRefreshDays] = useState(7)

  const load = async () => {
    setLoading(true)
    try {
      const d = await crimeForumsApi.list()
      setRows(d.forums || [])
      setCap(d.hunt_cap || 40)
      setBuiltin(d.defaults_count || 0)
      setCats(d.available_categories || [])
      setSurfaces({ clearnet: d.clearnet || 0, onion: d.onion || 0,
                    enabled_clearnet: d.enabled_clearnet || 0 })
    } catch (e: any) {
      message.error(e?.response?.data?.detail || t('forums.load_failed'))
    } finally { setLoading(false) }
    // Separate call, separate failure: the module being down must not blank
    // out the forum list, which is stored elsewhere entirely.
    try {
      const ix = await forumIndexesApi.status()
      setIndexes(ix.indexes || {})
      setRefreshDays(ix.refresh_days || 7)
    } catch { /* the card renders its own "unreachable" state */ }
  }
  useEffect(() => { load() }, [])

  // While a rebuild runs, poll — it takes minutes and a static "running"
  // that never resolves is indistinguishable from a hung one.
  const anyRunning = Object.values(indexes).some((i) => i.running)
  useEffect(() => {
    if (!anyRunning) return
    const h = setInterval(async () => {
      try {
        const ix = await forumIndexesApi.status()
        setIndexes(ix.indexes || {})
      } catch { /* keep the last known state */ }
    }, 15000)
    return () => clearInterval(h)
  }, [anyRunning])

  const enabledCount = rows.filter((r) => r.enabled).length
  const categories = useMemo(() => {
    const m: Record<string, number> = {}
    for (const r of rows) m[r.category] = (m[r.category] || 0) + 1
    return Object.entries(m).sort((a, b) => b[1] - a[1])
  }, [rows])

  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase()
    return rows.filter((r) =>
      (!onlyEnabled || r.enabled) &&
      (!catFilter || r.category === catFilter) &&
      (!q || r.domain.includes(q) || (r.note || '').toLowerCase().includes(q)))
  }, [rows, filter, catFilter, onlyEnabled])

  const persist = async (next: CrimeForum[]) => {
    setRows(next)
    setSaving(true)
    try {
      await crimeForumsApi.save(next)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || t('forums.save_failed'))
      load()   // never leave the screen showing something that was not stored
    } finally { setSaving(false) }
  }

  const toggle = (row: CrimeForum, on: boolean) =>
    persist(rows.map((r) => (r.id === row.id ? { ...r, enabled: on } : r)))

  const remove = (row: CrimeForum) => persist(rows.filter((r) => r.id !== row.id))

  const setManyEnabled = (on: boolean) => {
    const ids = new Set(shown.map((r) => r.id))
    persist(rows.map((r) => (ids.has(r.id) ? { ...r, enabled: on } : r)))
  }

  const seedDefaults = async () => {
    setLoading(true)
    try {
      const d = await crimeForumsApi.defaults(true)
      message.success(t('forums.seeded', { added: d.added, total: d.total }))
      await load()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || t('forums.save_failed'))
    } finally { setLoading(false) }
  }

  const doBulk = async () => {
    if (!bulkText.trim()) return
    setSaving(true)
    try {
      const d = await crimeForumsApi.bulk(bulkText, bulkCat, bulkEnabled)
      // `parsed` can be lower than the number of pasted lines: anything that
      // is not a plausible host name is dropped rather than stored as a forum
      // every search would then query for nothing. Say so.
      message.success(t('forums.bulk_added', { parsed: d.parsed, added: d.added }))
      setBulkText(''); setAddOpen(false)
      await load()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || t('forums.save_failed'))
    } finally { setSaving(false) }
  }

  const run = async (key: string, fn: () => Promise<any>, ok: (d: any) => string) => {
    setBusy(key)
    try { message.success(ok(await fn())); await load() }
    catch (e: any) { message.error(e?.response?.data?.detail || t('forums.save_failed')) }
    finally { setBusy('') }
  }

  const doCheck = (mode: 'index' | 'reach' | 'access' | 'both', recheck = false) =>
    run(recheck ? `${mode}-recheck` : mode,
    () => crimeForumsApi.check(mode, recheck),
    (d) => (mode === 'access'
      ? t('forums.checked_access', {
          n: d.checked,
          open: d.counts?.guest_open || 0,
          login: d.counts?.login_required || 0,
          blocked: d.counts?.blocked || 0,
        })
      : t('forums.checked', {
          n: d.checked,
          indexed: d.counts?.indexed || 0,
          notIndexed: d.counts?.not_indexed || 0,
          online: d.counts?.online || 0,
          blocked: d.counts?.blocked || 0,
        }))
      + (d.remaining ? ' · ' + t('forums.check_remaining', { n: d.remaining }) : ''))

  const doCleanup = (remove: boolean) => run('cleanup',
    () => crimeForumsApi.cleanup(remove),
    (d) => t(remove ? 'forums.cleaned_removed' : 'forums.cleaned_disabled',
             { n: d.affected }))

  // Only clearnet entries spend query budget; an onion costs nothing per
  // hunt. Counting both against the cap would tell the operator to disable
  // forums that are not the reason they are near the limit.
  const overCap = surfaces.enabled_clearnet > cap
  const empty = rows.length === 0
  const notIndexed = rows.filter((r) => r.index_status === 'not_indexed').length
  const noKey = rows.some((r) => r.index_status === 'no_key')
  // How many entries have never been asked the access question. Shown on the
  // button because that is the number an operator needs right after adding
  // forums: a new entry arrives unmeasured, and an empty column is not a
  // verdict. The server probes unchecked-first, so this is also exactly how
  // many are still ahead of the batch.
  const accessOpen = rows.filter((r) => !r.access_status).length
  // Entries whose access probe has never reached a verdict: never asked, or
  // asked and answered with a dropped circuit. These are the ones the
  // re-probe button targets — and the reason it exists. "Unchecked first"
  // treats a row that once timed out as measured, so without a second pass
  // those rows stay at `unreachable` forever even though almost all of them
  // are Tor-side accidents rather than dead boards.
  const INCONCLUSIVE = ['', 'unknown', 'unreachable', 'error', 'timeout']
  const inconclusive = rows.filter(
    (r) => INCONCLUSIVE.includes(r.access_status || '')).length

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Alert
        type={overCap ? 'warning' : 'info'}
        showIcon
        message={t('forums.headline', { total: rows.length, enabled: enabledCount, cap })}
        description={
          <Paragraph style={{ margin: 0 }}>
            {t('forums.explain')}
            {empty && <><br /><Text strong>{t('forums.empty_hint', { n: builtin })}</Text></>}
            {overCap && <><br /><Text strong type="danger">{t('forums.over_cap', { cap })}</Text></>}
          </Paragraph>
        }
      />

      <Row gutter={12}>
        <Col span={6}><Card size="small"><Statistic title={t('forums.stat_pool')} value={rows.length}
          suffix={<span style={{ fontSize: 12, color: '#888' }}>
            {t('forums.pool_split', { clearnet: surfaces.clearnet, onion: surfaces.onion })}
          </span>} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title={t('forums.stat_active')}
          value={surfaces.enabled_clearnet}
          valueStyle={{ color: overCap ? '#cf1322' : '#3f8600' }} suffix={`/ ${cap}`} /></Card></Col>
        <Col span={12}>
          <Card size="small">
            <Space wrap>
              <Button icon={<PlusOutlined />} type="primary" onClick={() => setAddOpen(true)}>
                {t('forums.add')}
              </Button>
              <Tooltip title={t('forums.ddcti_hint')}>
                <Button icon={<CloudDownloadOutlined />} loading={busy === 'ddcti'}
                        onClick={() => run('ddcti', () => crimeForumsApi.importDdcti(),
                          (d) => t('forums.ddcti_done', {
                            added: d.added, clearnet: d.clearnet,
                            onion: d.onion, total: d.total }))}>
                  {t('forums.ddcti')}
                </Button>
              </Tooltip>
              <Tooltip title={t('forums.seed_hint', { n: builtin })}>
                <Button icon={<CloudDownloadOutlined />} loading={loading} onClick={seedDefaults}>
                  {t('forums.seed')}
                </Button>
              </Tooltip>
              <Tooltip title={t('forums.check_index_hint')}>
                <Button icon={<SafetyCertificateOutlined />} loading={busy === 'index'}
                        onClick={() => doCheck('index')}>{t('forums.check_index')}</Button>
              </Tooltip>
              <Tooltip title={t('forums.check_reach_hint')}>
                <Button icon={<GlobalOutlined />} loading={busy === 'reach'}
                        onClick={() => doCheck('reach')}>{t('forums.check_reach')}</Button>
              </Tooltip>
              <Tooltip title={t('forums.check_access_hint')}>
                <Button icon={<LockOutlined />} loading={busy === 'access'}
                        onClick={() => doCheck('access')}>
                  {t('forums.check_access')}{accessOpen ? ` (${accessOpen})` : ''}
                </Button>
              </Tooltip>
              <Tooltip title={t('forums.recheck_hint')}>
                <Button icon={<ReloadOutlined />} loading={busy === 'access-recheck'}
                        disabled={!inconclusive}
                        onClick={() => doCheck('access', true)}>
                  {t('forums.recheck')}{inconclusive ? ` (${inconclusive})` : ''}
                </Button>
              </Tooltip>
              <Popconfirm title={t('forums.cleanup_confirm', { n: notIndexed })}
                          okText={t('forums.cleanup_disable')}
                          cancelText={t('forums.cleanup_remove')}
                          onConfirm={() => doCleanup(false)}
                          onCancel={() => notIndexed && doCleanup(true)}>
                <Button icon={<ClearOutlined />} loading={busy === 'cleanup'}
                        disabled={!notIndexed}>{t('forums.cleanup')} ({notIndexed})</Button>
              </Popconfirm>
              <Button aria-label={t('a11y.refresh')} icon={<ReloadOutlined />} onClick={load} loading={loading} />
            </Space>
          </Card>
        </Col>
      </Row>

      {noKey && <Alert type="warning" showIcon message={t('forums.no_key')} />}

      {/* The two reference indexes. Separate from the forum list above on
          purpose: that list decides WHERE the hunt dorks, these are local
          lookup tables it reads. Both had a refresh endpoint nobody ever
          called — the age column is the whole point of this card. */}
      <Card size="small" title={t('forums.idx_title')}
            extra={<Text type="secondary" style={{ fontSize: 12 }}>
              {t('forums.idx_schedule', { days: refreshDays })}
            </Text>}>
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          {/* Stated as an Alert, not as small print. Three different forum
              numbers live in this one tab — the 12-ish domains the hunt
              dorks, ~26 forums the handle index covers, ~289 boards in the
              directory — and nothing about their layout says they are
              unrelated. Somebody read them as one thing, which is a fair
              reading of what the screen showed. */}
          <Alert type="info" showIcon style={{ marginBottom: 4 }}
                 message={t('forums.idx_not_the_list')}
                 description={t('forums.idx_hint')} />
          <Paragraph type="secondary" style={{ margin: 0, fontSize: 12 }}>
            {t('forums.idx_sources')}
          </Paragraph>
          {Object.keys(indexes).length === 0 && (
            <Text type="secondary">{t('forums.idx_unreachable')}</Text>
          )}
          {Object.entries(indexes).map(([name, ix]) => (
            <Space key={name} wrap style={{ width: '100%' }}>
              <Text strong style={{ minWidth: 130, display: 'inline-block' }}>
                {t(`forums.idx_${name}`, { defaultValue: name })}
              </Text>
              {ix.error ? <Tag color="red">{ix.error}</Tag> : <>
                {ix.running
                  ? <Tag color="processing">{t('forums.idx_running')}</Tag>
                  : ix.age_days == null
                    ? <Tag color="default">{t('forums.idx_no_index')}</Tag>
                    : <Tag color={ix.due ? 'orange' : 'green'}>
                        {t('forums.idx_age', { days: ix.age_days })}
                      </Tag>}
                {/* Not cosmetic: this was the actual state for 20 days —
                    a refresh endpoint existed and had never run. */}
                {ix.using_baked_seed && !ix.running && (
                  <Tooltip title={t('forums.idx_baked_hint')}>
                    <Tag color="orange">{t('forums.idx_baked')}</Tag>
                  </Tooltip>
                )}
                {/* The count AND what it counts. A bare "862 637" next to a
                  12-row forum table invites exactly one reading, and it is
                  the wrong one. */}
              {ix.entries != null && (
                <Tag>{t(`forums.idx_unit_${name}`, {
                  n: ix.entries.toLocaleString(),
                  defaultValue: ix.entries.toLocaleString(),
                })}</Tag>
              )}
              {ix.forums != null && (
                <Tooltip title={t('forums.idx_covers_hint')}>
                  <Tag color="purple">{t('forums.idx_covers', { n: ix.forums })}</Tag>
                </Tooltip>
              )}
                {ix.last_error && <Tag color="red">{String(ix.last_error).slice(0, 60)}</Tag>}
                <Button size="small" icon={<ReloadOutlined />}
                        loading={busy === `idx-${name}`}
                        disabled={!!ix.running}
                        onClick={() => run(`idx-${name}`,
                          () => forumIndexesApi.refresh(name),
                          () => t('forums.idx_started'))}>
                  {t('forums.idx_refresh')}
                </Button>
              </>}
            </Space>
          ))}
        </Space>
      </Card>

      <Space wrap>
        <Input.Search allowClear placeholder={t('forums.filter')} style={{ width: 240 }}
                      onChange={(e) => setFilter(e.target.value)} />
        <Select allowClear style={{ width: 200 }} value={catFilter} onChange={setCatFilter}
                placeholder={t('forums.category')}
                options={categories.map(([c, n]) => ({ value: c, label: `${c} (${n})` }))} />
        <Checkbox checked={onlyEnabled} onChange={(e) => setOnlyEnabled(e.target.checked)}>
          {t('forums.only_active')}
        </Checkbox>
        <Tooltip title={t('forums.bulk_hint', { count: shown.length })}>
          <Button size="small" icon={<ThunderboltOutlined />} disabled={!shown.length}
                  onClick={() => setManyEnabled(true)}>{t('forums.enable_shown')}</Button>
        </Tooltip>
        <Button size="small" disabled={!shown.length} onClick={() => setManyEnabled(false)}>
          {t('forums.disable_shown')}
        </Button>
      </Space>

      <Table
        size="small"
        rowKey="id"
        loading={loading || saving}
        dataSource={shown}
        pagination={{ pageSize: 25, size: 'small', showSizeChanger: true }}
        columns={[
          {
            title: t('forums.col_active'), dataIndex: 'enabled', width: 90,
            render: (v: boolean, row: CrimeForum) => (
              <Switch aria-label={t('a11y.toggle_row_enabled')} size="small" checked={v} onChange={(on) => toggle(row, on)} />
            ),
          },
          {
            title: t('forums.col_domain'), dataIndex: 'domain',
            render: (d: string, row: CrimeForum) => (
              // No link. These are crime forums; opening one from the operator
              // console is a deliberate act, not something a stray click does.
              <Space size={6} wrap>
                {row.surface === 'onion' && (
                  <Tooltip title={t('forums.onion_hint')}>
                    <Tag color="purple">onion</Tag>
                  </Tooltip>
                )}
                <Text code copyable={{ text: d }}
                      style={row.surface === 'onion' ? { fontSize: 11 } : undefined}>
                  {row.surface === 'onion' ? `${d.slice(0, 16)}…onion` : d}
                </Text>
                {row.name && <Text type="secondary" style={{ fontSize: 12 }}>{row.name}</Text>}
              </Space>
            ),
          },
          {
            // The decisive column. A forum can be busy and alive and still
            // be worth nothing here, because the hunt asks a search engine
            // and never fetches the forum.
            title: t('forums.col_index'), dataIndex: 'index_status', width: 160,
            render: (st: string, row: CrimeForum) => {
              if (!st) return <Text type="secondary" style={{ fontSize: 12 }}>{t('forums.st_unchecked')}</Text>
              if (st === 'indexed') return (
                <Tooltip title={t('forums.st_indexed_hint', { n: row.index_count })}>
                  <Tag color="green">{t('forums.st_indexed')} · {row.index_count}+</Tag>
                </Tooltip>
              )
              if (st === 'not_indexed') return (
                <Tooltip title={t('forums.st_not_indexed_hint')}>
                  <Tag color="orange">{t('forums.st_not_indexed')}</Tag>
                </Tooltip>
              )
              if (st === 'not_applicable') return (
                <Tooltip title={t('forums.st_na_hint')}>
                  <Tag color="default">{t('forums.st_na')}</Tag>
                </Tooltip>
              )
              if (st === 'no_key') return <Tag color="default">{t('forums.st_no_key')}</Tag>
              return <Tag color="default">{t('forums.st_error')}</Tag>
            },
          },
          {
            title: t('forums.col_reach'), dataIndex: 'reach_status', width: 150,
            render: (st: string, row: CrimeForum) => {
              if (!st) return <Text type="secondary" style={{ fontSize: 12 }}>{t('forums.st_unchecked')}</Text>
              const tip = [row.title, row.reach_note].filter(Boolean).join(' · ')
              // "blocked" is up-and-refusing, not down — and several of the
              // most interesting forums sit permanently in that state.
              const map: Record<string, [string, string]> = {
                online: ['green', t('forums.st_online')],
                blocked: ['blue', t('forums.st_blocked')],
                unreachable: ['orange', t('forums.st_unreachable')],
                no_tor: ['default', t('forums.st_no_tor')],
                error: ['default', t('forums.st_error')],
              }
              const [color, label] = map[st] || ['default', st]
              // The ratio is the number that can actually be acted on: one
              // Tor probe is a statement about one circuit, ten are a
              // statement about the forum.
              const h = row.access_history
              const ratio = h && h.probes > 1
                ? <Text type="secondary" style={{ fontSize: 11 }}>
                    {t('forums.answered_ratio', { n: h.answered, of: h.probes })}
                  </Text>
                : null
              return (
                <Tooltip title={tip}>
                  <Space size={4}><Tag color={color}>{label}</Tag>{ratio}</Space>
                </Tooltip>
              )
            },
          },
          {
            // What a guest can read, and which software the board runs. The
            // column that decides what is buildable per forum: `login_required`
            // is a finding about this forum, never a task to go and get an
            // account — see the hint on the button.
            title: t('forums.col_access'), dataIndex: 'access_status', width: 170,
            render: (st: string, row: CrimeForum) => {
              if (!st) return <Text type="secondary" style={{ fontSize: 12 }}>{t('forums.st_unchecked')}</Text>
              const tip = [row.software && `${t('forums.software')}: ${row.software}`,
                           row.access_note,
                           // Say plainly when a per-handle check can never work
                           // here, rather than leaving an empty field to read as
                           // "not measured yet".
                           row.software && !row.profile_template
                             ? t('forums.profile_by_id') : '',
                          ].filter(Boolean).join(' · ')
              const map: Record<string, [string, string]> = {
                guest_open: ['green', t('forums.st_guest_open')],
                login_required: ['gold', t('forums.st_login_required')],
                blocked: ['blue', t('forums.st_blocked')],
                unknown: ['default', t('forums.st_unknown')],
                unreachable: ['orange', t('forums.st_unreachable')],
                no_tor: ['default', t('forums.st_no_tor')],
              }
              const [color, label] = map[st] || ['default', st]
              // The ratio is the number that can actually be acted on: one
              // Tor probe is a statement about one circuit, ten are a
              // statement about the forum.
              const h = row.access_history
              const ratio = h && h.probes > 1
                ? <Text type="secondary" style={{ fontSize: 11 }}>
                    {t('forums.answered_ratio', { n: h.answered, of: h.probes })}
                  </Text>
                : null
              return (
                <Tooltip title={tip}>
                  <Space size={4}><Tag color={color}>{label}</Tag>{ratio}</Space>
                </Tooltip>
              )
            },
          },
          {
            title: t('forums.col_category'), dataIndex: 'category', width: 160,
            render: (c: string, row: CrimeForum) => (
              <Select aria-label={t('a11y.row_category')} size="small" value={c} style={{ width: 140 }}
                      options={(cats.length ? cats : [c]).map((x) => ({ value: x, label: x }))}
                      onChange={(next) => persist(rows.map((r) =>
                        (r.id === row.id ? { ...r, category: next } : r)))} />
            ),
          },
          {
            title: t('forums.col_source'), dataIndex: 'source', width: 110,
            render: (s: string) => <Text type="secondary" style={{ fontSize: 12 }}>{s}</Text>,
          },
          {
            title: t('forums.col_note'), dataIndex: 'note',
            render: (n: string, row: CrimeForum) => (
              <Input size="small" defaultValue={n} placeholder="—"
                     onBlur={(e) => {
                       if (e.target.value !== n) {
                         persist(rows.map((r) => (r.id === row.id
                           ? { ...r, note: e.target.value } : r)))
                       }
                     }} />
            ),
          },
          {
            title: '', key: 'act', width: 60,
            render: (_: any, row: CrimeForum) => (
              <Popconfirm title={t('forums.remove_confirm')} onConfirm={() => remove(row)}>
                <Button aria-label={t('a11y.delete_row')} size="small" type="text" danger icon={<DeleteOutlined />} />
              </Popconfirm>
            ),
          },
        ]}
      />

      <Modal
        open={addOpen}
        title={t('forums.add_title')}
        onCancel={() => setAddOpen(false)}
        onOk={doBulk}
        confirmLoading={saving}
        okText={t('forums.add_ok')}
      >
        <Space direction="vertical" style={{ width: '100%' }} size={10}>
          <Paragraph type="secondary" style={{ margin: 0 }}>
            {t('forums.add_hint')}
          </Paragraph>
          <Input.TextArea
            rows={8}
            value={bulkText}
            onChange={(e) => setBulkText(e.target.value)}
            placeholder={'xss.is\nhttps://exploit.in/forum/\nnulled.to, cracked.io   # comment'}
          />
          <Space wrap>
            <Select aria-label={t('a11y.bulk_category')} style={{ width: 200 }} value={bulkCat} onChange={setBulkCat}
                    options={(cats.length ? cats : ['other']).map((c) => ({ value: c, label: c }))} />
            <Checkbox checked={bulkEnabled} onChange={(e) => setBulkEnabled(e.target.checked)}>
              {t('forums.add_enabled')}
            </Checkbox>
          </Space>
        </Space>
      </Modal>
    </Space>
  )
}

import { useEffect, useMemo, useState } from 'react'
import {
  Table, Button, Input, Select, Switch, Space, Alert, Tag, Popconfirm,
  Typography, Statistic, Card, Row, Col, Modal, Checkbox, message, Tooltip,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, CloudDownloadOutlined, ReloadOutlined,
  ThunderboltOutlined, SafetyCertificateOutlined, ClearOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { telegramChannelsApi, telegramSourcesApi, TgChannel, TgSource } from '../../api/client'

const { Text, Paragraph } = Typography

/**
 * Operator-maintained Telegram channel pool for the username sweep.
 *
 * The one thing this screen has to make impossible to misunderstand: the
 * pool and the swept set are not the same list. deepdarkCTI alone yields
 * ~960 handles, while every username search sweeps the ENABLED ones and the
 * module caps them (40 by default). Enabling everything would not "search
 * more" — it would make each search take forever and then silently truncate
 * to whichever 40 sorted first. So the counter is always "enabled / cap",
 * and going over the cap is called out rather than left to be discovered.
 */
export default function TelegramChannelsPanel() {
  const { t } = useTranslation()
  const [rows, setRows] = useState<TgChannel[]>([])
  const [cap, setCap] = useState(40)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [filter, setFilter] = useState('')
  const [catFilter, setCatFilter] = useState<string | undefined>()
  const [onlyEnabled, setOnlyEnabled] = useState(false)
  const [addOpen, setAddOpen] = useState(false)
  const [bulkText, setBulkText] = useState('')
  const [bulkCat, setBulkCat] = useState('threat_actor')
  const [bulkEnabled, setBulkEnabled] = useState(false)
  const [sources, setSources] = useState<TgSource[]>([])
  const [newSource, setNewSource] = useState('')
  const [busy, setBusy] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const d = await telegramChannelsApi.list()
      setRows(d.channels || [])
      setCap(d.sweep_cap || 40)
      setSources((await telegramSourcesApi.list()).sources || [])
    } catch (e: any) {
      message.error(e?.response?.data?.detail || t('tgchan.load_failed'))
    } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

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
      (!q || r.handle.includes(q) || (r.note || '').toLowerCase().includes(q)))
  }, [rows, filter, catFilter, onlyEnabled])

  const persist = async (next: TgChannel[]) => {
    setRows(next)
    setSaving(true)
    try {
      await telegramChannelsApi.save(next)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || t('tgchan.save_failed'))
      load()   // never leave the screen showing something that was not stored
    } finally { setSaving(false) }
  }

  const toggle = (row: TgChannel, on: boolean) =>
    persist(rows.map((r) => (r.id === row.id ? { ...r, enabled: on } : r)))

  const remove = (row: TgChannel) =>
    persist(rows.filter((r) => r.id !== row.id))

  const setManyEnabled = (on: boolean) => {
    const ids = new Set(shown.map((r) => r.id))
    persist(rows.map((r) => (ids.has(r.id) ? { ...r, enabled: on } : r)))
  }

  const doImport = async () => {
    setLoading(true)
    try {
      const d = await telegramChannelsApi.import()
      message.success(t('tgchan.imported', { fetched: d.fetched, added: d.added }))
      await load()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || t('tgchan.import_failed'))
    } finally { setLoading(false) }
  }

  const doBulk = async () => {
    if (!bulkText.trim()) return
    setSaving(true)
    try {
      const d = await telegramChannelsApi.bulk(bulkText, bulkCat, bulkEnabled)
      message.success(t('tgchan.bulk_added', { parsed: d.parsed, added: d.added }))
      setBulkText(''); setAddOpen(false)
      await load()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || t('tgchan.save_failed'))
    } finally { setSaving(false) }
  }

  const run = async (key: string, fn: () => Promise<any>, ok: (d: any) => string) => {
    setBusy(key)
    try { message.success(ok(await fn())); await load() }
    catch (e: any) { message.error(e?.response?.data?.detail || t('tgchan.save_failed')) }
    finally { setBusy('') }
  }

  const doCheck = (onlyActive: boolean) => run('check',
    () => telegramChannelsApi.check(onlyActive, 1000),
    (d) => t('tgchan.checked', { n: d.checked, alive: d.counts?.alive || 0,
                                dead: d.counts?.no_public_page || 0 }))

  const doCleanup = (remove: boolean) => run('cleanup',
    () => telegramChannelsApi.cleanup(remove, false),
    (d) => t(remove ? 'tgchan.cleaned_removed' : 'tgchan.cleaned_disabled',
             { n: d.affected }))

  const addSource = () => run('src',
    async () => {
      const next = [...sources, { url: newSource.trim() } as any]
      const r = await telegramSourcesApi.save(next); setNewSource(''); return r
    }, () => t('tgchan.src_added'))

  const removeSource = (id: string) => run('src',
    () => telegramSourcesApi.save(sources.filter((s) => s.id !== id)),
    () => t('tgchan.src_removed'))

  const scanSources = () => run('scan', () => telegramSourcesApi.scan(),
    (d) => t('tgchan.scanned', { found: d.found, added: d.added, sources: d.sources }))

  const overCap = enabledCount > cap
  const noPage = rows.filter((r) => r.status === 'no_public_page').length
  const checked = rows.filter((r) => r.status).length

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Alert
        type={overCap ? 'warning' : 'info'}
        showIcon
        message={t('tgchan.headline', { total: rows.length, enabled: enabledCount, cap })}
        description={
          <Paragraph style={{ margin: 0 }}>
            {t('tgchan.explain')}
            {overCap && <><br /><Text strong type="danger">{t('tgchan.over_cap', { cap })}</Text></>}
          </Paragraph>
        }
      />

      <Row gutter={12}>
        <Col span={6}><Card size="small"><Statistic title={t('tgchan.stat_pool')} value={rows.length} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title={t('tgchan.stat_active')} value={enabledCount}
          valueStyle={{ color: overCap ? '#cf1322' : '#3f8600' }} suffix={`/ ${cap}`} /></Card></Col>
        <Col span={12}>
          <Card size="small">
            <Space wrap>
              <Button icon={<CloudDownloadOutlined />} loading={loading} onClick={doImport}>
                {t('tgchan.import')}
              </Button>
              <Button icon={<PlusOutlined />} onClick={() => setAddOpen(true)}>
                {t('tgchan.add')}
              </Button>
              <Button icon={<SafetyCertificateOutlined />} loading={busy === 'check'}
                      onClick={() => doCheck(false)}>{t('tgchan.check')}</Button>
              <Popconfirm title={t('tgchan.cleanup_confirm', { n: noPage })}
                          okText={t('tgchan.cleanup_disable')}
                          cancelText={t('tgchan.cleanup_remove')}
                          onConfirm={() => doCleanup(false)}
                          onCancel={() => noPage && doCleanup(true)}>
                <Button icon={<ClearOutlined />} loading={busy === 'cleanup'}
                        disabled={!noPage}>{t('tgchan.cleanup')} ({noPage})</Button>
              </Popconfirm>
              <Button aria-label={t('a11y.refresh')} icon={<ReloadOutlined />} onClick={load} loading={loading} />
            </Space>
          </Card>
        </Col>
      </Row>

      <Space wrap>
        <Input.Search allowClear placeholder={t('tgchan.filter')} style={{ width: 240 }}
                      onChange={(e) => setFilter(e.target.value)} />
        <Select allowClear style={{ width: 200 }} value={catFilter} onChange={setCatFilter}
                placeholder={t('tgchan.category')}
                options={categories.map(([c, n]) => ({ value: c, label: `${c} (${n})` }))} />
        <Checkbox checked={onlyEnabled} onChange={(e) => setOnlyEnabled(e.target.checked)}>
          {t('tgchan.only_active')}
        </Checkbox>
        <Tooltip title={t('tgchan.bulk_hint', { count: shown.length })}>
          <Button size="small" icon={<ThunderboltOutlined />} disabled={!shown.length}
                  onClick={() => setManyEnabled(true)}>{t('tgchan.enable_shown')}</Button>
        </Tooltip>
        <Button size="small" disabled={!shown.length} onClick={() => setManyEnabled(false)}>
          {t('tgchan.disable_shown')}
        </Button>
      </Space>

      <Card size="small" title={t('tgchan.src_title')}
            extra={<Button size="small" icon={<CloudDownloadOutlined />}
                           loading={busy === 'scan'} onClick={scanSources}
                           disabled={!sources.length}>{t('tgchan.src_scan')}</Button>}>
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          <Paragraph type="secondary" style={{ margin: 0, fontSize: 12 }}>
            {t('tgchan.src_hint')}
          </Paragraph>
          <Space.Compact style={{ width: '100%' }}>
            <Input value={newSource} onChange={(e) => setNewSource(e.target.value)}
                   onPressEnter={addSource}
                   placeholder="https://github.com/fastfire/deepdarkCTI" />
            <Button type="primary" onClick={addSource} loading={busy === 'src'}
                    disabled={!newSource.trim()}>{t('tgchan.src_add')}</Button>
          </Space.Compact>
          {sources.map((src) => (
            <Space key={src.id} wrap style={{ width: '100%' }}>
              <Tag color={src.kind === 'github_repo' ? 'blue' : 'default'}>{src.kind}</Tag>
              <a href={src.url} target="_blank" rel="noopener noreferrer">{src.url}</a>
              {src.last_run && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {t('tgchan.src_last', { found: src.last_found, added: src.last_added,
                                          when: src.last_run.replace('T', ' ').slice(0, 16) })}
                </Text>
              )}
              {src.last_error && <Tag color="red">{src.last_error.slice(0, 60)}</Tag>}
              <Popconfirm title={t('tgchan.src_remove_confirm')}
                          onConfirm={() => removeSource(src.id)}>
                <Button aria-label={t('a11y.delete_row')} size="small" type="text" danger icon={<DeleteOutlined />} />
              </Popconfirm>
            </Space>
          ))}
        </Space>
      </Card>

      <Table
        size="small"
        rowKey="id"
        loading={loading || saving}
        dataSource={shown}
        pagination={{ pageSize: 25, size: 'small', showSizeChanger: true }}
        columns={[
          {
            title: t('tgchan.col_active'), dataIndex: 'enabled', width: 90,
            render: (v: boolean, row: TgChannel) => (
              <Switch aria-label={t('a11y.toggle_row_enabled')} size="small" checked={v} onChange={(on) => toggle(row, on)} />
            ),
          },
          {
            title: t('tgchan.col_handle'), dataIndex: 'handle',
            render: (h: string) => (
              <a href={`https://t.me/${h}`} target="_blank" rel="noopener noreferrer">@{h}</a>
            ),
          },
          {
            title: t('tgchan.col_status'), dataIndex: 'status', width: 150,
            render: (st: string, row: TgChannel) => {
              if (!st) return <Text type="secondary" style={{ fontSize: 12 }}>{t('tgchan.st_unchecked')}</Text>
              if (st === 'alive') return (
                <Tooltip title={`${row.title} · ${row.subscribers}`}>
                  <Tag color="green">{t('tgchan.st_alive')}{row.reach ? ` · ${row.reach.toLocaleString()}` : ''}</Tag>
                </Tooltip>
              )
              if (st === 'error') return <Tag color="default">{t('tgchan.st_error')}</Tag>
              // Deliberately not called "dead": an invite-only channel looks
              // exactly like this, and those are the ones worth keeping.
              return <Tag color="orange">{t('tgchan.st_nopage')}</Tag>
            },
          },
          {
            title: t('tgchan.col_category'), dataIndex: 'category', width: 130,
            render: (c: string) => <Tag>{c}</Tag>,
          },
          {
            title: t('tgchan.col_source'), dataIndex: 'source', width: 130,
            render: (s: string) => <Text type="secondary" style={{ fontSize: 12 }}>{s}</Text>,
          },
          {
            title: t('tgchan.col_note'), dataIndex: 'note',
            render: (n: string, row: TgChannel) => (
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
            render: (_: any, row: TgChannel) => (
              <Popconfirm title={t('tgchan.remove_confirm')} onConfirm={() => remove(row)}>
                <Button aria-label={t('a11y.delete_row')} size="small" type="text" danger icon={<DeleteOutlined />} />
              </Popconfirm>
            ),
          },
        ]}
      />

      <Modal
        open={addOpen}
        title={t('tgchan.add_title')}
        onCancel={() => setAddOpen(false)}
        onOk={doBulk}
        confirmLoading={saving}
        okText={t('tgchan.add_ok')}
      >
        <Space direction="vertical" style={{ width: '100%' }} size={10}>
          <Paragraph type="secondary" style={{ margin: 0 }}>
            {t('tgchan.add_hint')}
          </Paragraph>
          <Input.TextArea
            rows={8}
            value={bulkText}
            onChange={(e) => setBulkText(e.target.value)}
            placeholder={"@examplechannel\nhttps://t.me/another_one\nthird_channel, fourth_channel   # comment"}
          />
          <Space wrap>
            <Select aria-label={t('a11y.bulk_category')} style={{ width: 200 }} value={bulkCat} onChange={setBulkCat}
                    options={['threat_actor', 'infostealer', 'ransomware', 'forum',
                              'market', 'maas', 'exploits', 'service', 'other']
                      .map((c) => ({ value: c, label: c }))} />
            <Checkbox checked={bulkEnabled} onChange={(e) => setBulkEnabled(e.target.checked)}>
              {t('tgchan.add_enabled')}
            </Checkbox>
          </Space>
        </Space>
      </Modal>
    </Space>
  )
}

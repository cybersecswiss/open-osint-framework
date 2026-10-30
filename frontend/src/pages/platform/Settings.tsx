import { useMemo, useState } from 'react'
import {
  Typography, Card, Input, Button, Space, Tag, Alert, message, Tooltip, Divider, Spin, Switch, Popconfirm, Tabs, InputNumber,
  Statistic, Row, Col,
} from 'antd'
import {
  CheckCircleTwoTone, CloseCircleTwoTone, ExperimentOutlined, SaveOutlined,
  LinkOutlined, ClearOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiKeysApi, platformApi, ApiKeyInfo, KeyTestResult } from '../../api/client'
import TelegramChannelsPanel from '../../components/platform/TelegramChannelsPanel'
import NewsFeedsPanel from '../../components/platform/NewsFeedsPanel'
import CrimeForumsPanel from '../../components/platform/CrimeForumsPanel'

const { Title, Paragraph, Text, Link } = Typography

export default function Settings() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const { data: keys, isLoading } = useQuery({ queryKey: ['api-keys'], queryFn: apiKeysApi.list })

  // Operator toggle: external access to the n8n editor (n8n keeps running).
  const { data: n8nAccess } = useQuery({ queryKey: ['n8n-access'], queryFn: platformApi.getN8nAccess })
  // n8n version: running vs latest on npm.
  const { data: n8nVer, isFetching: verFetching, refetch: refetchVer } =
    useQuery({ queryKey: ['n8n-version'], queryFn: platformApi.getN8nVersion })
  const updateN8nMut = useMutation({
    mutationFn: () => platformApi.updateN8n(),
    onSuccess: () => { message.success(t('glbadmin.settings.saved')); setTimeout(() => refetchVer(), 4000) },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('glbadmin.save_failed')),
  })

  // AI function settings (entity cap sent to the model).
  const { data: aiCfg } = useQuery({ queryKey: ['ai-settings'], queryFn: platformApi.getAiSettings })
  const [aiMaxEdit, setAiMaxEdit] = useState<number | null>(null)
  const aiCfgMut = useMutation({
    mutationFn: (n: number) => platformApi.setAiSettings(n),
    onSuccess: () => { message.success(t('glbadmin.settings.saved')); setAiMaxEdit(null); qc.invalidateQueries({ queryKey: ['ai-settings'] }) },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('glbadmin.save_failed')),
  })

  // AI token usage + estimated cost (refreshes on the AI tab).
  const { data: aiUsage } = useQuery({ queryKey: ['ai-usage'], queryFn: platformApi.getAiUsage, refetchInterval: 30000 })
  const [rateIn, setRateIn] = useState<number | null>(null)
  const [rateOut, setRateOut] = useState<number | null>(null)
  const aiUsageResetMut = useMutation({
    mutationFn: () => platformApi.resetAiUsage(),
    onSuccess: () => { message.success(t('glbadmin.settings.saved')); qc.invalidateQueries({ queryKey: ['ai-usage'] }) },
  })
  const aiRatesMut = useMutation({
    mutationFn: () => platformApi.setAiRates(rateIn ?? aiUsage?.rate_in_per_m ?? 0, rateOut ?? aiUsage?.rate_out_per_m ?? 0),
    onSuccess: () => { message.success(t('glbadmin.settings.saved')); setRateIn(null); setRateOut(null); qc.invalidateQueries({ queryKey: ['ai-usage'] }) },
  })
  const n8nMut = useMutation({
    mutationFn: (enabled: boolean) => platformApi.setN8nAccess(enabled),
    onSuccess: () => {
      message.success(t('glbadmin.settings.saved'))
      qc.invalidateQueries({ queryKey: ['n8n-access'] })
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('glbadmin.save_failed')),
  })

  // Local edits (only sent on Save). Empty/unchanged secret fields are omitted.
  const [edited, setEdited] = useState<Record<string, string>>({})
  const [results, setResults] = useState<Record<string, KeyTestResult>>({})
  const [testing, setTesting] = useState<string | null>(null)
  const [ghuntBlob, setGhuntBlob] = useState('')
  const [deriving, setDeriving] = useState(false)
  const [deriveMsg, setDeriveMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const setVal = (name: string, v: string) => setEdited((p) => ({ ...p, [name]: v }))

  const saveMut = useMutation({
    mutationFn: () => apiKeysApi.save(edited),
    onSuccess: () => {
      message.success(t('glbadmin.settings.saved'))
      setEdited({})
      qc.invalidateQueries({ queryKey: ['api-keys'] })
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('glbadmin.save_failed')),
  })

  const runTest = async (name: string) => {
    setTesting(name)
    try {
      const r = await apiKeysApi.test(name, edited[name])
      setResults((p) => ({ ...p, [name]: r }))
    } catch (e: any) {
      setResults((p) => ({ ...p, [name]: { valid: false, message: e?.message || 'error' } }))
    } finally {
      setTesting(null)
    }
  }

  const runTelegramTest = async () => {
    setTesting('__telegram__')
    try {
      const r = await apiKeysApi.testTelegram({
        api_id: edited.TELEGRAM_API_ID,
        api_hash: edited.TELEGRAM_API_HASH,
        session: edited.TELEGRAM_SESSION,
      })
      setResults((p) => ({ ...p, __telegram__: r }))
    } catch (e: any) {
      setResults((p) => ({ ...p, __telegram__: { valid: false, message: e?.message || 'error' } }))
    } finally {
      setTesting(null)
    }
  }

  const runGhuntDerive = async () => {
    setDeriving(true)
    setDeriveMsg(null)
    try {
      const r = await apiKeysApi.ghuntDerive(ghuntBlob.trim())
      if (r.ok && r.master_token) {
        setVal('GHUNT_CREDS', r.master_token)
        setGhuntBlob('')
        setDeriveMsg({ ok: true, text: `${t('glbadmin.settings.ghunt_derived')}${r.account ? ` (${r.account})` : ''}` })
      } else {
        setDeriveMsg({ ok: false, text: r.message || 'error' })
      }
    } catch (e: any) {
      setDeriveMsg({ ok: false, text: e?.response?.data?.detail || e?.message || 'error' })
    } finally {
      setDeriving(false)
    }
  }

  // Group keys by their `group`, preserving registry order.
  const grouped = useMemo(() => {
    const g: Record<string, ApiKeyInfo[]> = {}
    for (const k of keys || []) (g[k.group] ||= []).push(k)
    return g
  }, [keys])

  if (isLoading) return <Spin style={{ display: 'block', margin: '80px auto' }} />

  const dirty = Object.keys(edited).length > 0

  const statusTag = (k: ApiKeyInfo) => {
    if (!k.is_set) return <Tag>{t('glbadmin.settings.st_empty')}</Tag>
    return k.from_env
      ? <Tag color="blue">{t('glbadmin.settings.st_env')}</Tag>
      : <Tag color="green">{t('glbadmin.settings.st_panel')}</Tag>
  }

  const testResult = (name: string) => {
    const r = results[name]
    if (!r) return null
    return r.valid
      ? <Text type="success"><CheckCircleTwoTone twoToneColor="#52c41a" /> {r.message}{r.account ? ` (${r.account})` : ''}</Text>
      : <Text type="danger"><CloseCircleTwoTone twoToneColor="#ff4d4f" /> {r.message}</Text>
  }

  const keyRow = (k: ApiKeyInfo) => (
    <div key={k.name} style={{ marginBottom: 18 }}>
      <Space wrap style={{ marginBottom: 4 }}>
        <Text strong>{k.label}</Text>
        {statusTag(k)}
        <Link href={k.register_url} target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>
          <LinkOutlined /> {t('glbadmin.settings.get_key')}
        </Link>
      </Space>
      {k.help && <div><Text type="secondary" style={{ fontSize: 12 }}>{k.help}</Text></div>}
      <Space.Compact style={{ width: '100%', maxWidth: 640, marginTop: 6 }}>
        {k.secret ? (
          <Input.Password
            placeholder={k.is_set ? `${t('glbadmin.settings.stored')}: ${k.preview}` : t('glbadmin.settings.placeholder')}
            value={edited[k.name] ?? ''}
            onChange={(e) => setVal(k.name, e.target.value)}
            autoComplete="new-password"
          />
        ) : (
          <Input
            placeholder={t('glbadmin.settings.placeholder')}
            defaultValue={k.preview}
            onChange={(e) => setVal(k.name, e.target.value)}
          />
        )}
        {k.testable && (
          <Button icon={<ExperimentOutlined />} loading={testing === k.name} onClick={() => runTest(k.name)}>
            {t('glbadmin.settings.test')}
          </Button>
        )}
        {k.is_set && !k.from_env && (
          <Tooltip title={t('glbadmin.settings.clear_hint')}>
            <Button aria-label={t('glbadmin.settings.clear_hint')} icon={<ClearOutlined />} onClick={() => setVal(k.name, '')} />
          </Tooltip>
        )}
      </Space.Compact>
      {edited[k.name] === '' && k.is_set && (
        <div><Text type="warning" style={{ fontSize: 12 }}>{t('glbadmin.settings.will_clear')}</Text></div>
      )}
      <div style={{ marginTop: 4 }}>{testResult(k.name)}</div>
    </div>
  )

  const groupNames = Object.keys(grouped)

  const keysTab = (
    <>
      <Alert type="info" showIcon style={{ marginBottom: 16 }} message={t('glbadmin.settings.note')} />
      {groupNames.map((gname) => {
        const isTelegram = gname === 'Telegram'
        const isGoogle = gname === 'Google'
        return (
          <Card key={gname} title={gname} size="small" style={{ marginBottom: 18 }}>
            {grouped[gname].map(keyRow)}
            {isGoogle && (
              <>
                <Divider style={{ margin: '8px 0' }} orientation="left" plain>
                  <Text type="secondary" style={{ fontSize: 12 }}>{t('glbadmin.settings.ghunt_setup')}</Text>
                </Divider>
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>{t('glbadmin.settings.ghunt_hint')}</Text>
                  <Space.Compact style={{ width: '100%', maxWidth: 640 }}>
                    <Input.Password
                      placeholder={t('glbadmin.settings.ghunt_blob_ph')}
                      value={ghuntBlob}
                      onChange={(e) => setGhuntBlob(e.target.value)}
                      autoComplete="new-password"
                    />
                    <Button icon={<ExperimentOutlined />} loading={deriving}
                      disabled={!ghuntBlob.trim()} onClick={runGhuntDerive} type="primary" ghost>
                      {t('glbadmin.settings.ghunt_derive')}
                    </Button>
                  </Space.Compact>
                  {deriveMsg && (deriveMsg.ok
                    ? <Text type="success"><CheckCircleTwoTone twoToneColor="#52c41a" /> {deriveMsg.text}</Text>
                    : <Text type="danger"><CloseCircleTwoTone twoToneColor="#ff4d4f" /> {deriveMsg.text}</Text>)}
                </Space>
              </>
            )}
            {isTelegram && (
              <>
                <Divider style={{ margin: '8px 0' }} />
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Button icon={<ExperimentOutlined />} loading={testing === '__telegram__'}
                    onClick={runTelegramTest} type="primary" ghost>
                    {t('glbadmin.settings.tg_test')}
                  </Button>
                  {testResult('__telegram__')}
                  <Text type="secondary" style={{ fontSize: 12 }}>{t('glbadmin.settings.tg_hint')}</Text>
                </Space>
              </>
            )}
          </Card>
        )
      })}
      <Space style={{ marginTop: 8 }}>
        <Button type="primary" icon={<SaveOutlined />} disabled={!dirty}
          loading={saveMut.isPending} onClick={() => saveMut.mutate()}>
          {t('glbadmin.settings.save')}
        </Button>
        {dirty && <Text type="secondary">{t('glbadmin.settings.unsaved')}</Text>}
      </Space>
    </>
  )

  const n8nTab = (
    <>
      <Card size="small" style={{ marginBottom: 20 }} title={t('glbadmin.settings.n8n_title')}>
        <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', justifyContent: 'space-between' }}>
          <Text type="secondary" style={{ fontSize: 13, maxWidth: 620 }}>
            {t('glbadmin.settings.n8n_desc')}
          </Text>
          <Switch aria-label={t('a11y.toggle_n8n_access')}
            checked={!!n8nAccess?.enabled}
            loading={n8nMut.isPending}
            onChange={(v) => n8nMut.mutate(v)}
            checkedChildren={t('glbadmin.settings.n8n_on')}
            unCheckedChildren={t('glbadmin.settings.n8n_off')}
          />
        </div>
      </Card>
      <Card size="small" title={t('glbadmin.settings.n8nver_title')}>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap' }}>
          <Space wrap>
            <Text>{t('glbadmin.settings.n8nver_current')}: <Text code>{n8nVer?.current || '—'}</Text></Text>
            <Text type="secondary">{t('glbadmin.settings.n8nver_latest')}: <Text code>{n8nVer?.latest || '—'}</Text></Text>
            {n8nVer && (n8nVer.update_available
              ? <Tag color="orange">{t('glbadmin.settings.n8nver_outdated')}</Tag>
              : <Tag color="green">{t('glbadmin.settings.n8nver_uptodate')}</Tag>)}
          </Space>
          <Space>
            <Button icon={<ExperimentOutlined />} loading={verFetching} onClick={() => refetchVer()}>
              {t('glbadmin.settings.n8nver_check')}
            </Button>
            {n8nVer?.update_available && (
              <Popconfirm
                title={t('glbadmin.settings.n8nver_update')}
                description={t('glbadmin.settings.n8nver_updating')}
                okButtonProps={{ loading: updateN8nMut.isPending }}
                onConfirm={() => updateN8nMut.mutate()}
              >
                <Button type="primary" loading={updateN8nMut.isPending}>
                  {t('glbadmin.settings.n8nver_update')}
                </Button>
              </Popconfirm>
            )}
          </Space>
        </div>
      </Card>
    </>
  )

  const aiTab = (
    <Card size="small" title={t('glbadmin.settings.ai_title')}>
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <Text type="secondary" style={{ fontSize: 13, maxWidth: 640, display: 'block' }}>
          {t('glbadmin.settings.ai_maxent_desc')}
        </Text>
        <Space>
          <Text>{t('glbadmin.settings.ai_maxent_label')}:</Text>
          <InputNumber aria-label={t('a11y.ai_max_entities')} min={10} max={500} step={10}
            value={aiMaxEdit ?? aiCfg?.max_entities ?? 150}
            onChange={(v) => setAiMaxEdit(v as number)} />
          <Button type="primary" icon={<SaveOutlined />} loading={aiCfgMut.isPending}
            disabled={aiMaxEdit === null || aiMaxEdit === aiCfg?.max_entities}
            onClick={() => aiCfgMut.mutate(aiMaxEdit ?? aiCfg?.max_entities ?? 150)}>
            {t('glbadmin.settings.save')}
          </Button>
        </Space>

        <Divider style={{ margin: '8px 0' }} />

        <Text strong>{t('glbadmin.settings.ai_usage_title')}</Text>
        <Row gutter={16}>
          <Col><Statistic title={t('glbadmin.settings.ai_usage_runs')} value={aiUsage?.runs ?? 0} /></Col>
          <Col><Statistic title={t('glbadmin.settings.ai_usage_tokens')}
            value={(aiUsage?.total_tokens ?? 0).toLocaleString()} /></Col>
          <Col><Statistic title={t('glbadmin.settings.ai_usage_cost')}
            value={aiUsage?.estimated_cost_usd ?? 0} precision={4} prefix="$" /></Col>
        </Row>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {t('glbadmin.settings.ai_usage_breakdown', {
            prompt: (aiUsage?.prompt_tokens ?? 0).toLocaleString(),
            output: (aiUsage?.billable_output_tokens ?? 0).toLocaleString(),
            model: aiUsage?.last_model || '—',
          })}
        </Text>

        <Space wrap>
          <Text style={{ fontSize: 12 }}>{t('glbadmin.settings.ai_rate_in')}:</Text>
          <InputNumber aria-label={t('a11y.ai_rate_in')} size="small" min={0} step={0.01} style={{ width: 100 }}
            value={rateIn ?? aiUsage?.rate_in_per_m ?? 0}
            onChange={(v) => setRateIn(v as number)} />
          <Text style={{ fontSize: 12 }}>{t('glbadmin.settings.ai_rate_out')}:</Text>
          <InputNumber aria-label={t('a11y.ai_rate_out')} size="small" min={0} step={0.01} style={{ width: 100 }}
            value={rateOut ?? aiUsage?.rate_out_per_m ?? 0}
            onChange={(v) => setRateOut(v as number)} />
          <Button size="small" loading={aiRatesMut.isPending}
            disabled={rateIn === null && rateOut === null}
            onClick={() => aiRatesMut.mutate()}>{t('glbadmin.settings.save')}</Button>
          <Popconfirm title={t('glbadmin.settings.ai_usage_reset_confirm')}
            onConfirm={() => aiUsageResetMut.mutate()}>
            <Button size="small" danger loading={aiUsageResetMut.isPending}>
              {t('glbadmin.settings.ai_usage_reset')}
            </Button>
          </Popconfirm>
        </Space>

        <Alert type="info" showIcon style={{ fontSize: 12 }}
          message={t('glbadmin.settings.ai_balance_note')} />
      </Space>
    </Card>
  )

  return (
    <div style={{ maxWidth: 860 }}>
      <Title level={3}>{t('glbadmin.settings.title')}</Title>
      <Paragraph type="secondary">{t('glbadmin.settings.intro')}</Paragraph>
      <Tabs defaultActiveKey="keys" items={[
        { key: 'keys', label: t('glbadmin.settings.tab_keys'), children: keysTab },
        { key: 'n8n', label: t('glbadmin.settings.tab_n8n'), children: n8nTab },
        { key: 'ai', label: t('glbadmin.settings.tab_ai'), children: aiTab },
        { key: 'feeds', label: t('glbadmin.settings.tab_feeds'), children: <NewsFeedsPanel /> },
        { key: 'tgchannels', label: t('glbadmin.settings.tab_tgchannels'),
          children: <TelegramChannelsPanel /> },
        { key: 'forums', label: t('glbadmin.settings.tab_forums'),
          children: <CrimeForumsPanel /> },
      ]} />
    </div>
  )
}

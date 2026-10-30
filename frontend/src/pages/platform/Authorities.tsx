import { useState } from 'react'
import {
  Typography, Space, Tag, Table, Button, Modal, Form, Input, InputNumber,
  Select, Drawer, Descriptions, Popconfirm, message, Alert, Tooltip, Divider, Switch,
} from 'antd'
import {
  PlusOutlined, ReloadOutlined, SettingOutlined, ApiOutlined,
  DeleteOutlined, PauseCircleOutlined, PlayCircleOutlined, CopyOutlined,
  MinusCircleOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  platformApi, TenantSummary, CreateTenantPayload, CreatedTenant,
} from '../../api/client'
import { formatDate } from '../../utils/datetime'
import CaseDriftPanel from '../../components/platform/CaseDriftPanel'

const { Title, Text } = Typography

function statusTag(t: TenantSummary, tr: (k: string) => string) {
  if (t.is_expired) return <Tag color="red">{tr('glbadmin.status_expired')}</Tag>
  if (!t.is_active) return <Tag color="orange">{tr('glbadmin.status_suspended')}</Tag>
  return <Tag color="green">{tr('glbadmin.status_active')}</Tag>
}

export default function Authorities() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [manageTenant, setManageTenant] = useState<string | null>(null)
  const [created, setCreated] = useState<CreatedTenant | null>(null)
  const [createForm] = Form.useForm()

  const { data: tenants, isLoading } = useQuery({ queryKey: ['platform-tenants'], queryFn: platformApi.listTenants })
  const { data: metrics } = useQuery({ queryKey: ['platform-metrics'], queryFn: platformApi.metrics })
  const moduleCatalog = metrics?.modules_loaded ?? []

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['platform-tenants'] })
    qc.invalidateQueries({ queryKey: ['platform-metrics'] })
    // also drop cached per-tenant detail so reopening Manage shows the
    // just-saved values (was the cause of "need to refresh").
    qc.invalidateQueries({ queryKey: ['platform-tenant'] })
  }

  const createMut = useMutation({
    mutationFn: (data: CreateTenantPayload) => platformApi.createTenant(data),
    onSuccess: (resp) => { setCreateOpen(false); createForm.resetFields(); setCreated(resp); invalidate() },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('glbadmin.save_failed')),
  })
  const renewMut = useMutation({
    mutationFn: (tenant: string) => platformApi.renew(tenant, 365),
    onSuccess: () => { message.success(t('glbadmin.renewed_ok')); invalidate() },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('glbadmin.save_failed')),
  })
  const activeMut = useMutation({
    mutationFn: (v: { tenant: string; is_active: boolean }) => platformApi.setActive(v.tenant, v.is_active),
    onSuccess: () => { message.success(t('glbadmin.saved')); invalidate() },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('glbadmin.save_failed')),
  })
  const deleteMut = useMutation({
    mutationFn: (tenant: string) => platformApi.deleteTenant(tenant),
    onSuccess: () => { message.success(t('glbadmin.deleted_ok')); invalidate() },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('glbadmin.save_failed')),
  })

  const checkAgent = async (tenant: string) => {
    const key = 'agent-' + tenant
    message.loading({ content: t('glbadmin.checking'), key })
    try {
      const h = await platformApi.agentHealth(tenant)
      if (h.reachable) message.success({ content: t('glbadmin.agent_reachable'), key })
      else message.warning({ content: `${t('glbadmin.agent_unreachable')}: ${h.detail || h.status_code || ''}`, key })
    } catch (e: any) {
      message.error({ content: e?.response?.data?.detail || t('glbadmin.agent_unreachable'), key })
    }
  }
  const copy = (v: string) => { navigator.clipboard?.writeText(v); message.success(t('glbadmin.copied')) }

  const columns = [
    {
      title: t('glbadmin.col_tenant'), key: 'tenant',
      render: (_: any, r: TenantSummary) => (
        <div><Text strong>{r.display_name || r.tenant}</Text>
          {r.display_name && <div style={{ fontSize: 11, color: '#8c8c8c' }}>{r.tenant}</div>}</div>
      ),
    },
    { title: t('glbadmin.col_status'), key: 'status', render: (_: any, r: TenantSummary) => statusTag(r, t) },
    {
      title: t('glbadmin.col_valid'), key: 'valid',
      render: (_: any, r: TenantSummary) => (
        <Tooltip title={formatDate(r.valid_until)}>
          <span style={{ color: r.days_remaining <= 30 ? '#faad14' : undefined }}>{t('glbadmin.days_left', { days: r.days_remaining })}</span>
        </Tooltip>
      ),
    },
    { title: t('glbadmin.col_contacts'), key: 'contacts', render: (_: any, r: TenantSummary) => <Tag>{(r.contacts?.length ?? 0)}</Tag> },
    {
      title: t('glbadmin.col_modules'), key: 'modules',
      render: (_: any, r: TenantSummary) => (!r.enabled_modules || r.enabled_modules.length === 0)
        ? <Tag color="green">{t('glbadmin.modules_all')}</Tag>
        : <Space wrap size={2}>{r.enabled_modules.map((m) => <Tag key={m} color="blue" style={{ margin: 0 }}>{m}</Tag>)}</Space>,
    },
    {
      title: t('glbadmin.col_actions'), key: 'actions',
      render: (_: any, r: TenantSummary) => (
        <Space size={4} wrap>
          <Tooltip title={t('glbadmin.manage')}><Button aria-label={t('glbadmin.manage')} size="small" icon={<SettingOutlined />} onClick={() => setManageTenant(r.tenant)} /></Tooltip>
          <Tooltip title={t('glbadmin.check_agent')}><Button aria-label={t('glbadmin.check_agent')} size="small" icon={<ApiOutlined />} onClick={() => checkAgent(r.tenant)} /></Tooltip>
          <Tooltip title={t('glbadmin.renew')}><Button aria-label={t('glbadmin.renew')} size="small" icon={<ReloadOutlined />} loading={renewMut.isPending} onClick={() => renewMut.mutate(r.tenant)} /></Tooltip>
          {r.is_active
            ? <Tooltip title={t('glbadmin.suspend')}><Button aria-label={t('glbadmin.suspend')} size="small" icon={<PauseCircleOutlined />} onClick={() => activeMut.mutate({ tenant: r.tenant, is_active: false })} /></Tooltip>
            : <Tooltip title={t('glbadmin.reactivate')}><Button aria-label={t('glbadmin.reactivate')} size="small" icon={<PlayCircleOutlined />} onClick={() => activeMut.mutate({ tenant: r.tenant, is_active: true })} /></Tooltip>}
          <Popconfirm title={t('glbadmin.delete_confirm', { tenant: r.tenant })} okButtonProps={{ danger: true }} onConfirm={() => deleteMut.mutate(r.tenant)}>
            <Button aria-label={t('a11y.delete_authority')} size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const onCreate = async () => {
    const v = await createForm.validateFields()
    createMut.mutate({
      tenant: v.tenant, contact_email: v.contact_email, valid_days: v.valid_days ?? 365,
      agent_url: v.agent_url || null, idp_url: v.idp_url || null,
      email_domains: v.email_domains ?? null,
      enabled_modules: (v.enabled_modules && v.enabled_modules.length) ? v.enabled_modules : null,
      display_name: v.display_name || null,
    })
  }

  return (
    <div>
      <Space align="baseline" style={{ marginBottom: 4, justifyContent: 'space-between', width: '100%' }}>
        <Title level={3} style={{ margin: 0 }}>{t('glbadmin.nav_authorities')}</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>{t('glbadmin.new_tenant')}</Button>
      </Space>

      <Table rowKey="tenant" loading={isLoading} dataSource={tenants} columns={columns as any}
        pagination={false} size="small" scroll={{ x: 'max-content' }} style={{ marginTop: 12 }} />

      <Modal title={t('glbadmin.create_title')} open={createOpen} onCancel={() => setCreateOpen(false)}
        onOk={onCreate} okText={t('glbadmin.create_ok')} confirmLoading={createMut.isPending} width={640}>
        <Form form={createForm} layout="vertical" initialValues={{ valid_days: 365 }}>
          <Space style={{ display: 'flex' }} align="start">
            <Form.Item name="tenant" label={t('glbadmin.f_tenant')} style={{ flex: 1 }}
              rules={[{ required: true }, { pattern: /^[a-z0-9-]+$/, message: t('glbadmin.f_tenant_rule') }]}>
              <Input placeholder="agency-zh" />
            </Form.Item>
            <Form.Item name="display_name" label={t('glbadmin.f_display_name')} style={{ flex: 1 }}>
              <Input placeholder="Example Agency" />
            </Form.Item>
          </Space>
          <Space style={{ display: 'flex' }} align="start">
            <Form.Item name="contact_email" label={t('glbadmin.f_contact')} style={{ flex: 1 }}
              rules={[{ required: true, type: 'email' }]}><Input placeholder="it@agency-zh.example" /></Form.Item>
            <Form.Item name="valid_days" label={t('glbadmin.f_valid_days')}><InputNumber min={1} max={36500} /></Form.Item>
          </Space>
          <Form.Item name="email_domains" label={t('glbadmin.f_email_domains')} help={t('glbadmin.f_email_domains_help')}>
            <Select mode="tags" tokenSeparators={[',', ' ']} placeholder="agency-zh.example" />
          </Form.Item>
          <Form.Item name="agent_url" label={t('glbadmin.f_agent_url')} help={t('glbadmin.f_agent_url_help')}><Input placeholder="https://data-agent.agency-zh.example:9000" /></Form.Item>
          <Form.Item name="idp_url" label={t('glbadmin.f_idp_url')} help={t('glbadmin.f_idp_url_help')}><Input placeholder="https://idp.agency-zh.example/auth/realms/agency-zh" /></Form.Item>
          <Form.Item name="enabled_modules" label={t('glbadmin.f_modules')} help={t('glbadmin.f_modules_help')}>
            <Select mode="multiple" allowClear placeholder={t('glbadmin.modules_all')} options={moduleCatalog.map((m) => ({ label: m, value: m }))} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title={t('glbadmin.created_title')} open={!!created} onCancel={() => setCreated(null)}
        footer={<Button type="primary" onClick={() => setCreated(null)}>{t('common.close')}</Button>}>
        <Alert type="warning" showIcon style={{ marginBottom: 12 }} message={t('glbadmin.created_warning')} />
        {created && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label={t('glbadmin.f_tenant')}>{created.tenant}</Descriptions.Item>
            <Descriptions.Item label={t('glbadmin.created_license_key')}>
              <Space><Text code>{created.license_key}</Text><Button aria-label={t('a11y.copy_license_key')} size="small" icon={<CopyOutlined />} onClick={() => copy(created.license_key)} /></Space>
            </Descriptions.Item>
            <Descriptions.Item label={t('glbadmin.created_agent_key')}>
              <Space><Text code>{created.agent_api_key}</Text><Button aria-label={t('a11y.copy_agent_key')} size="small" icon={<CopyOutlined />} onClick={() => copy(created.agent_api_key)} /></Space>
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>

      {manageTenant && (
        <ManageDrawer tenant={manageTenant} moduleCatalog={moduleCatalog}
          onClose={() => setManageTenant(null)} onSaved={invalidate} />
      )}
    </div>
  )
}

function ManageDrawer({ tenant, moduleCatalog, onClose, onSaved }: {
  tenant: string; moduleCatalog: string[]; onClose: () => void; onSaved: () => void
}) {
  const { t } = useTranslation()
  const [form] = Form.useForm()
  const { data, isLoading } = useQuery({
    queryKey: ['platform-tenant', tenant], queryFn: () => platformApi.getTenant(tenant),
    staleTime: 0, refetchOnMount: 'always',  // always show the current stored state
  })

  const saveMut = useMutation({
    mutationFn: async (v: any) => {
      await platformApi.setAgentUrl(tenant, v.agent_url || '')
      if (v.idp_url) await platformApi.setIdpUrl(tenant, v.idp_url)
      await platformApi.setEmailDomains(tenant, v.email_domains ?? [])
      await platformApi.setEnabledModules(tenant, (v.enabled_modules && v.enabled_modules.length) ? v.enabled_modules : null)
      await platformApi.setAiEnabled(tenant, !!v.ai_enabled)
      await platformApi.setSettings(tenant, { display_name: v.display_name || null })
      await platformApi.setContacts(tenant, (v.contacts ?? []).filter((c: any) => c && c.name))
    },
    onSuccess: () => { message.success(t('glbadmin.saved')); onSaved(); onClose() },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('glbadmin.save_failed')),
  })

  return (
    <Drawer title={`${t('glbadmin.manage_title')} — ${tenant}`} open width={520} onClose={onClose}
      extra={<Button type="primary" loading={saveMut.isPending} onClick={async () => saveMut.mutate(await form.validateFields())}>{t('common.save')}</Button>}>
      {isLoading || !data ? null : (
        <Form form={form} layout="vertical" initialValues={{
          display_name: data.display_name, agent_url: data.agent_url, idp_url: data.idp_url,
          email_domains: data.email_domains, enabled_modules: data.enabled_modules ?? [],
          ai_enabled: !!data.ai_enabled,
          contacts: data.contacts ?? [],
        }}>
          <Descriptions column={1} size="small" bordered style={{ marginBottom: 16 }}>
            <Descriptions.Item label={t('glbadmin.masked_license')}><Text code>{data.license_key_masked || '—'}</Text></Descriptions.Item>
            <Descriptions.Item label={t('glbadmin.masked_agent_key')}><Text code>{data.agent_api_key_masked || '—'}</Text></Descriptions.Item>
          </Descriptions>
          <Form.Item name="display_name" label={t('glbadmin.f_display_name')}><Input allowClear /></Form.Item>
          <Form.Item name="agent_url" label={t('glbadmin.f_agent_url')}><Input allowClear /></Form.Item>
          <Form.Item name="idp_url" label={t('glbadmin.f_idp_url')}><Input allowClear /></Form.Item>
          <Form.Item name="email_domains" label={t('glbadmin.f_email_domains')}><Select mode="tags" tokenSeparators={[',', ' ']} /></Form.Item>
          <Form.Item name="enabled_modules" label={t('glbadmin.f_modules')} help={t('glbadmin.f_modules_help')}>
            <Select mode="multiple" allowClear placeholder={t('glbadmin.modules_all')} options={moduleCatalog.map((m) => ({ label: m, value: m }))} />
          </Form.Item>
          <Form.Item name="ai_enabled" label={t('glbadmin.f_ai_enabled')} help={t('glbadmin.f_ai_help')} valuePropName="checked">
            <Switch />
          </Form.Item>

          <Divider orientation="left" style={{ fontSize: 13 }}>{t('glbadmin.contacts_title')}</Divider>
          <Form.List name="contacts">
            {(fields, { add, remove }) => (
              <>
                {fields.map((field) => (
                  <Space key={field.key} align="start" style={{ display: 'flex', marginBottom: 4 }} wrap>
                    <Form.Item name={[field.name, 'name']} rules={[{ required: true, message: t('glbadmin.c_name') }]} style={{ marginBottom: 8 }}>
                      <Input placeholder={t('glbadmin.c_name')} style={{ width: 140 }} />
                    </Form.Item>
                    <Form.Item name={[field.name, 'email']} style={{ marginBottom: 8 }}><Input placeholder={t('glbadmin.c_email')} style={{ width: 160 }} /></Form.Item>
                    <Form.Item name={[field.name, 'phone']} style={{ marginBottom: 8 }}><Input placeholder={t('glbadmin.c_phone')} style={{ width: 110 }} /></Form.Item>
                    <Form.Item name={[field.name, 'role']} style={{ marginBottom: 8 }}><Input placeholder={t('glbadmin.c_role')} style={{ width: 120 }} /></Form.Item>
                    <Button aria-label={t('a11y.remove_contact')} type="text" danger icon={<MinusCircleOutlined />} onClick={() => remove(field.name)} />
                  </Space>
                ))}
                <Button type="dashed" onClick={() => add()} icon={<PlusOutlined />} block>{t('glbadmin.contacts_add')}</Button>
              </>
            )}
          </Form.List>
        </Form>
      )}

      {/* Reconciliation against the customer's own store — see the panel's
          header for why it lives in the operator console and nowhere else. */}
      <Divider />
      <CaseDriftPanel tenant={tenant} />
    </Drawer>
  )
}

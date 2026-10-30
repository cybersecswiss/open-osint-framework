import { useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Typography, Switch, Radio, Form, Input, Button,
  Space, Tag, Skeleton, Descriptions, Empty,
} from 'antd'
import { ArrowLeftOutlined, SaveOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { monitoringApi, tenantApi } from '../api/client'
import { message } from 'antd'
import { formatDateTime } from '../utils/datetime'
import LoadFailed from '../components/LoadFailed'
import TriggerField, { normaliseTriggers, useTriggers } from '../components/monitoring/TriggerField'

// Fixed interval bands. Mapped to hours so the backend
// (which only knows interval_hours) doesn't need to change.
const INTERVAL_OPTIONS = [
  { value: 1,    labelKey: 'monitoring.interval_hourly' },
  { value: 24,   labelKey: 'monitoring.interval_daily' },
  { value: 168,  labelKey: 'monitoring.interval_weekly' },
  { value: 720,  labelKey: 'monitoring.interval_monthly' },
]


export default function MonitoringDetail() {
  const { t } = useTranslation()
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [form] = Form.useForm()

  const { data: config, isLoading, isError, refetch } = useQuery({
    queryKey: ['monitoring', id],
    queryFn: () => monitoringApi.get(id!),
    enabled: !!id,
  })
  // Pre-fill alert_email from the tenant default if this monitoring
  // hasn't set its own (tenant setting default_alert_email).
  const { data: tenantSettings } = useQuery({
    queryKey: ['tenant-settings'],
    queryFn: tenantApi.getSettings,
    staleTime: 5 * 60 * 1000,
  })

  const { data: triggers } = useTriggers()
  const mapped = normaliseTriggers(config?.alert_on, triggers?.legacy_map,
    (triggers?.available || []).map((a) => a.value))
  const droppedTriggers = triggers ? mapped.dropped : []

  useEffect(() => {
    if (config && triggers) {
      form.setFieldsValue({
        is_active: config.is_active,
        interval_hours: config.interval_hours,
        alert_on: mapped.values,
        alert_email: config.alert_email || tenantSettings?.default_alert_email || '',
        alert_webhook: config.alert_webhook,
      })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config, tenantSettings, form, triggers])

  const updateMut = useMutation({
    mutationFn: (data: any) => monitoringApi.update(id!, data),
    onSuccess: () => {
      message.success(t('monitoring.msg_saved'))
      qc.invalidateQueries({ queryKey: ['monitoring', id] })
      qc.invalidateQueries({ queryKey: ['monitoring'] })
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('monitoring.msg_save_failed')),
  })

  const onSave = () => form.validateFields().then((values) => updateMut.mutate(values))

  if (isLoading) return <Skeleton active paragraph={{ rows: 8 }} />
  // Two states, one branch: a failed request must not render as "not
  // found". "Not found" is a statement about the server's
  // answer; a failed request has no answer to report.
  if (isError) {
    return <LoadFailed what={t('loadfail.what.monitoring')}
                       onRetry={() => refetch()} />
  }
  if (!config) return <Empty description={t('monitoring.not_found')} />

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/monitoring')}>
          {t('monitoring.back_to_list')}
        </Button>
      </Space>

      <Typography.Title level={3} style={{ marginTop: 0 }}>
        {t('monitoring.detail_title')}
      </Typography.Title>

      <Card style={{ marginBottom: 16 }}>
        <Descriptions size="small" column={2}>
          <Descriptions.Item label={t('monitoring.detail_entity_id')}>
            <code>{String(config.entity_id).slice(0, 13)}…</code>
          </Descriptions.Item>
          <Descriptions.Item label={t('monitoring.detail_case_id')}>
            <a onClick={() => navigate(`/cases/${config.case_id}`)} style={{ cursor: 'pointer' }}>
              <code>{String(config.case_id).slice(0, 13)}…</code>
            </a>
          </Descriptions.Item>
          <Descriptions.Item label={t('monitoring.last_scan')}>
            {formatDateTime(config.last_scan)}
          </Descriptions.Item>
          <Descriptions.Item label={t('monitoring.next_scan')}>
            {formatDateTime(config.next_scan)}
          </Descriptions.Item>
          <Descriptions.Item label={t('monitoring.detail_created_by')}>
            {config.created_by}
          </Descriptions.Item>
          <Descriptions.Item label={t('monitoring.detail_created_at')}>
            {formatDateTime(config.created_at)}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card>
        <Form form={form} layout="vertical" onFinish={onSave}>
          <Form.Item name="is_active" label={t('monitoring.field_status')} valuePropName="checked">
            <Switch
              checkedChildren={<Tag color="green" style={{ margin: 0 }}>{t('monitoring.status_active')}</Tag>}
              unCheckedChildren={<Tag color="default" style={{ margin: 0 }}>{t('monitoring.status_inactive')}</Tag>}
            />
          </Form.Item>

          <Form.Item name="interval_hours" label={t('monitoring.field_interval')}>
            <Radio.Group optionType="button" buttonStyle="solid">
              {INTERVAL_OPTIONS.map((o) => (
                <Radio.Button key={o.value} value={o.value}>{t(o.labelKey)}</Radio.Button>
              ))}
            </Radio.Group>
          </Form.Item>

          <Form.Item name="alert_on" label={t('monitoring.field_triggers')}>
            <TriggerField dropped={droppedTriggers} />
          </Form.Item>

          <Form.Item
            name="alert_email"
            label={t('monitoring.field_alert_email')}
            rules={[{ type: 'email', message: t('search.email_invalid') }]}
          >
            <Input placeholder="alerts@agency-zh.example" allowClear />
          </Form.Item>
          <Form.Item
            name="alert_webhook"
            label={t('monitoring.field_alert_webhook')}
            rules={[{ type: 'url', message: t('monitoring.webhook_invalid') }]}
          >
            <Input placeholder="https://siem.agency-zh.example/hooks/osint" allowClear />
          </Form.Item>


          <Form.Item style={{ marginBottom: 0 }}>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              htmlType="submit"
              loading={updateMut.isPending}
            >
              {t('common.save')}
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  )
}

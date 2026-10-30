import { useEffect } from 'react'
import { Modal, Form, Input, Radio, message, Tag } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { monitoringApi, tenantApi } from '../../api/client'
import { lastPurpose, rememberPurpose } from '../../utils/purpose'
import TriggerField from './TriggerField'

// Same fixed bands MonitoringDetail uses, kept in sync.
const INTERVAL_OPTIONS = [
  { value: 1,    labelKey: 'monitoring.interval_hourly' },
  { value: 24,   labelKey: 'monitoring.interval_daily' },
  { value: 168,  labelKey: 'monitoring.interval_weekly' },
  { value: 720,  labelKey: 'monitoring.interval_monthly' },
]

interface Props {
  open: boolean
  onCancel: () => void
  /** Pre-fill — typically wired from the graph context-menu. Both
   *  identifiers are needed: case_id pins the monitoring to a case,
   *  entity_id is what gets re-scanned. */
  caseId: string
  entityId: string
  /** Optional: shown in the modal header so the user knows which
   *  entity they're about to monitor. */
  entityLabel?: string
}

export default function MonitoringQuickCreate({ open, onCancel, caseId, entityId, entityLabel }: Props) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [form] = Form.useForm()

  // Pre-fill alert_email from the tenant default
  // (default_alert_email setting). User can still change it before saving.
  const { data: tenantSettings } = useQuery({
    queryKey: ['tenant-settings'],
    queryFn: tenantApi.getSettings,
    staleTime: 5 * 60 * 1000,
  })

  useEffect(() => {
    if (open) {
      form.setFieldsValue({
        interval_hours: 24,
        alert_on: [],
        alert_email: tenantSettings?.default_alert_email || '',
        alert_webhook: '',
        purpose: lastPurpose(caseId) || '',
      })
    }
  }, [open, tenantSettings, form, caseId])

  const createMut = useMutation({
    mutationFn: (data: any) => monitoringApi.create(data),
    onSuccess: () => {
      message.success(t('monitoring.qc_created'))
      qc.invalidateQueries({ queryKey: ['monitoring'] })
      onCancel()
      form.resetFields()
    },
    onError: (e: any) => {
      const d = e?.response?.data?.detail
      const known: Record<string, string> = {
        purpose_required: 'search.purpose_required',
        activity_log_unavailable: 'search.activity_log_unavailable',
        monitoring_selector_unknown: 'monitoring.selector_unknown',
      }
      message.error(known[d] ? t(known[d]) : (typeof d === 'string' ? d : t('monitoring.qc_create_failed')))
    },
  })

  const onOk = async () => {
    const values = await form.validateFields()
    createMut.mutate({
      entity_id: entityId,
      case_id: caseId,
      interval_hours: values.interval_hours,
      alert_on: values.alert_on || [],
      alert_email: values.alert_email || null,
      alert_webhook: values.alert_webhook || null,
      purpose: (values.purpose || '').trim() || undefined,
    })
    if ((values.purpose || '').trim()) rememberPurpose(caseId, values.purpose.trim())
  }

  return (
    <Modal
      title={t('monitoring.qc_title')}
      open={open}
      onOk={onOk}
      confirmLoading={createMut.isPending}
      onCancel={onCancel}
      okText={t('monitoring.qc_create_button')}
      cancelText={t('common.cancel')}
      width={560}
      destroyOnClose
    >
      {entityLabel && (
        <p style={{ marginTop: 0 }}>
          {t('monitoring.qc_for')}: <Tag color="blue">{entityLabel}</Tag>
        </p>
      )}
      <Form form={form} layout="vertical">
        <Form.Item
          name="purpose"
          label={t('search.purpose_label')}
          extra={t('monitoring.purpose_hint')}
          rules={tenantSettings?.require_search_purpose
            ? [{ required: true, whitespace: true, message: t('search.purpose_required') }] : []}
        >
          <Input maxLength={500} placeholder={t('search.purpose_placeholder')} />
        </Form.Item>

        <Form.Item name="interval_hours" label={t('monitoring.field_interval')}>
          <Radio.Group optionType="button" buttonStyle="solid">
            {INTERVAL_OPTIONS.map((o) => (
              <Radio.Button key={o.value} value={o.value}>{t(o.labelKey)}</Radio.Button>
            ))}
          </Radio.Group>
        </Form.Item>

        <Form.Item name="alert_on" label={t('monitoring.field_triggers')}>
          <TriggerField />
        </Form.Item>

        <Form.Item
          name="alert_email"
          label={t('monitoring.field_alert_email')}
          help={tenantSettings?.default_alert_email
            ? t('monitoring.qc_email_prefilled')
            : undefined}
          rules={[{ type: 'email', message: t('search.email_invalid') }]}
        >
          <Input allowClear />
        </Form.Item>
        <Form.Item
          name="alert_webhook"
          label={t('monitoring.field_alert_webhook')}
          rules={[{ type: 'url', message: t('monitoring.webhook_invalid') }]}
        >
          <Input placeholder="https://siem.behoerde.example/hooks/osint" allowClear />
        </Form.Item>
      </Form>
    </Modal>
  )
}

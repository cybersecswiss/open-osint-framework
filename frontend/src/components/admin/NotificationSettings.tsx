import { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Checkbox, Descriptions, Divider, Form, Input,
  InputNumber, Select, Space, Spin, Switch, Tag, Tooltip, Typography, message,
} from 'antd'
import { SendOutlined, SaveOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  alertsApi, tenantApi,
  type DeliveryResult, type NotificationSettingsUpdate,
} from '../../api/client'

const { Text, Paragraph } = Typography

/**
 * Where the customer's own admin says how alerts reach them.
 *
 * Three properties are deliberate and easy to undo by accident:
 *
 * 1. **A password is never displayed.** The server reports
 *    `smtp_password_set`; the field stays empty with a "stored" hint. Only
 *    a typed value is sent, so leaving it alone keeps it.
 * 2. **Saving is not delivery.** The form reports "saved" and nothing
 *    more; only the test button claims a message arrived, and it prints
 *    what the mail server actually said when it did not.
 * 3. **Delivery health comes from the server**, not from this session.
 *    A tab opened tomorrow must still be able to say when the last alert
 *    went out and why the one before it failed.
 */
export default function NotificationSettings() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [form] = Form.useForm()
  const [testing, setTesting] = useState<string | null>(null)
  const [result, setResult] = useState<DeliveryResult | null>(null)
  const [testRecipient, setTestRecipient] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['notification-settings'],
    queryFn: tenantApi.getNotifications,
  })
  const { data: triggers } = useQuery({
    queryKey: ['alert-triggers'],
    queryFn: alertsApi.triggers,
  })

  useEffect(() => {
    if (data) {
      form.setFieldsValue({
        notify_email_enabled: data.notify_email_enabled,
        smtp_host: data.smtp_host,
        smtp_port: data.smtp_port,
        smtp_security: data.smtp_security,
        smtp_username: data.smtp_username,
        smtp_from: data.smtp_from,
        smtp_verify_tls: data.smtp_verify_tls,
        notify_webhook_enabled: data.notify_webhook_enabled,
        webhook_url: data.webhook_url,
        notify_events: data.notify_events || [],
        // Secrets intentionally absent — see the component docstring.
        smtp_password: '',
        webhook_secret: '',
      })
    }
  }, [data, form])

  const save = useMutation({
    mutationFn: (values: NotificationSettingsUpdate) => tenantApi.updateNotifications(values),
    onSuccess: () => {
      message.success(t('notify.saved'))
      qc.invalidateQueries({ queryKey: ['notification-settings'] })
      // Clear the secret inputs so a saved password is not left sitting in
      // the DOM for the rest of the session.
      form.setFieldsValue({ smtp_password: '', webhook_secret: '' })
    },
    onError: (e: any) =>
      message.error(e?.response?.data?.detail || t('notify.save_failed')),
  })

  const onFinish = (values: any) => {
    const payload: NotificationSettingsUpdate = { ...values }
    // An untouched secret field must not be sent at all: '' means "clear
    // it", and sending '' on every save would wipe the password the first
    // time somebody changed the port.
    if (!values.smtp_password) delete payload.smtp_password
    if (!values.webhook_secret) delete payload.webhook_secret
    save.mutate(payload)
  }

  const runTest = async (channel: 'email' | 'webhook') => {
    setTesting(channel)
    setResult(null)
    try {
      const r = await tenantApi.testNotification(
        channel, channel === 'email' ? testRecipient || undefined : undefined)
      setResult(r)
    } catch (e: any) {
      setResult({
        channel, ok: false,
        detail: e?.response?.data?.detail || t('notify.test_unreachable'),
        duration_ms: 0,
      })
    } finally {
      setTesting(null)
      qc.invalidateQueries({ queryKey: ['notification-settings'] })
    }
  }

  if (isLoading) return <Spin />

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      {data?.unregistered && (
        <Alert type="warning" showIcon message={t('notify.unregistered')} />
      )}

      <Alert
        type="info"
        showIcon
        message={t('notify.privacy_title')}
        description={t('notify.privacy_body')}
      />

      <Form form={form} layout="vertical" onFinish={onFinish}>
        <Card size="small" title={t('notify.email_section')}>
          <Form.Item name="notify_email_enabled" valuePropName="checked"
                     label={t('notify.email_enabled')}>
            <Switch />
          </Form.Item>
          <Space wrap align="start" style={{ width: '100%' }}>
            <Form.Item name="smtp_host" label={t('notify.smtp_host')}
                       style={{ minWidth: 260 }}>
              <Input placeholder="mail.example.org" autoComplete="off" />
            </Form.Item>
            <Form.Item name="smtp_port" label={t('notify.smtp_port')}>
              <InputNumber min={1} max={65535} />
            </Form.Item>
            <Form.Item name="smtp_security" label={t('notify.smtp_security')}
                       style={{ minWidth: 200 }}>
              <Select
                options={[
                  { value: 'starttls', label: t('notify.sec_starttls') },
                  { value: 'ssl', label: t('notify.sec_ssl') },
                  { value: 'none', label: t('notify.sec_none') },
                ]}
              />
            </Form.Item>
          </Space>
          <Space wrap align="start" style={{ width: '100%' }}>
            <Form.Item name="smtp_username" label={t('notify.smtp_username')}
                       style={{ minWidth: 260 }}>
              <Input autoComplete="off" />
            </Form.Item>
            <Form.Item
              name="smtp_password"
              label={t('notify.smtp_password')}
              extra={data?.smtp_password_set
                ? t('notify.secret_stored')
                : t('notify.secret_unset')}
              style={{ minWidth: 260 }}
            >
              <Input.Password autoComplete="new-password"
                              placeholder={data?.smtp_password_set ? '••••••••' : ''} />
            </Form.Item>
            <Form.Item name="smtp_from" label={t('notify.smtp_from')}
                       style={{ minWidth: 260 }}>
              <Input placeholder="osint@example.org" autoComplete="off" />
            </Form.Item>
          </Space>
          <Form.Item name="smtp_verify_tls" valuePropName="checked">
            <Checkbox>
              {t('notify.verify_tls')}{' '}
              <Tooltip title={t('notify.verify_tls_hint')}>
                <InfoCircleOutlined aria-hidden="true" />
              </Tooltip>
            </Checkbox>
          </Form.Item>

          <Divider style={{ margin: '12px 0' }} />
          <Space wrap>
            <Input
              value={testRecipient}
              onChange={(e) => setTestRecipient(e.target.value)}
              placeholder={data?.default_alert_email || t('notify.test_to_placeholder')}
              style={{ width: 260 }}
              aria-label={t('notify.test_to')}
            />
            <Button
              icon={<SendOutlined />}
              loading={testing === 'email'}
              onClick={() => runTest('email')}
            >
              {t('notify.test_email')}
            </Button>
            <Text type="secondary">{t('notify.test_hint')}</Text>
          </Space>
        </Card>

        <Card size="small" title={t('notify.webhook_section')} style={{ marginTop: 16 }}>
          <Form.Item name="notify_webhook_enabled" valuePropName="checked"
                     label={t('notify.webhook_enabled')}>
            <Switch />
          </Form.Item>
          <Form.Item name="webhook_url" label={t('notify.webhook_url')}
                     extra={t('notify.webhook_url_hint')}>
            <Input placeholder="https://soc.example.org/hooks/osint" autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="webhook_secret"
            label={t('notify.webhook_secret')}
            extra={data?.webhook_secret_set
              ? `${t('notify.secret_stored')} — ${t('notify.webhook_secret_hint')}`
              : t('notify.webhook_secret_hint')}
          >
            <Input.Password autoComplete="new-password"
                            placeholder={data?.webhook_secret_set ? '••••••••' : ''} />
          </Form.Item>
          <Button
            icon={<SendOutlined />}
            loading={testing === 'webhook'}
            onClick={() => runTest('webhook')}
          >
            {t('notify.test_webhook')}
          </Button>
        </Card>

        <Card size="small" title={t('notify.events_section')} style={{ marginTop: 16 }}>
          <Form.Item name="notify_events" extra={t('notify.events_hint')}>
            <Select
              mode="multiple"
              allowClear
              placeholder={t('notify.events_all')}
              options={(triggers?.available || []).map((x) => ({
                value: x.value,
                label: `${t(`notify.trigger_${x.value}`, x.value)} — ${x.description}`,
              }))}
            />
          </Form.Item>
          {!!triggers?.unavailable?.length && (
            <Alert
              type="warning"
              showIcon
              message={t('notify.unavailable_title')}
              description={
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {triggers.unavailable.map((u) => (
                    <li key={u.value}><Text code>{u.value}</Text> — {u.reason}</li>
                  ))}
                </ul>
              }
            />
          )}
        </Card>

        <Button type="primary" htmlType="submit" icon={<SaveOutlined />}
                loading={save.isPending} style={{ marginTop: 16 }}>
          {t('notify.save')}
        </Button>
      </Form>

      {result && (
        <Alert
          type={result.ok ? 'success' : 'error'}
          showIcon
          message={result.ok
            ? t('notify.test_ok', { channel: result.channel, ms: result.duration_ms })
            : t('notify.test_failed', { channel: result.channel })}
          description={result.detail}
        />
      )}

      <Card size="small" title={t('notify.health_section')}>
        <Descriptions column={1} size="small">
          <Descriptions.Item label={t('notify.last_ok')}>
            {data?.notify_last_ok_at
              ? new Date(data.notify_last_ok_at).toLocaleString()
              : <Text type="secondary">{t('notify.never')}</Text>}
          </Descriptions.Item>
          <Descriptions.Item label={t('notify.last_attempt')}>
            {data?.notify_last_attempt_at
              ? new Date(data.notify_last_attempt_at).toLocaleString()
              : <Text type="secondary">{t('notify.never')}</Text>}
          </Descriptions.Item>
          <Descriptions.Item label={t('notify.last_error')}>
            {data?.notify_last_error
              ? <Text type="danger">{data.notify_last_error}</Text>
              : <Tag color="green">{t('notify.no_error')}</Tag>}
          </Descriptions.Item>
          <Descriptions.Item label={t('notify.default_recipient')}>
            {data?.default_alert_email
              || <Text type="secondary">{t('notify.no_default_recipient')}</Text>}
          </Descriptions.Item>
        </Descriptions>
        <Paragraph type="secondary" style={{ marginBottom: 0, marginTop: 8 }}>
          {t('notify.health_hint')}
        </Paragraph>
      </Card>
    </Space>
  )
}

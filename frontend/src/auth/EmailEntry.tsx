import { useState } from 'react'
import { Card, Form, Input, Button, Alert, Typography, Space } from 'antd'
import { LoginOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'

interface Props {
  onResolve: (tenant: string, email: string) => void
}

/**
 * Pre-auth page. User enters their email; we ask the
 * backend which tenant owns that email's domain, then init keycloak-js
 * against that tenant's IdP. The framework operator never sees the
 * password — auth happens directly between the browser and the
 * customer-side Keycloak.
 */
export default function EmailEntry({ onResolve }: Props) {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (values: { email: string }) => {
    setError(null)
    setLoading(true)
    try {
      const apiBase = (import.meta as any).env.VITE_API_URL || ''
      const r = await fetch(
        `${apiBase}/api/v1/resolve-tenant?email=${encodeURIComponent(values.email)}`
      )
      if (r.status === 404) {
        setError(t('login.unknown_org'))
        return
      }
      if (!r.ok) {
        setError(t('login.lookup_failed'))
        return
      }
      const body = await r.json()
      onResolve(body.tenant, values.email)
    } catch (e) {
      setError(t('login.lookup_failed'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: '#f5f7fa',
    }}>
      <Card
        style={{ width: 440, boxShadow: '0 4px 24px rgba(0,0,0,0.06)' }}
        styles={{ body: { padding: 32 } }}
      >
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <div>
            <Typography.Title level={3} style={{ margin: 0 }}>
              OOF
            </Typography.Title>
            <Typography.Text type="secondary">{t('login.subtitle')}</Typography.Text>
          </div>

          <Form layout="vertical" onFinish={submit}>
            <Form.Item
              name="email"
              label={t('login.email_label')}
              rules={[
                { required: true, message: t('login.email_required') },
                { type: 'email', message: t('login.email_invalid') },
              ]}
            >
              <Input
                size="large"
                placeholder="firstname.lastname@authority.example"
                autoComplete="username"
                autoFocus
              />
            </Form.Item>

            <Form.Item style={{ marginBottom: 0 }}>
              <Button
                type="primary"
                htmlType="submit"
                size="large"
                icon={<LoginOutlined />}
                loading={loading}
                block
              >
                {t('login.continue')}
              </Button>
            </Form.Item>
          </Form>

          {error && <Alert type="error" showIcon message={error} />}

          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {t('login.privacy_note')}
          </Typography.Text>
        </Space>
      </Card>
    </div>
  )
}

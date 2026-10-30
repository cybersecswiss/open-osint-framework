import { Card, Button, Space, Typography, Alert, Collapse } from 'antd'
import { ReloadOutlined, MailOutlined, WarningOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'

const { Text, Paragraph } = Typography

/**
 * What the investigator sees when signing in fails.
 *
 * Without this page they would see nothing: if `main.tsx` renders `null`
 * while `authReady` is false and `initAuth(...).then(...)` carries no
 * `.catch`, a failure produces a blank white page — no message, no retry, no
 * way back. Reloading does not help either, because the stored tenant sends the
 * browser down the same path again.
 *
 * That matters more here than it would in most products. The identity
 * provider can run **on the tenant's own server**: it is the one
 * component in the login chain the operator neither monitors nor can restart.
 * An organisation whose Keycloak is down would see a white screen and
 * have nothing to report except "it doesn't work".
 *
 * Three things this page must do, in order of importance:
 *
 *  1. **Say which side failed.** "Your authority's login server did not
 *     answer" points the investigator at their own IT; "the framework could
 *     not be reached" points them at the operator. Getting this wrong wastes
 *     a support call on the wrong desk.
 *  2. **Offer a retry**, because the most common cause is transient.
 *  3. **Offer a way back to the e-mail entry**, which is the only escape from
 *     a wrong stored tenant — a typo that happens to match another
 *     authority's domain otherwise locks the browser into a loop.
 *
 * Deliberately NOT shown: the raw exception. It leaks internal hostnames to a
 * pre-auth screen. It is available behind a fold for someone who is actually
 * debugging.
 */
export type LoginErrorReason =
  /** The framework backend could not be asked which IdP to use. */
  | 'config'
  /** The IdP itself did not complete the handshake. */
  | 'idp'
  /** The handshake completed but returned "not authenticated". */
  | 'unauthenticated'

export default function LoginError({
  reason, detail, tenant, onRetry, onChangeEmail,
}: {
  reason: LoginErrorReason
  detail?: string
  tenant?: string | null
  onRetry: () => void
  onChangeEmail: () => void
}) {
  const { t } = useTranslation()

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center',
      justifyContent: 'center', background: '#f5f7fa', padding: 16,
    }}>
      <Card style={{ width: 520, boxShadow: '0 4px 24px rgba(0,0,0,0.06)' }}
            styles={{ body: { padding: 32 } }}>
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <div>
            <Typography.Title level={4} style={{ margin: 0 }}>
              <WarningOutlined style={{ color: '#faad14', marginInlineEnd: 8 }} />
              {t('login_error.title')}
            </Typography.Title>
            {tenant && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                {t('login_error.tenant', { tenant })}
              </Text>
            )}
          </div>

          <Alert
            type="error"
            showIcon
            message={t(`login_error.${reason}_head`)}
            description={
              <Paragraph style={{ margin: 0 }}>
                {t(`login_error.${reason}_body`)}
              </Paragraph>
            }
          />

          <Space>
            <Button type="primary" icon={<ReloadOutlined />} onClick={onRetry}>
              {t('login_error.retry')}
            </Button>
            <Button icon={<MailOutlined />} onClick={onChangeEmail}>
              {t('login_error.change_email')}
            </Button>
          </Space>

          {detail && (
            <Collapse
              size="small"
              ghost
              items={[{
                key: 'detail',
                label: <Text type="secondary" style={{ fontSize: 12 }}>
                  {t('login_error.technical')}
                </Text>,
                children: (
                  <Text code style={{ fontSize: 11, wordBreak: 'break-all' }}>
                    {detail}
                  </Text>
                ),
              }]}
            />
          )}
        </Space>
      </Card>
    </div>
  )
}

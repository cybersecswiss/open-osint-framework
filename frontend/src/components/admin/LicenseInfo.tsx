import { Card, Descriptions, Tag, Alert, Space, Typography, Spin, Empty } from 'antd'
import { CheckCircleTwoTone, CloseCircleTwoTone, WarningTwoTone } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { tenantApi } from '../../api/client'
import { formatDateTime } from '../../utils/datetime'
import LoadFailed from '../LoadFailed'

// Read-only License tab. Tenant-admin sees their license
// status, expiry, masked keys, and the operator-set tenant config
// (agent URL, IdP URL, email domains). Mutation (rotate-key, change
// validity, etc.) stays operator-side, in the operator console.

export default function LicenseInfo() {
  const { t } = useTranslation()
  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ['admin-license'],
    queryFn: tenantApi.getLicense,
    retry: false,
  })

  if (isLoading) return <Spin />
  if (isError) {
    // Was `<Empty description={detail} />`: AntD's empty-state illustration
    // says "there is nothing here", which is a statement about the licence.
    // A failed request is a statement about the request — the distinction
    // this project fixed in seven other places (see LoadFailed).
    const detail = (error as any)?.response?.data?.detail
    return <LoadFailed what={t('loadfail.what.license')} hint={detail}
                       onRetry={() => refetch()} loading={isFetching} />
  }
  if (!data) return <Empty description={t('admin.license_none')} />

  const expiringSoon = data.days_remaining <= 30 && data.days_remaining > 0
  const expired = data.is_expired

  let statusIcon: any = <CheckCircleTwoTone twoToneColor="#52c41a" />
  let statusColor = 'green'
  let statusKey = 'admin.license_status_active'
  if (expired) {
    statusIcon = <CloseCircleTwoTone twoToneColor="#ff4d4f" />
    statusColor = 'red'
    statusKey = 'admin.license_status_expired'
  } else if (expiringSoon) {
    statusIcon = <WarningTwoTone twoToneColor="#faad14" />
    statusColor = 'orange'
    statusKey = 'admin.license_status_expiring'
  } else if (!data.is_active) {
    statusIcon = <CloseCircleTwoTone twoToneColor="#ff4d4f" />
    statusColor = 'red'
    statusKey = 'admin.license_status_inactive'
  }

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%', maxWidth: 720 }}>
      {expired && (
        <Alert type="error" showIcon
          message={t('admin.license_alert_expired_title')}
          description={t('admin.license_alert_expired_desc')}
        />
      )}
      {expiringSoon && (
        <Alert type="warning" showIcon
          message={t('admin.license_alert_expiring_title', { days: data.days_remaining })}
          description={t('admin.license_alert_expiring_desc')}
        />
      )}

      <Card>
        <Space size="large" align="center" style={{ marginBottom: 16 }}>
          <span style={{ fontSize: 28 }}>{statusIcon}</span>
          <div>
            <Tag color={statusColor} style={{ fontSize: 14, padding: '2px 10px' }}>
              {t(statusKey)}
            </Tag>
            {!expired && (
              <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 2 }}>
                {t('admin.license_days_remaining', { days: data.days_remaining })}
              </div>
            )}
          </div>
        </Space>

        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label={t('admin.license_tenant')}>
            <Tag color="blue">{data.tenant}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label={t('admin.license_valid_until')}>
            {formatDateTime(data.valid_until)}
          </Descriptions.Item>
          <Descriptions.Item label={t('admin.license_contact_email')}>
            {data.contact_email}
          </Descriptions.Item>
          <Descriptions.Item label={t('admin.license_key')}>
            <Typography.Text code>{data.license_key_masked}</Typography.Text>
          </Descriptions.Item>
          <Descriptions.Item label={t('admin.license_agent_api_key')}>
            <Typography.Text code>{data.agent_api_key_masked}</Typography.Text>
          </Descriptions.Item>
          <Descriptions.Item label={t('admin.license_agent_url')}>
            {data.agent_url ? <Typography.Text code copyable>{data.agent_url}</Typography.Text> : '—'}
          </Descriptions.Item>
          <Descriptions.Item label={t('admin.license_idp_url')}>
            {data.idp_url ? <Typography.Text code copyable>{data.idp_url}</Typography.Text> : '—'}
          </Descriptions.Item>
          <Descriptions.Item label={t('admin.license_email_domains')}>
            {data.email_domains.length === 0
              ? <span style={{ color: '#999' }}>—</span>
              : <Space wrap>{data.email_domains.map((d) => <Tag key={d}>{d}</Tag>)}</Space>}
          </Descriptions.Item>
          <Descriptions.Item label={t('admin.license_modules')}>
            {(!data.enabled_modules || data.enabled_modules.length === 0)
              ? <Tag color="green">{t('admin.license_modules_all')}</Tag>
              : <Space wrap>{data.enabled_modules.map((m) => <Tag key={m} color="blue">{m}</Tag>)}</Space>}
          </Descriptions.Item>
          <Descriptions.Item label={t('admin.license_ai')}>
            {data.ai_enabled
              ? <Tag color="green">{t('admin.license_ai_on')}</Tag>
              : <Tag>{t('admin.license_ai_off')}</Tag>}
          </Descriptions.Item>
          <Descriptions.Item label={t('admin.license_created_at')}>
            {formatDateTime(data.created_at)}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Alert type="info" showIcon
        message={t('admin.license_operator_note_title')}
        description={t('admin.license_operator_note_desc')}
      />
    </Space>
  )
}

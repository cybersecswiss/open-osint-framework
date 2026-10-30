import { Table, Tag, Typography, Space, Button, Alert } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { platformApi } from '../../api/client'
import { formatDateTime } from '../../utils/datetime'
import LoadFailed from '../../components/LoadFailed'

const { Title, Paragraph, Text } = Typography

/**
 * The operator's own action log.
 *
 * Every route on the platform router is audited — including attempts that
 * were rejected, because on an operator console "someone tried" is exactly
 * the interesting line. Nothing could read those rows back until now: the
 * existing audit view filters on the caller's tenant, and a platform admin
 * is deliberately tenant-less.
 *
 * The boundary is explicit: the operator MAY see the audit log of their
 * own platform actions and MUST NOT see a tenant's. The server pins the
 * query to the platform tenant and accepts no tenant parameter, so the
 * boundary is not a matter of what this page asks for.
 */
const COLORS: Record<string, string> = {
  create: 'green', delete: 'red', update: 'gold', renew: 'cyan', read: 'default',
}

function actionColor(a: string): string {
  const verb = a.split('.').pop() || ''
  return COLORS[verb] || (a.includes('delete') ? 'red' : 'blue')
}

export default function PlatformAudit() {
  const { t } = useTranslation()
  const { data, isLoading, isError, isFetching, refetch } = useQuery({
    queryKey: ['platform-audit'],
    queryFn: () => platformApi.audit(200),
  })

  const columns = [
    { title: t('audit.time'), dataIndex: 'timestamp', width: 165,
      render: (x: string) => formatDateTime(x) },
    { title: t('audit.user'), dataIndex: 'user_name', width: 150 },
    { title: t('audit.action'), dataIndex: 'action', width: 190,
      render: (a: string) => <Tag color={actionColor(a)}>{a}</Tag> },
    { title: t('audit.target'), width: 160,
      render: (_: any, r: any) => r.target_id
        ? `${r.target_type || '—'}:${r.target_id}` : '—' },
    { title: t('audit.ip'), dataIndex: 'ip_address', width: 130 },
    { title: t('audit.details'),
      render: (_: any, r: any) => r.details
        ? <Text type="secondary" style={{ fontSize: 12 }}>
            {JSON.stringify(r.details).slice(0, 160)}
          </Text>
        : '' },
  ]

  return (
    <div>
      <Title level={3} style={{ marginTop: 0 }}>{t('glbadmin.audit.title')}</Title>
      <Paragraph type="secondary">{t('glbadmin.audit.subtitle')}</Paragraph>

      <Alert type="info" showIcon style={{ marginBottom: 16 }}
             message={t('glbadmin.audit.boundary')} />

      {isError ? (
        <LoadFailed what={t('loadfail.what.audit')}
                    onRetry={() => refetch()} loading={isFetching} />
      ) : (
        <>
          <Space style={{ marginBottom: 12 }}>
            <Button icon={<ReloadOutlined />} loading={isFetching}
                    onClick={() => refetch()}>{t('audit.refresh')}</Button>
            <Text type="secondary">
              {t('glbadmin.audit.count', { count: data?.total ?? 0 })}
            </Text>
          </Space>
          <Table rowKey="id" size="small" loading={isLoading}
                 dataSource={data?.entries ?? []} columns={columns}
                 pagination={{ pageSize: 25, showSizeChanger: false }}
                 scroll={{ x: 1000 }} />
        </>
      )}
    </div>
  )
}

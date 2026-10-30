import { Table, Tag, Button, Space, Typography, Alert } from 'antd'
import { SafetyCertificateOutlined, ReloadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { auditApi } from '../../api/client'
import { formatDateTime } from '../../utils/datetime'

const ACTION_COLORS: Record<string, string> = {
  'case.delete': 'red', 'entity.delete': 'red', 'case.auto_delete': 'volcano',
  'report.export': 'green', 'ai.link': 'purple', 'ai.apply': 'purple',
  'search.run': 'blue', 'entities.commit': 'cyan', 'entity.rename': 'geekblue',
  'case.create': 'green', 'case.update': 'gold',
}

export default function AuditLog() {
  const { t } = useTranslation()
  const { data, isFetching, refetch } = useQuery({ queryKey: ['audit'], queryFn: () => auditApi.list(200) })
  const { data: v, refetch: reverify, isFetching: verifying } = useQuery({ queryKey: ['audit-verify'], queryFn: auditApi.verify })

  const columns = [
    { title: t('audit.time'), dataIndex: 'timestamp', width: 160,
      render: (x: string) => formatDateTime(x) },
    { title: t('audit.user'), dataIndex: 'user_name', width: 130 },
    { title: t('audit.action'), dataIndex: 'action', width: 150,
      render: (a: string) => <Tag color={ACTION_COLORS[a] || 'default'}>{a}</Tag> },
    { title: t('audit.target'), width: 150,
      render: (_: any, r: any) => r.target_type ? `${r.target_type}:${String(r.target_id || '').slice(0, 8)}` : '—' },
    { title: t('audit.ip'), dataIndex: 'ip_address', width: 130 },
    { title: t('audit.details'),
      render: (_: any, r: any) => r.details
        ? <Typography.Text type="secondary" style={{ fontSize: 12 }}>{JSON.stringify(r.details).slice(0, 140)}</Typography.Text>
        : '' },
  ]

  return (
    <>
      <Typography.Paragraph type="secondary">{t('audit.intro')}</Typography.Paragraph>
      <Space style={{ marginBottom: 12 }} wrap>
        {v && (v.ok
          ? <Alert type="success" showIcon banner message={t('audit.intact', { n: v.checked })} />
          : <Alert type="error" showIcon banner message={t('audit.broken', { at: v.broken_at })} />)}
        <Button icon={<SafetyCertificateOutlined />} loading={verifying} onClick={() => reverify()}>
          {t('audit.verify')}
        </Button>
        <Button icon={<ReloadOutlined />} loading={isFetching} onClick={() => refetch()}>
          {t('audit.refresh')}
        </Button>
      </Space>
      <Table size="small" rowKey="id" columns={columns as any}
        dataSource={data?.entries || []} pagination={{ pageSize: 20, showTotal: (n) => `${n}` }}
        scroll={{ x: 900 }} />
    </>
  )
}

import { Alert, Empty, Spin, Table, Tag, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { casesApi, type ActivityEntry } from '../../api/client'
import { formatDateTime } from '../../utils/datetime'

const { Text } = Typography

/**
 * The case's activity log, read from the CUSTOMER's store: who searched what,
 * when, and for what stated purpose. This is the record a data-protection
 * officer or a court asks for; the operator holds only a fingerprint of it.
 *
 * An unreachable store is said as such — an empty table would read as
 * "nobody searched", which is the one wrong answer this panel must not give.
 */
export default function ActivityLogPanel({ caseId }: { caseId: string }) {
  const { t } = useTranslation()
  const q = useQuery({
    queryKey: ['case-activity', caseId],
    queryFn: () => casesApi.activity(caseId),
    retry: false,
  })

  if (q.isLoading) return <Spin />
  if (q.isError) {
    return <Alert type="warning" showIcon message={t('activity.unavailable')} />
  }
  const rows = q.data?.entries || []
  if (!rows.length) return <Empty description={t('activity.empty')} />

  const actionLabel = (a: string) => {
    const key = `activity.action_${a.replace('.', '_')}`
    const label = t(key)
    return label === key ? a : label
  }

  return (
    <Table<ActivityEntry>
      size="small"
      rowKey="id"
      dataSource={rows}
      pagination={{ pageSize: 50, hideOnSinglePage: true }}
      columns={[
        {
          title: t('activity.col_time'), dataIndex: 'timestamp', width: 160,
          render: (v) => formatDateTime(v),
        },
        { title: t('activity.col_user'), dataIndex: 'user_name', width: 140 },
        {
          title: t('activity.col_action'), dataIndex: 'action', width: 150,
          render: (v: string) => <Tag color={v === 'monitoring.rescan' ? 'default' : 'blue'}>{actionLabel(v)}</Tag>,
        },
        {
          title: t('activity.col_selector'), key: 'sel',
          render: (_, r) => r.action === 'entity.merge' ? (
            <Text type="secondary">
              {(r.details?.merged || []).map((m: any) => m.label).join(', ')} → <Text strong>{r.details?.target?.label}</Text>
            </Text>
          ) : r.action === 'case.access_change' ? (
            <Text type="secondary">
              {r.details?.after?.restricted ? t('case_access.tag') : '—'}
              {r.details?.after?.members?.length ? ` · ${r.details.after.members.join(', ')}` : ''}
              {r.details?.after?.assigned_to ? ` · ${t('case_detail.assigned_label')}: ${r.details.after.assigned_to}` : ''}
            </Text>
          ) : (
            <span>
              <Text code>{r.details?.query || '—'}</Text>{' '}
              {r.details?.query_type && <Text type="secondary">({r.details.query_type})</Text>}
            </span>
          ),
        },
        {
          title: t('activity.col_purpose'), key: 'purpose',
          render: (_, r) => ['case.access_change', 'evidence.capture', 'entity.merge'].includes(r.action) ? null : r.details?.purpose
            ? <Text>{r.details.purpose}</Text>
            : r.action === 'monitoring.rescan'
              ? <Text type="secondary">{t('activity.purpose_from_watch')}</Text>
              : <Text type="secondary">{t('activity.no_purpose')}</Text>,
        },
      ]}
    />
  )
}

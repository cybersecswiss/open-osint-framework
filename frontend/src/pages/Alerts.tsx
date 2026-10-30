import { useMemo, useState } from 'react'
import {
  Alert as AntAlert, Button, Card, Empty, Segmented, Space, Table, Tag,
  Tooltip, Typography, message,
} from 'antd'
import { CheckOutlined, ReloadOutlined, FolderOpenOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { alertsApi, type AlertRow } from '../api/client'
import { formatDateTime } from '../utils/datetime'
import LoadFailed from '../components/LoadFailed'

const { Text } = Typography

/**
 * Every alert across every case.
 *
 * The dashboard tile answers "is there anything?"; the case view answers
 * "what happened here?". Neither answers the question an investigator with
 * three monitored cases actually has, which is "what changed anywhere since
 * I last looked" — the tile could only ever open one case.
 *
 * Sorted newest first and defaulting to unread, because that is the working
 * order. Marking read is explicit: an alert that disappears because a list
 * was rendered has not been read by anybody.
 */
const TYPE_COLOR: Record<string, string> = {
  new_entity: 'blue',
  new_account: 'purple',
  new_edge: 'cyan',
}

export default function Alerts() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [scope, setScope] = useState<'unread' | 'all'>('unread')
  const [picked, setPicked] = useState<string[]>([])

  const q = useQuery({
    queryKey: ['alerts', scope],
    queryFn: () => alertsApi.list(scope === 'unread', 500),
  })

  const markRead = useMutation({
    mutationFn: ({ ids, read }: { ids?: string[]; read: boolean }) =>
      alertsApi.markRead(ids, read),
    onSuccess: (r) => {
      message.success(t('alerts.marked', { n: r.updated }))
      setPicked([])
      // Both this list and the dashboard tile read the same rows.
      qc.invalidateQueries({ queryKey: ['alerts'] })
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('alerts.mark_failed')),
  })

  const rows = q.data?.alerts ?? []
  const unreadTotal = useMemo(() => rows.filter((r) => !r.is_read).length, [rows])

  // The label lives with the customer and is resolved per request. When
  // the agent is unreachable we say so instead of printing a bare UUID and
  // letting the reader think that is the finding.
  const label = (a: AlertRow) => {
    if (a.entity_label) return a.entity_label
    const v = (a.new_value || {}) as Record<string, any>
    if (v.relation) return String(v.relation)
    return a.resolved === false ? t('alerts.unresolved') : a.entity_id
  }

  const columns = [
    {
      title: t('alerts.col_when'),
      dataIndex: 'created_at',
      width: 170,
      render: (v: string, r: AlertRow) => (
        <Space size={4}>
          {!r.is_read && <Tag color="red" style={{ marginInlineEnd: 0 }}>{t('alerts.new')}</Tag>}
          <Text type={r.is_read ? 'secondary' : undefined}>{formatDateTime(v)}</Text>
        </Space>
      ),
    },
    {
      title: t('alerts.col_case'),
      dataIndex: 'case_title',
      render: (v: string | null, r: AlertRow) => (
        <Button type="link" style={{ padding: 0 }}
                onClick={() => navigate(`/cases/${r.case_id}`)}>
          {v || r.case_number || r.case_id.slice(0, 8)}
        </Button>
      ),
    },
    {
      title: t('alerts.col_type'),
      dataIndex: 'change_type',
      width: 150,
      render: (v: string) => (
        <Tag color={TYPE_COLOR[v] || 'default'}>{t(`notify.trigger_${v}`, v)}</Tag>
      ),
    },
    {
      title: t('alerts.col_what'),
      key: 'what',
      render: (_: unknown, r: AlertRow) => {
        const v = (r.new_value || {}) as Record<string, any>
        const meta = [v.entity_type, v.source, r.admiralty].filter(Boolean).join(' · ')
        return (
          <Space direction="vertical" size={0}>
            <Text type={r.resolved === false ? 'secondary' : undefined}
                  italic={r.resolved === false}>
              {label(r)}
            </Text>
            {meta && <Text type="secondary" style={{ fontSize: 12 }}>{meta}</Text>}
          </Space>
        )
      },
    },
    {
      title: t('alerts.col_actions'),
      key: 'actions',
      width: 130,
      align: 'right' as const,
      render: (_: unknown, r: AlertRow) => (
        <Space>
          <Tooltip title={t('alerts.open_case')}>
            <Button size="small" icon={<FolderOpenOutlined />}
                    aria-label={t('alerts.open_case')}
                    onClick={() => navigate(`/cases/${r.case_id}`)} />
          </Tooltip>
          {!r.is_read && (
            <Tooltip title={t('alerts.mark_one')}>
              <Button size="small" icon={<CheckOutlined />}
                      aria-label={t('alerts.mark_one')}
                      onClick={() => markRead.mutate({ ids: [r.id], read: true })} />
            </Tooltip>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 16 }}
             align="start">
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>{t('alerts.title')}</Typography.Title>
          <Text type="secondary">{t('alerts.subtitle')}</Text>
        </div>
        <Space>
          <Segmented
            aria-label={t('alerts.scope')}
            value={scope}
            onChange={(v) => { setScope(v as 'unread' | 'all'); setPicked([]) }}
            options={[
              { value: 'unread', label: t('alerts.scope_unread') },
              { value: 'all', label: t('alerts.scope_all') },
            ]}
          />
          <Tooltip title={t('alerts.reload')}>
            <Button icon={<ReloadOutlined />} aria-label={t('alerts.reload')}
                    loading={q.isFetching} onClick={() => q.refetch()} />
          </Tooltip>
        </Space>
      </Space>

      {q.isError && (
        <LoadFailed compact what={t('alerts.title')} onRetry={() => q.refetch()} />
      )}

      {rows.length > 0 && rows.every((r) => r.resolved === false) && (
        <AntAlert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message={t('alerts.unresolved_title')}
          description={t('alerts.unresolved_body')}
        />
      )}

      {picked.length > 0 && (
        <Space style={{ marginBottom: 12 }}>
          <Button type="primary" icon={<CheckOutlined />} loading={markRead.isPending}
                  onClick={() => markRead.mutate({ ids: picked, read: true })}>
            {t('alerts.mark_selected', { n: picked.length })}
          </Button>
          <Button onClick={() => setPicked([])}>{t('alerts.clear_selection')}</Button>
        </Space>
      )}

      <Card size="small">
        <Table
          rowKey="id"
          size="small"
          loading={q.isLoading}
          dataSource={rows}
          columns={columns}
          rowSelection={{
            selectedRowKeys: picked,
            onChange: (keys) => setPicked(keys as string[]),
            getCheckboxProps: (r: AlertRow) => ({ disabled: r.is_read }),
          }}
          pagination={{ pageSize: 25, hideOnSinglePage: true }}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={
                  <Space direction="vertical" size={2}>
                    <Text>{scope === 'unread' ? t('alerts.empty_unread') : t('alerts.empty_all')}</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {t('alerts.empty_hint')}
                    </Text>
                  </Space>
                }
              />
            ),
          }}
        />
      </Card>

      {/* The quiet first cycle is the single most likely reason somebody
          stands in front of an empty list and concludes the feature is
          broken. Saying it here costs one line and saves a support ticket. */}
      {rows.length === 0 && !q.isLoading && (
        <AntAlert
          type="info"
          showIcon
          style={{ marginTop: 16 }}
          message={t('alerts.baseline_title')}
          description={t('alerts.baseline_body')}
        />
      )}

      {scope === 'all' && unreadTotal > 0 && (
        <Button style={{ marginTop: 16 }} onClick={() => markRead.mutate({ read: true })}
                loading={markRead.isPending}>
          {t('alerts.mark_all', { n: unreadTotal })}
        </Button>
      )}
    </div>
  )
}

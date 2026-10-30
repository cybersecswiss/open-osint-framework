import { useParams, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import LoadFailed from '../components/LoadFailed'
import {
  Card, Typography, Space, Button, Tag, Progress, Descriptions, Alert,
  Statistic, Row, Col, Spin, Empty, Table, Popconfirm, message,
} from 'antd'
import {
  ArrowLeftOutlined, EyeOutlined, ReloadOutlined, StopOutlined,
  CheckCircleTwoTone, CloseCircleTwoTone, ClockCircleTwoTone, WarningTwoTone,
  StopTwoTone,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { searchApi } from '../api/client'
import { searchProgressPercent } from '../utils/progress'
import { durationMs, formatDateTime } from '../utils/datetime'

// Dedicated, bookmarkable URL for a
// search job. Polls /search/{id} every 3 s while the job is running;
// stops as soon as it reaches a terminal state. WebSocket-style live
// updates would require backend support — until then, polling.

const STATUS_INFO: Record<string, { color: string; icon: any; percent: number }> = {
  queued:    { color: 'default', icon: <ClockCircleTwoTone twoToneColor="#999" />,   percent: 5 },
  running:   { color: 'processing', icon: <Spin size="small" />,                      percent: 50 },
  completed: { color: 'success', icon: <CheckCircleTwoTone twoToneColor="#52c41a" />, percent: 100 },
  partial:   { color: 'warning', icon: <WarningTwoTone twoToneColor="#faad14" />,     percent: 100 },
  failed:    { color: 'error',   icon: <CloseCircleTwoTone twoToneColor="#ff4d4f" />, percent: 100 },
  // Stopped by the investigator. Deliberately NOT the error styling: what
  // the tools already found is in the case, and "we stopped looking" is a
  // different statement from "the search failed".
  cancelled: { color: 'default', icon: <StopTwoTone twoToneColor="#8c8c8c" />,        percent: 100 },
}

const TERMINAL = new Set(['completed', 'partial', 'failed', 'cancelled'])

export default function SearchProgress() {
  const { t } = useTranslation()
  const { job_id } = useParams<{ job_id: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()

  const { data: job, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['search-job', job_id],
    queryFn: () => searchApi.status(job_id!),
    enabled: !!job_id,
    // Poll while non-terminal; stop once status is final.
    refetchInterval: (q) => {
      const status = (q.state.data as any)?.status
      return status && TERMINAL.has(status) ? false : 3000
    },
    // Keep polling even when the tab is in the background so a search
    // the user switched away from still updates and reaches its terminal
    // state (the server-side job runs regardless — this keeps the UI live).
    refetchIntervalInBackground: true,
  })

  const cancelMut = useMutation({
    mutationFn: () => searchApi.cancel(job_id!),
    onSuccess: (res: any) => {
      // `cancelled: false` means the job had already reached a terminal
      // state between the render and the click — no error, just say what
      // actually happened instead of claiming it was stopped.
      if (res?.cancelled === false) message.info(t('search_progress.cancel_too_late'))
      else message.success(t('search_progress.cancel_done'))
      qc.invalidateQueries({ queryKey: ['search-job', job_id] })
    },
    onError: (e: any) =>
      message.error(e?.response?.data?.detail || t('search_progress.cancel_failed')),
  })

  if (isLoading) return <Spin />
  // These two were one branch, and the wrong one won: a network error
  // rendered "job not found", telling an investigator their search had
  // vanished while it was still running on the server. The job is a
  // background task entirely independent of this view.
  if (isError) {
    return <LoadFailed what={t('loadfail.what.job')} loading={isFetching}
                       onRetry={() => refetch()} />
  }
  if (!job) return <Empty description={t('search_progress.not_found')} />

  const info = STATUS_INFO[job.status] || STATUS_INFO.queued
  const isTerminal = TERMINAL.has(job.status)
  const elapsedMs = job.started_at
    ? (durationMs(job.started_at, job.completed_at) ?? 0)
    : 0
  const elapsedSec = Math.round(elapsedMs / 1000)

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>
          {t('search_progress.back')}
        </Button>
        {job.case_id && (
          <Button icon={<EyeOutlined />} onClick={() => navigate(`/cases/${job.case_id}`)}>
            {t('search_progress.go_to_case')}
          </Button>
        )}
        <Button icon={<ReloadOutlined />} loading={isFetching && !isTerminal} onClick={() => refetch()}>
          {t('search_progress.refresh')}
        </Button>
        {/* Only while it is actually running. A search used to be
            unstoppable: the slowest tool decided when the investigator got
            their results back, and a source sitting at its five-minute
            timeout held the whole run. Everything found so far is already
            in the case, which is what the confirmation says. */}
        {!isTerminal && (
          <Popconfirm
            title={t('search_progress.cancel_confirm_title')}
            description={t('search_progress.cancel_confirm_body')}
            okText={t('search_progress.cancel_ok')}
            cancelText={t('search_progress.cancel_keep')}
            okButtonProps={{ danger: true }}
            onConfirm={() => cancelMut.mutate()}
          >
            <Button danger icon={<StopOutlined />} loading={cancelMut.isPending}>
              {t('search_progress.cancel')}
            </Button>
          </Popconfirm>
        )}
      </Space>

      <Typography.Title level={3} style={{ marginTop: 0 }}>
        {t('search_progress.title')}
      </Typography.Title>

      <Card style={{ marginBottom: 16 }}>
        <Space size="large" align="center" style={{ marginBottom: 16 }}>
          <span style={{ fontSize: 24 }}>{info.icon}</span>
          <div>
            <Tag color={info.color} style={{ fontSize: 14, padding: '2px 10px' }}>
              {String(t(`search_progress.status_${job.status}`, job.status))}
            </Tag>
            <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 2 }}>
              {isTerminal
                ? t('search_progress.took_seconds', { sec: elapsedSec })
                : t('search_progress.running_for', { sec: elapsedSec })}
            </div>
          </div>
        </Space>
        <Progress
          percent={searchProgressPercent(job.tool_progress, job.status, isTerminal)}
          status={
            job.status === 'failed' ? 'exception' :
            job.status === 'completed' ? 'success' :
            // 'normal' and not 'active': an animated bar on a stopped job
            // reads as "still working".
            job.status === 'partial' || job.status === 'cancelled' ? 'normal' : 'active'
          }
          strokeColor={
            job.status === 'partial' ? '#faad14' : undefined
          }
        />
        {!isTerminal && (job.tool_progress || []).length > 0 && (
          <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>
            {t('search_progress.tools_done', {
              done: (job.tool_progress || []).filter((x: any) =>
                ['success', 'partial', 'error'].includes(x.status)).length,
              total: (job.tool_progress || []).length,
            })}
          </div>
        )}
      </Card>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={12}>
          <Card><Statistic title={t('search_progress.entities')} value={job.case_entity_count ?? 0} /></Card>
        </Col>
        <Col span={12}>
          <Card><Statistic title={t('search_progress.edges')} value={job.case_edge_count ?? 0} /></Card>
        </Col>
      </Row>

      {job.error_message && (
        <Alert
          type={job.status === 'partial' ? 'warning' : 'error'}
          message={t('search_progress.error_message_label')}
          description={<pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{job.error_message}</pre>}
          style={{ marginBottom: 16 }}
          showIcon
        />
      )}

      <Card title={t('search_progress.detail_card_title')}>
        <Descriptions size="small" column={2}>
          <Descriptions.Item label={t('search_progress.field_query')}>
            <code>{job.query}</code>
          </Descriptions.Item>
          <Descriptions.Item label={t('search_progress.field_query_type')}>
            <Tag>{job.query_type}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label={t('search_progress.field_modules')} span={2}>
            <Space wrap>
              {(job.modules_used || []).length === 0
                ? <span style={{ color: '#999' }}>—</span>
                : (job.modules_used || []).map((m: string) => (
                    <Tag key={m} color="blue">{m}</Tag>
                  ))}
            </Space>
          </Descriptions.Item>
          <Descriptions.Item label={t('search_progress.field_started_at')}>
            {formatDateTime(job.started_at)}
          </Descriptions.Item>
          <Descriptions.Item label={t('search_progress.field_completed_at')}>
            {formatDateTime(job.completed_at)}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* Per-tool live progress table — populated by the orchestrator's
          on_progress callback into SearchJob.tool_progress. Polled every
          3s alongside the rest of the job state. */}
      {(job.tool_progress || []).length > 0 && (
        <Card
          title={t('search_progress.tool_progress_title')}
          style={{ marginTop: 16 }}
          size="small"
        >
          <Table
            size="small"
            pagination={false}
            rowKey={(r: any) => `${r.module}:${r.tool}`}
            dataSource={job.tool_progress}
            columns={[
              {
                title: t('search_progress.tp_module'),
                dataIndex: 'module',
                render: (m: string) => <Tag color="blue">{m}</Tag>,
              },
              {
                title: t('search_progress.tp_tool'),
                dataIndex: 'tool',
                render: (v: string) => <code>{v}</code>,
              },
              {
                title: t('search_progress.tp_status'),
                dataIndex: 'status',
                render: (s: string) => {
                  const m: Record<string, string> = {
                    pending: 'default', running: 'processing',
                    success: 'success', partial: 'warning', error: 'error',
                  }
                  return <Tag color={m[s] || 'default'}>{s}</Tag>
                },
              },
              {
                title: t('search_progress.tp_findings'),
                dataIndex: 'findings',
                align: 'right',
              },
              {
                title: t('search_progress.tp_edges'),
                dataIndex: 'edges',
                align: 'right',
              },
              {
                title: t('search_progress.tp_duration'),
                dataIndex: 'duration_seconds',
                align: 'right',
                render: (s: number) => s ? `${s.toFixed(1)}s` : '—',
              },
              {
                title: t('search_progress.tp_errors'),
                dataIndex: 'errors',
                render: (errs: string[], record: any) => {
                  if (errs?.length) return <span style={{ color: '#fa541c', fontSize: 12 }}>
                      {errs[0].length > 80 ? errs[0].slice(0, 80) + '…' : errs[0]}
                    </span>
                  const notes = record?.notes as string[] | undefined
                  if (notes?.length) return <span style={{ color: '#8c8c8c', fontSize: 12 }}>
                      ℹ {notes[0].length > 80 ? notes[0].slice(0, 80) + '…' : notes[0]}
                    </span>
                  return <span style={{ color: '#999' }}>—</span>
                },
              },
            ]}
          />
        </Card>
      )}

      {!isTerminal && (
        <Alert
          type="info"
          showIcon
          style={{ marginTop: 16 }}
          message={t('search_progress.polling_note')}
        />
      )}
    </div>
  )
}

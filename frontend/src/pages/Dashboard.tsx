import { Row, Col, Card, Statistic, List, Tag, Typography, Button, Tooltip, Space, Alert } from 'antd'
import { PlusOutlined, InfoCircleOutlined, FolderOpenOutlined, ReloadOutlined, BellOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { alertsApi, casesApi, monitoringApi } from '../api/client'
import { useNavigate } from 'react-router-dom'
import { formatDate } from '../utils/datetime'
import LoadFailed from '../components/LoadFailed'

const { Text } = Typography

export default function Dashboard() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const casesQ = useQuery({ queryKey: ['cases'], queryFn: casesApi.list })
  // "Which of my cases moved?" — the question at eight in the morning. The
  // situation report on /lagebild answers what happened in the world; this
  // answers what happened in MY work. Busy cases first, then the quiet ones
  // going cold, which are invisible everywhere else today.
  const overviewQ = useQuery({
    queryKey: ['cases-overview'], queryFn: casesApi.overview, staleTime: 60_000,
  })
  const monitoringQ = useQuery({ queryKey: ['monitoring'], queryFn: monitoringApi.list })
  // The tile was once hard-wired to 0 because nothing wrote an alert.
  // Now that the alert chain exists, a 0 is a statement rather than a placeholder,
  // which is the whole difference between a useful tile and a decorative one.
  const alertsQ = useQuery({
    queryKey: ['alerts', 'unread'],
    queryFn: () => alertsApi.list(true, 200),
    staleTime: 60_000,
  })

  const cases = casesQ.data ?? []
  const overview = overviewQ.data
  const monitorings = monitoringQ.data ?? []

  // Loading and failure must not look like "you have nothing". Unpacking the
  // queries with `= []` meant the first screen after login confidently showed
  // "0 active cases" and an empty list in all three situations — and the
  // obvious reading of the third is that one's own cases are gone.
  const failed = [casesQ, overviewQ, monitoringQ, alertsQ].filter((q) => q.isError)
  const retryAll = () => {
    casesQ.refetch(); overviewQ.refetch(); monitoringQ.refetch(); alertsQ.refetch()
  }

  const openCases = cases.filter((c: any) => c.status === 'open').length
  const activeMonitorings = monitorings.filter((m: any) => m.is_active !== false).length
  // Shown next to the alerts tile. Running searches are
  // real, already in this response, and answer a question an investigator
  // actually has on landing: is anything still working for me right now?
  const runningSearches = (overview?.cases || [])
    .reduce((n: number, c: any) => n + (c.running_searches || 0), 0)
  const unreadAlerts = alertsQ.data?.alerts?.length ?? 0

  return (
    <div>
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 16 }} align="start">
        <Typography.Title level={3} style={{ margin: 0 }}>{t('dashboard.title')}</Typography.Title>
        <Button type="primary" size="large" icon={<PlusOutlined />} onClick={() => navigate('/search')}>
          {t('dashboard.start_search')}
        </Button>
      </Space>
      {failed.length > 0 && (
        <LoadFailed compact what={t('loadfail.what.dash')}
                    hint={t('dashboard.load_failed_hint')} onRetry={retryAll} />
      )}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} md={6}>
          <Card>
            <Statistic
              title={t('dashboard.active_cases')}
              value={openCases}
              loading={casesQ.isLoading}
              prefix={<FolderOpenOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card>
            <Statistic
              title={
                <Space size={4}>
                  {t('dashboard.running_searches')}
                  <Tooltip title={t('dashboard.running_tooltip')}>
                    <InfoCircleOutlined style={{ color: '#999' }} />
                  </Tooltip>
                </Space>
              }
              value={runningSearches}
              loading={overviewQ.isLoading}
              valueStyle={runningSearches ? { color: '#1677ff' } : undefined}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card>
            <Statistic title={t('dashboard.monitored')} value={activeMonitorings}
                       loading={monitoringQ.isLoading} />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card
            hoverable={unreadAlerts > 0}
            // To the LIST, not to one case. The tile used to open whichever
            // case happened to hold the newest alert, which is only the
            // right answer when there is exactly one case involved.
            onClick={unreadAlerts > 0 ? () => navigate('/alerts') : undefined}
            style={unreadAlerts > 0 ? { cursor: 'pointer' } : undefined}
          >
            <Statistic
              title={
                <Space size={4}>
                  {t('dashboard.unread_alerts')}
                  <Tooltip title={t('dashboard.alerts_tooltip')}>
                    <InfoCircleOutlined style={{ color: '#999' }} aria-hidden="true" />
                  </Tooltip>
                </Space>
              }
              value={unreadAlerts}
              loading={alertsQ.isLoading}
              prefix={<BellOutlined aria-hidden="true" />}
              valueStyle={unreadAlerts ? { color: '#cf1322' } : undefined}
            />
          </Card>
        </Col>
      </Row>
      {(overview?.cases?.length ?? 0) > 0 && (
        <Card size="small" style={{ marginBottom: 16 }}
              title={t('dashboard.moved_title')}>
          <List
            size="small"
            dataSource={(overview?.cases || []).slice(0, 8)}
            renderItem={(c: any) => (
              <List.Item
                style={{ cursor: 'pointer' }}
                onClick={() => navigate(`/cases/${c.id}`)}
                actions={[
                  c.alerts ? <Tag color="red" key="a">{t('dashboard.moved_alerts', { n: c.alerts })}</Tag> : null,
                  c.running_searches ? <Tag color="processing" key="r">{t('dashboard.moved_running')}</Tag> : null,
                  // A case nobody has touched for weeks is not visible
                  // anywhere today. Silence is also a state worth seeing.
                  c.stale_days >= 7 ? <Tag key="s">{t('dashboard.moved_stale', { d: c.stale_days })}</Tag> : null,
                ].filter(Boolean) as any}
              >
                <Space direction="vertical" size={0}>
                  <Space size={6}>
                    <Text strong>{c.case_number}</Text>
                    <Text>{c.title}</Text>
                  </Space>
                  {c.last_search && (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {t('dashboard.moved_last', {
                        q: c.last_search.query,
                        n: c.last_search.entities ?? 0,
                      })}
                    </Text>
                  )}
                </Space>
              </List.Item>
            )}
          />
        </Card>
      )}

      <Card
        title={t('dashboard.active_cases_list')}
        extra={cases.length > 5
          ? <Button type="link" onClick={() => navigate('/cases')}>{t('dashboard.view_all_cases')}</Button>
          : null}
      >
        <List
          loading={casesQ.isLoading}
          locale={{ emptyText: casesQ.isError
            ? t('dashboard.list_unavailable') : t('dashboard.no_cases') }}
          dataSource={cases.slice(0, 5)}
          renderItem={(c: any) => (
            <List.Item
              onClick={() => navigate(`/cases/${c.id}`)}
              style={{ cursor: 'pointer' }}
              extra={<Tag color={c.status === 'open' ? 'green' : 'default'}>{String(t(`cases.status_${c.status}`, c.status))}</Tag>}
            >
              <List.Item.Meta
                title={`${c.case_number} — ${c.title}`}
                description={`${t(`cases.priority_${c.priority}`, c.priority)} | ${formatDate(c.created_at)}`}
              />
            </List.Item>
          )}
        />
      </Card>
    </div>
  )
}

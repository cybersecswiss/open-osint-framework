import { Card, Tag, Space, Typography, Row, Col, Tooltip, Button, Alert } from 'antd'
import { ReloadOutlined, LineChartOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { platformApi } from '../../api/client'
import LoadFailed from '../LoadFailed'

const { Text } = Typography

/**
 * "Is the machine under me healthy?" — the operator's own question.
 *
 * The console could answer everything about the tenants and nothing about
 * the framework running beneath it. Postgres, Redis, the licence server and
 * the fourteen module containers were visible only over SSH, and Grafana —
 * which is deployed, running and reachable at /grafana/ — was linked from
 * nowhere in the application.
 *
 * Two rules this panel follows:
 *
 *   * **A failed fetch is never a green light.** `LoadFailed` rather than a
 *     reassuring "all ok" — the same defect the four confident zeros on this
 *     very page had.
 *   * **A module that answers /health but delivered no manifest is NOT ok.**
 *     It contributes zero tools to a search while looking perfectly alive
 *     from the outside; the backend marks it `degraded` and says why.
 */
const COLORS: Record<string, string> = {
  ok: 'green', degraded: 'orange', down: 'red',
}

export default function SystemHealthPanel() {
  const { t } = useTranslation()
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['platform-system-health'],
    queryFn: platformApi.systemHealth,
    refetchInterval: 60_000,
  })

  if (isError) {
    return (
      <Card size="small" title={t('glbadmin.health.title')} style={{ marginBottom: 16 }}>
        <LoadFailed what={t('loadfail.what.system_health')}
                    onRetry={() => refetch()} loading={isFetching} />
      </Card>
    )
  }

  const problems = data
    ? [...data.problems.infra, ...data.problems.down, ...data.problems.degraded]
    : []

  return (
    <Card
      size="small"
      loading={isLoading}
      style={{ marginBottom: 16 }}
      title={
        <Space>
          {t('glbadmin.health.title')}
          {data && (
            <Tag color={COLORS[data.status] || 'default'}>
              {t(`glbadmin.health.status_${data.status}`)}
            </Tag>
          )}
        </Space>
      }
      extra={
        <Space>
          <Tooltip title={t('glbadmin.health.grafana_hint')}>
            <Button size="small" icon={<LineChartOutlined />}
                    href={data?.grafana_url || '/grafana/'} target="_blank" rel="noreferrer">
              {t('glbadmin.health.grafana')}
            </Button>
          </Tooltip>
          <Button size="small" icon={<ReloadOutlined />} loading={isFetching}
                  onClick={() => refetch()} aria-label={t('audit.refresh')} />
        </Space>
      }
    >
      {data && problems.length > 0 && (
        <Alert type={data.status === 'down' ? 'error' : 'warning'} showIcon
               style={{ marginBottom: 12 }}
               message={t('glbadmin.health.problem_summary', { list: problems.join(', ') })} />
      )}

      <Row gutter={[8, 8]} style={{ marginBottom: 12 }}>
        {data && Object.entries(data.infra).map(([name, state]) => (
          <Col key={name}>
            <Tag color={state === 'ok' ? 'green' : 'red'}>
              {name}{state === 'ok' ? '' : ` — ${state}`}
            </Tag>
          </Col>
        ))}
      </Row>

      <Text type="secondary" style={{ fontSize: 12 }}>
        {t('glbadmin.health.modules_line', {
          ok: data?.modules_ok ?? 0,
          total: data?.modules_total ?? 0,
          tools: data?.tools_total ?? 0,
        })}
      </Text>
      <div style={{ marginTop: 8 }}>
        <Space wrap size={[4, 4]}>
          {(data?.modules ?? []).map((m) => (
            <Tooltip key={m.name}
                     title={m.detail || t('glbadmin.health.tools_n', { count: m.tools })}>
              <Tag color={COLORS[m.status] || 'default'}>
                {m.name} · {m.tools}
              </Tag>
            </Tooltip>
          ))}
        </Space>
      </div>
    </Card>
  )
}

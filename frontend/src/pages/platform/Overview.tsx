import { Typography, Row, Col, Card, Statistic, Space, Tag, Alert, Spin } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { platformApi } from '../../api/client'
import LoadFailed from '../../components/LoadFailed'
import SystemHealthPanel from '../../components/platform/SystemHealthPanel'

const { Title, Paragraph } = Typography

export default function Overview() {
  const { t } = useTranslation()
  const { data: m, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['platform-metrics'], queryFn: platformApi.metrics,
  })

  return (
    <div>
      <Title level={3} style={{ marginTop: 0 }}>{t('glbadmin.overview_title')}</Title>
      <Paragraph type="secondary">{t('glbadmin.subtitle')}</Paragraph>

      {/*
        Four confident zeros used to be this page's answer to a failed
        request: `value={m?.tenants_expiring_30d ?? 0}` and no error path at
        all. "0 licences expiring in 30 days" is the number the operator
        checks to decide whether any tenant needs renewing, and a broken
        fetch rendered it as the most reassuring possible reading — nothing
        needs you — on the one page whose job is to raise its hand.

        The same defect existed on the tenant dashboard ("0 open alerts").
      */}
      {isLoading && <Spin />}
      {isError && (
        <LoadFailed what={t('loadfail.what.metrics')}
                    onRetry={() => refetch()} loading={isFetching} />
      )}

      {!isLoading && !isError && (
      <>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={12} md={6}><Card size="small"><Statistic title={t('glbadmin.stat_total')} value={m?.tenants_total ?? 0} /></Card></Col>
        <Col xs={12} md={6}><Card size="small"><Statistic title={t('glbadmin.stat_active')} value={m?.tenants_active ?? 0} valueStyle={{ color: '#52c41a' }} /></Card></Col>
        <Col xs={12} md={6}><Card size="small"><Statistic title={t('glbadmin.stat_expiring')} value={m?.tenants_expiring_30d ?? 0} valueStyle={{ color: '#faad14' }} /></Card></Col>
        <Col xs={12} md={6}><Card size="small"><Statistic title={t('glbadmin.stat_expired')} value={m?.tenants_expired ?? 0} valueStyle={{ color: '#ff4d4f' }} /></Card></Col>
      </Row>

      {/* The framework's own state: without it this console could answer
          everything about the tenants and nothing about the machine under
          it — Grafana was deployed but linked from nowhere. */}
      <SystemHealthPanel />

      <Card size="small" title={t('glbadmin.modules_loaded')} style={{ marginBottom: 16 }}>
        <Space wrap>
          {(m?.modules_loaded ?? []).map((mod) => <Tag key={mod} color="blue">{mod}</Tag>)}
          {(!m || m.modules_loaded.length === 0) && <span style={{ color: '#999' }}>—</span>}
        </Space>
      </Card>
      </>
      )}

      <Alert type="info" showIcon message={t('glbadmin.boundary_title')} description={t('glbadmin.boundary_desc')} />
    </div>
  )
}

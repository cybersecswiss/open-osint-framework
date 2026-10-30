import { Alert, Button, List, Space, Spin, Tag, Typography } from 'antd'
import {
  CheckCircleFilled, CloseCircleFilled, ExclamationCircleFilled, InfoCircleFilled, ReloadOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { tenantApi, type SelfTestCheck } from '../../api/client'
import { formatDateTime } from '../../utils/datetime'

const { Text } = Typography

const ICON: Record<SelfTestCheck['status'], JSX.Element> = {
  ok: <CheckCircleFilled style={{ color: '#52c41a', fontSize: 18 }} />,
  warn: <ExclamationCircleFilled style={{ color: '#faad14', fontSize: 18 }} />,
  fail: <CloseCircleFilled style={{ color: '#ff4d4f', fontSize: 18 }} />,
  info: <InfoCircleFilled style={{ color: '#1677ff', fontSize: 18 }} />,
}

/**
 * "Is our installation working?" — one line per component, each with a
 * sentence the admin can act on. Read-only: health and configuration, never
 * case data (backend services/selftest.py).
 */
export default function SelfTest() {
  const { t } = useTranslation()
  const q = useQuery({ queryKey: ['selftest'], queryFn: tenantApi.selftest, retry: false })

  const text = (c: SelfTestCheck) => {
    const reason = c.params.reason ? `_${c.params.reason}` : ''
    const key = `selftest.${c.key}_${c.status}${reason}`
    const fallback = `selftest.${c.key}_${c.status}`
    const out = t(key, { ...c.params, defaultValue: '' })
    return out || t(fallback, { ...c.params, defaultValue: c.params.error || c.status })
  }

  return (
    <div style={{ maxWidth: 820 }}>
      <Space style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} onClick={() => q.refetch()} loading={q.isFetching}>
          {t('selftest.run')}
        </Button>
        {q.data && <Text type="secondary">{t('selftest.checked_at', { at: formatDateTime(q.data.checked_at) })}</Text>}
      </Space>
      {q.isLoading ? <Spin /> : q.isError ? (
        <Alert type="error" showIcon message={t('selftest.failed')} />
      ) : q.data && (
        <>
          <Alert
            style={{ marginBottom: 12 }}
            showIcon
            type={q.data.overall === 'ok' ? 'success' : q.data.overall === 'warn' ? 'warning' : 'error'}
            message={t(`selftest.overall_${q.data.overall}`)}
          />
          <List
            bordered
            dataSource={q.data.checks}
            renderItem={(c) => (
              <List.Item>
                <Space align="start">
                  {ICON[c.status]}
                  <Space direction="vertical" size={0}>
                    <Text strong>{t(`selftest.${c.key}`)}</Text>
                    <Text type={c.status === 'fail' ? 'danger' : undefined}>{text(c)}</Text>
                    {c.params.error && c.status !== 'ok' && (
                      <Text type="secondary" style={{ fontSize: 12 }}><Tag>{c.params.error}</Tag></Text>
                    )}
                  </Space>
                </Space>
              </List.Item>
            )}
          />
        </>
      )}
    </div>
  )
}

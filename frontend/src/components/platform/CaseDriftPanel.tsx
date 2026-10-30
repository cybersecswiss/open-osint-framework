import { useState } from 'react'
import {
  Alert, Button, Space, Table, Tag, Typography, Popconfirm, message, Empty,
} from 'antd'
import { ReloadOutlined, DeleteOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { platformApi } from '../../api/client'
import { formatDateTime } from '../../utils/datetime'

const { Text, Paragraph } = Typography

/**
 * Cases the customer's store holds that this framework has no record of.
 *
 * Why the operator console is where this lives: nobody else can see it. A
 * case that exists only on the agent has no entry in the framework, so it
 * appears in no tenant's case list — the investigator cannot reach it, and
 * the auto-delete routine, which iterates framework cases, never examines
 * it. Its findings outlive every retention rule, invisibly.
 *
 * Deliberately manual, and deliberately per case. Deleting investigation
 * data that has no counterpart here is a judgement about somebody else's
 * case file: it belongs to a person who confirms it, not to the cron job
 * that runs at 03:15. There is no "delete all" button for the same reason.
 *
 * The other direction — cases here with nothing on the agent — is listed
 * too but never offered for deletion: that is usually just a case nobody has
 * searched yet, and the framework row is the customer's own metadata.
 */
export default function CaseDriftPanel({ tenant }: { tenant: string }) {
  const { t } = useTranslation()
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const load = async () => {
    setLoading(true); setError('')
    try {
      setData(await platformApi.caseDrift(tenant))
    } catch (e: any) {
      // "Could not ask" must not render as "nothing to report" — the whole
      // point of this view is to surface a discrepancy.
      setError(e?.response?.data?.detail || t('drift.failed'))
      setData(null)
    } finally {
      setLoading(false)
    }
  }

  const remove = async (id: string) => {
    setBusy(true)
    try {
      const r = await platformApi.deleteOrphanCases(tenant, [id])
      if (r.deleted?.length) message.success(t('drift.deleted'))
      if (r.refused_still_in_framework?.length) message.warning(t('drift.refused'))
      if (r.failed?.length) message.error(r.failed[0]?.error || t('drift.failed'))
      await load()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || t('drift.failed'))
    } finally {
      setBusy(false)
    }
  }

  const orphans = data?.agent_only || []
  const fwOnly = data?.framework_only || []

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Space style={{ width: '100%', justifyContent: 'space-between' }} wrap>
        <Text strong>{t('drift.title')}</Text>
        <Button size="small" icon={<ReloadOutlined />} loading={loading}
                onClick={load}>{t('drift.check')}</Button>
      </Space>
      <Paragraph type="secondary" style={{ fontSize: 12, margin: 0 }}>
        {t('drift.intro')}
      </Paragraph>

      {error && <Alert type="error" showIcon message={error} />}

      {data && (
        <>
          <Space wrap>
            <Tag color={orphans.length ? 'red' : 'green'}>
              {t('drift.agent_only', { n: orphans.length })}
            </Tag>
            {orphans.length > 0 && (
              <Tag color="red">
                {t('drift.orphan_entities', { n: data.orphan_entities })}
              </Tag>
            )}
            <Tag>{t('drift.framework_only', { n: fwOnly.length })}</Tag>
            <Tag color="green">{t('drift.in_sync', { n: data.in_sync })}</Tag>
          </Space>

          {orphans.length === 0 && fwOnly.length === 0 && (
            <Empty description={t('drift.none')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}

          {orphans.length > 0 && (
            <>
              <Alert type="warning" showIcon message={t('drift.warn_head')}
                     description={t('drift.warn_body')} />
              <Table
                size="small" rowKey="id" pagination={false} dataSource={orphans}
                columns={[
                  // Case NUMBER, not title. The agent deliberately no longer
                  // ships titles for cases the framework has no record of —
                  // in police work the title is often the substance of the
                  // investigation, and this panel was the one place carrying
                  // it to the operator. A number and an id identify the
                  // bucket well enough to decide whether to delete it.
                  { title: t('drift.col_case'), dataIndex: 'case_number',
                    render: (v: string, r: any) => (
                      <Space direction="vertical" size={0}>
                        <Text style={{ fontSize: 12 }}>{v || t('drift.no_number')}</Text>
                        <Text type="secondary" style={{ fontSize: 11 }}>{r.id}</Text>
                      </Space>
                    ) },
                  { title: t('drift.col_created'), dataIndex: 'created_at', width: 150,
                    render: (v: string) => <Text style={{ fontSize: 12 }}>{formatDateTime(v)}</Text> },
                  { title: t('drift.col_rows'), width: 130,
                    render: (_: any, r: any) => (
                      <Text style={{ fontSize: 12 }}>
                        {t('drift.rows', { e: r.entities, k: r.edges })}
                      </Text>
                    ) },
                  { title: '', width: 60,
                    render: (_: any, r: any) => (
                      <Popconfirm
                        title={t('drift.confirm_title')}
                        description={t('drift.confirm_desc', { e: r.entities })}
                        okButtonProps={{ danger: true }}
                        okText={t('drift.confirm_ok')}
                        onConfirm={() => remove(r.id)}
                      >
                        <Button aria-label={t('a11y.delete_orphan_case')} size="small" danger icon={<DeleteOutlined />}
                                loading={busy} />
                      </Popconfirm>
                    ) },
                ]}
              />
            </>
          )}

          {fwOnly.length > 0 && (
            <Alert
              type="info" showIcon
              message={t('drift.fw_only_head', { n: fwOnly.length })}
              description={t('drift.fw_only_body')}
            />
          )}
        </>
      )}
    </Space>
  )
}

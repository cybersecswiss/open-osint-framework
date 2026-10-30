import { Alert, Card, Empty, Space, Spin, Table, Tag, Tooltip, Typography, Button } from 'antd'
import { AimOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { graphApi } from '../../api/client'
import LoadFailed from '../LoadFailed'
import { displayLabel } from '../../utils/label'

const { Text, Paragraph } = Typography

/**
 * "What in this case has never been asked about."
 *
 * Whether a node was FOUND is visible everywhere in the app; whether it was
 * ever ASKED ABOUT is recorded nowhere the investigator can see. A domain
 * that turned up in a certificate and was never scanned looks exactly like
 * one that was scanned and yielded nothing — so "did I miss something?" was
 * unanswerable.
 *
 * One property must stay visible here and is stated in the panel rather than
 * left to be inferred: **being unsearched is not evidence of anything.** It
 * means nobody has asked, not that there is something to find. A list of open
 * items that reads as a list of leads would be a worse defect than the gap it
 * closes.
 */
export default function WorklistPanel({
  caseId, onPivot,
}: {
  caseId: string
  onPivot?: (node: any) => void
}) {
  const { t } = useTranslation()
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['worklist', caseId],
    queryFn: () => graphApi.getWorklist(caseId),
    staleTime: 30_000,
  })

  if (isLoading) {
    return <div style={{ textAlign: 'center', padding: 48 }}><Spin /></div>
  }
  // A failed fetch used to fall through to the `!data` branch below and
  // render "nothing to do" — which is a STATEMENT about the case ("every
  // selector here has been asked about"), produced by a network error.
  // Same defect class as the "0 open alerts" tile and the operator
  // console's four confident zeros (see LoadFailed.tsx).
  if (isError) {
    return <LoadFailed what={t('loadfail.what.worklist')}
                       onRetry={() => refetch()} loading={isFetching} />
  }
  if (!data) return <Empty description={t('worklist.empty')} style={{ padding: 48 }} />

  return (
    <Card size="small">
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Alert
          type="info"
          showIcon
          message={t('worklist.headline', {
            searched: data.searched, count: data.total ?? data.candidates,
          })}
          description={
            <Paragraph style={{ margin: 0 }}>
              {t('worklist.note')}
              {/* The list is capped. Saying so matters: without it the
                  headline number and the row count silently disagree, and a
                  truncation reads as "that is all there is". */}
              {data.truncated && (
                <> {t('worklist.truncated', {
                  shown: data.candidates, total: data.total })}</>
              )}
            </Paragraph>
          }
        />
        {data.items?.length === 0 ? (
          <Empty description={t('worklist.all_done')} style={{ padding: 24 }} />
        ) : (
          <Table
            size="small"
            rowKey="id"
            dataSource={data.items}
            pagination={data.items.length > 20 ? { pageSize: 20, size: 'small' } : false}
            columns={[
              {
                title: t('worklist.col_selector'),
                dataIndex: 'label',
                render: (v: string, row: any) => (
                  <Space size={6}>
                    <Text style={{ wordBreak: 'break-all' }}>
                      {displayLabel(row.entity_type, v) || v}
                    </Text>
                    {/* No tool reported this as a finding — it turned up as
                        the far end of a relation (the counterparty of a
                        transaction, the host an MX record points at). Still a
                        real selector, but less substantiated, and saying so
                        is the difference between a lead and a claim. */}
                    {row.from_relation && (
                      <Tooltip title={t('worklist.from_relation_hint')}>
                        <Tag style={{ marginInlineEnd: 0, fontSize: 11 }}>
                          {t('worklist.from_relation')}
                        </Tag>
                      </Tooltip>
                    )}
                    {/* Same rating chips as everywhere else — one visual
                        language for "how well is this supported". */}
                    {row.admiralty && (
                      <Tooltip title={t('graph.admiralty_hint')}>
                        <Tag color={(row.corroborated_by?.length || 0) > 1 ? 'green' : undefined}
                             style={{ marginInlineEnd: 0, fontSize: 11 }}>
                          {row.admiralty}
                        </Tag>
                      </Tooltip>
                    )}
                    {(row.corroborated_by?.length || 0) > 1 && (
                      <Tooltip title={row.corroborated_by.join(', ')}>
                        <span style={{ color: '#389e0d', fontSize: 12 }}>
                          ✓ {row.corroborated_by.length}
                        </span>
                      </Tooltip>
                    )}
                  </Space>
                ),
              },
              {
                title: t('worklist.col_as'),
                dataIndex: 'query_type',
                width: 130,
                render: (v: string) => <Tag>{t(`search.type_${v}`, { defaultValue: v })}</Tag>,
              },
              {
                title: t('worklist.col_tools'),
                dataIndex: 'tool_count',
                width: 110,
                render: (n: number, row: any) => (
                  <Tooltip title={(row.tools || []).join(', ')}>
                    <Text type="secondary">{t('worklist.tools_n', { count: n })}</Text>
                  </Tooltip>
                ),
              },
              {
                title: '',
                key: 'act',
                width: 60,
                render: (_: any, row: any) => (
                  <Tooltip title={t('pivot.button')}>
                    <Button aria-label={t('pivot.button')}
                      size="small" type="text" icon={<AimOutlined />}
                      onClick={() => onPivot?.({
                        entity_type: row.entity_type, label: row.label, data: {},
                      })}
                    />
                  </Tooltip>
                ),
              },
            ]}
          />
        )}
      </Space>
    </Card>
  )
}

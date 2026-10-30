import { Alert, Card, Empty, Space, Spin, Table, Tag, Tooltip, Typography } from 'antd'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { graphApi } from '../../api/client'
import { displayLabel } from '../../utils/label'
import { formatDateTime } from '../../utils/datetime'

const { Text, Paragraph } = Typography

/**
 * "What changed since the last run" for an open case.
 *
 * Deterministic ids make a re-scan idempotent, which is correct but hides the
 * one thing an investigator on a running case actually wants: the additions.
 * The backend answers that at GET /cases/{id}/delta; this is its surface.
 *
 * Two properties of the data are load-bearing and must stay visible here:
 *
 *  * **Additions only.** Removals are not tracked — a tool that merely failed
 *    and a genuine takedown are indistinguishable in this pipeline. The panel
 *    states that rather than showing an empty "removed" column, which would
 *    read as "nothing disappeared".
 *  * **Re-confirmations are not additions.** The gap-fill ingest touches
 *    provenance on existing rows on every run; counting those as new would
 *    make every re-scan look like a discovery.
 */
export default function DeltaPanel({
  caseId, onSelect,
}: {
  caseId: string
  onSelect?: (node: any) => void
}) {
  const { t } = useTranslation()
  const { data, isLoading, error } = useQuery({
    queryKey: ['delta', caseId],
    queryFn: () => graphApi.getDelta(caseId),
    enabled: !!caseId,
  })

  if (isLoading) return <Spin style={{ display: 'block', margin: '48px auto' }} />
  if (error) return <Alert type="error" showIcon message={t('delta.load_failed')} />
  if (!data) return null

  // No search has ever run on this case — a different situation from "the last
  // run found nothing new", and worth saying so explicitly.
  if (!data.job) {
    return <Empty description={t('delta.no_search_yet')} />
  }

  const fmt = (s?: string | null) => formatDateTime(s)
  const nEnt = data.counts?.entities ?? data.entities.length
  const nEdg = data.counts?.edges ?? data.edges.length

  // Edge endpoints arrive as ids; resolve to a label where the entity came
  // with the delta, otherwise show the id rather than inventing a name.
  const labelById = new Map<string, any>(data.entities.map((e: any) => [e.id, e]))
  const endpoint = (id: string) => {
    const e = labelById.get(id)
    return e ? (displayLabel(e.entity_type, e.label) || e.id) : id
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card size="small">
        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          <Space wrap>
            <Text strong>{t('delta.last_run')}:</Text>
            <Text code>{data.job.query}</Text>
            <Tag>{data.job.query_type}</Tag>
            <Text type="secondary">{fmt(data.job.started_at)}</Text>
            {data.job.status !== 'completed' && <Tag color="orange">{data.job.status}</Tag>}
          </Space>
          {data.previous_job ? (
            <Text type="secondary">
              {t('delta.compared_to', {
                query: data.previous_job.query, when: fmt(data.previous_job.started_at),
              })}
            </Text>
          ) : (
            <Text type="secondary">{t('delta.first_run')}</Text>
          )}
          <Space size={16} style={{ marginTop: 4 }}>
            <Text><Text strong style={{ fontSize: 18 }}>{nEnt}</Text> {t('delta.new_entities')}</Text>
            <Text><Text strong style={{ fontSize: 18 }}>{nEdg}</Text> {t('delta.new_edges')}</Text>
          </Space>
        </Space>
      </Card>

      {/* The honesty note travels from the backend, which owns the caveat. */}
      <Alert type="info" showIcon message={data.note || t('delta.additions_only')} />

      {nEnt === 0 && nEdg === 0 ? (
        <Empty description={t('delta.nothing_new')} />
      ) : (
        <>
          {nEnt > 0 && (
            <Card size="small" title={t('delta.new_entities_title', { count: nEnt })}>
              <Table
                size="small"
                rowKey="id"
                dataSource={data.entities}
                pagination={data.entities.length > 25 ? { pageSize: 25 } : false}
                onRow={(row) => ({
                  onClick: () => onSelect?.(row),
                  style: onSelect ? { cursor: 'pointer' } : undefined,
                })}
                columns={[
                  {
                    title: t('delta.col_type'), dataIndex: 'entity_type', width: 150,
                    render: (v: string) => <Tag>{v}</Tag>,
                  },
                  {
                    title: t('delta.col_label'), dataIndex: 'label',
                    render: (_: any, r: any) => (
                      <Text style={{ wordBreak: 'break-all' }}>
                        {displayLabel(r.entity_type, r.label) || r.id}
                      </Text>
                    ),
                  },
                  {
                    title: t('delta.col_rating'), dataIndex: 'admiralty', width: 90,
                    render: (v: string, r: any) => v ? (
                      <Tooltip title={t('graph.admiralty_hint')}>
                        <Tag color={(r.corroborated_by?.length || 0) > 1 ? 'green' : undefined}>
                          {v}
                        </Tag>
                      </Tooltip>
                    ) : <Text type="secondary">—</Text>,
                  },
                  {
                    title: t('delta.col_source'), dataIndex: 'source', width: 170,
                    render: (v: string, r: any) => (
                      <Space size={4} wrap>
                        <Text type="secondary" style={{ fontSize: 12 }}>{v || '—'}</Text>
                        {(r.corroborated_by?.length || 0) > 1 && (
                          <Tooltip title={r.corroborated_by.join(', ')}>
                            <span style={{ color: '#389e0d', fontSize: 12 }}>
                              ✓ {r.corroborated_by.length}
                            </span>
                          </Tooltip>
                        )}
                      </Space>
                    ),
                  },
                  {
                    title: t('delta.col_evidence'), dataIndex: 'url', width: 110,
                    render: (v: string) => v ? (
                      <a href={v} target="_blank" rel="noreferrer"
                         onClick={(e) => e.stopPropagation()}>
                        {t('delta.open_source')}
                      </a>
                    ) : <Text type="secondary">—</Text>,
                  },
                ]}
              />
            </Card>
          )}

          {nEdg > 0 && (
            <Card size="small" title={t('delta.new_edges_title', { count: nEdg })}>
              <Table
                size="small"
                rowKey="id"
                dataSource={data.edges}
                pagination={data.edges.length > 25 ? { pageSize: 25 } : false}
                columns={[
                  {
                    title: t('delta.col_from'), dataIndex: 'from_entity',
                    render: (v: string) => <Text style={{ wordBreak: 'break-all' }}>{endpoint(v)}</Text>,
                  },
                  {
                    title: t('delta.col_relation'), dataIndex: 'relation_type', width: 190,
                    render: (v: string) => <Tag color="default">{v}</Tag>,
                  },
                  {
                    title: t('delta.col_to'), dataIndex: 'to_entity',
                    render: (v: string) => <Text style={{ wordBreak: 'break-all' }}>{endpoint(v)}</Text>,
                  },
                  {
                    title: t('delta.col_source'), dataIndex: 'source', width: 170,
                    render: (v: string) => (
                      <Text type="secondary" style={{ fontSize: 12 }}>{v || '—'}</Text>
                    ),
                  },
                ]}
              />
            </Card>
          )}
        </>
      )}

      <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }}>
        {t('delta.boundary_hint', { when: fmt(data.since) })}
      </Paragraph>
    </Space>
  )
}

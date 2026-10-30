import { useMemo, useState } from 'react'
import { Card, Timeline, Typography, Tag, Space, Empty, Alert, Segmented, Tooltip } from 'antd'
import { useTranslation } from 'react-i18next'
import { NODE_COLORS } from './GraphView'
import { displayLabel } from '../../utils/label'

const { Text, Paragraph } = Typography
const { CheckableTag } = Tag

/**
 * When did what happen — as far as the SOURCES say.
 *
 * The load-bearing decision here is what is left OUT. `observed_at` is meant
 * to be the time the source states, but for most findings it is the run
 * time, because `Finding.found_at` defaults to utcnow() and most runners do
 * not override it. A chronology built on that shows hundreds of events at
 * "when I searched" and a handful of real ones — it looks like a chronology
 * of the case and is a chronology of the searching, which in a file is worse
 * than having none.
 *
 * The default is honest now (unknown = null) and the runners that know a real
 * date set it. This panel therefore shows ONLY findings carrying a source
 * date, and states how many it is leaving out. A finding with no date is not
 * placed on the line — inventing a position for it is the whole failure mode.
 */
export default function TimelinePanel({
  data, onSelect,
}: {
  data: { entities: any[]; edges: any[] } | null
  onSelect?: (node: any) => void
}) {
  const { t } = useTranslation()
  const [order, setOrder] = useState<'desc' | 'asc'>('desc')
  // Empty set means "everything" — not "nothing". A type filter that starts
  // out excluding is a filter that hides the case from the person who opened
  // the tab.
  const [types, setTypes] = useState<Set<string>>(new Set())

  const { allDated, undated } = useMemo(() => {
    const all = (data?.entities || []).filter(
      (e) => !(e.data || {}).virtual)
    const allDated = all
      .filter((e) => e.observed_at)
      .sort((a, b) => {
        const d = String(a.observed_at).localeCompare(String(b.observed_at))
        return order === 'asc' ? d : -d
      })
    return { allDated, undated: all.length - allDated.length }
  }, [data, order])

  /** Types actually present on the line, commonest first, with counts. */
  const available = useMemo(() => {
    const n = new Map<string, number>()
    for (const e of allDated) {
      const k = String(e.entity_type || 'unknown')
      n.set(k, (n.get(k) || 0) + 1)
    }
    return [...n.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  }, [allDated])

  const dated = useMemo(
    () => (types.size === 0 ? allDated
      : allDated.filter((e) => types.has(String(e.entity_type || 'unknown')))),
    [allDated, types],
  )

  // Hidden BY THE FILTER, counted apart from the ones with no date at all.
  // Rolling the two into one number would let a filter read as a statement
  // about the case — the same failure this panel exists to avoid.
  const hiddenByFilter = allDated.length - dated.length

  const toggleType = (k: string) => setTypes((prev) => {
    const n = new Set(prev)
    n.has(k) ? n.delete(k) : n.add(k)
    return n
  })

  if (!data) return <Empty description={t('timeline.empty')} style={{ padding: 40 }} />

  return (
    <Card size="small">
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Alert
          type="info"
          showIcon
          message={t('timeline.headline', { n: allDated.length, skipped: undated })}
          description={
            <Paragraph style={{ margin: 0 }}>{t('timeline.explain')}</Paragraph>
          }
        />

        <Segmented aria-label={t('a11y.timeline_order')}
          size="small"
          value={order}
          onChange={(v) => setOrder(v as 'desc' | 'asc')}
          options={[
            { label: t('timeline.newest'), value: 'desc' },
            { label: t('timeline.oldest'), value: 'asc' },
          ]}
        />

        {available.length > 1 && (
          <Space wrap size={[4, 6]}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t('timeline.filter_label')}
            </Text>
            <CheckableTag
              checked={types.size === 0}
              onChange={() => setTypes(new Set())}
            >
              {t('timeline.filter_all', { n: allDated.length })}
            </CheckableTag>
            {available.map(([k, n]) => (
              <CheckableTag
                key={k}
                checked={types.has(k)}
                onChange={() => toggleType(k)}
                style={types.has(k)
                  ? { background: NODE_COLORS[k] || NODE_COLORS.default }
                  : { borderColor: NODE_COLORS[k] || NODE_COLORS.default }}
              >
                {k} · {n}
              </CheckableTag>
            ))}
          </Space>
        )}

        {hiddenByFilter > 0 && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('timeline.filter_active', {
              shown: dated.length, hidden: hiddenByFilter,
            })}
          </Text>
        )}

        {dated.length === 0 ? (
          <Empty
            description={t(allDated.length === 0
              ? 'timeline.none_dated'      /* nothing in the case has a date */
              : 'timeline.none_in_filter') /* dates exist, the filter hides them */}
            style={{ padding: 24 }}
          />
        ) : (
          <Timeline
            mode="left"
            items={dated.slice(0, 200).map((e) => ({
              color: NODE_COLORS[e.entity_type] || NODE_COLORS.default,
              label: (
                <Text style={{ fontSize: 12 }}>
                  {String(e.observed_at).replace('T', ' ').slice(0, 16)}
                </Text>
              ),
              children: (
                <Space size={6} wrap style={{ cursor: onSelect ? 'pointer' : undefined }}
                       onClick={() => onSelect?.(e)}>
                  <Tag>{e.entity_type}</Tag>
                  <Text strong style={{ wordBreak: 'break-all' }}>
                    {displayLabel(e.entity_type, e.label) || e.label}
                  </Text>
                  {e.admiralty && (
                    <Tooltip title={t('graph.admiralty_hint')}>
                      <Tag color={(e.corroborated_by?.length || 0) > 1 ? 'green' : undefined}
                           style={{ fontSize: 11 }}>{e.admiralty}</Tag>
                    </Tooltip>
                  )}
                  {e.source && (
                    <Text type="secondary" style={{ fontSize: 12 }}>{e.source}</Text>
                  )}
                </Space>
              ),
            }))}
          />
        )}
        {dated.length > 200 && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('timeline.capped', { shown: 200, total: dated.length })}
          </Text>
        )}
      </Space>
    </Card>
  )
}

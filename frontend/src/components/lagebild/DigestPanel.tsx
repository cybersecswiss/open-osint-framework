import { Card, Row, Col, Typography, Tag, Space, Alert, Spin, Tooltip, Button, Segmented } from 'antd'
import { ReloadOutlined, WarningOutlined, FileTextOutlined, BugOutlined } from '@ant-design/icons'
import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { digestApi } from '../../api/client'
import { formatDateTime } from '../../utils/datetime'
import LoadFailed from '../LoadFailed'

const { Text, Paragraph, Title } = Typography

// Source kinds in reading order. An official release and a newspaper piece
// are both leads, not the same weight — and with roughly 46 authority items
// against 10 907 media items a week, sorting by time alone would bury every
// official statement under press churn.
const KIND_COLOUR: Record<string, string> = {
  authority: 'red', police: 'volcano', cyber: 'purple',
  tech: 'blue', media: 'default', other: 'default',
}

/**
 * The morning situation report.
 *
 * Everything on this panel already existed and nobody had to look at it: the
 * harvester caches 17 000 articles, CISA publishes the exploited-vulnerability
 * catalogue, ransomware.live tracks leak-site postings. Each answered a
 * question only once it was asked — and a running team does not ask, it opens
 * the app.
 *
 * States its scope in the panel rather than leaving it to be assumed: public
 * reporting only, nothing derived from case data.
 */
export default function DigestPanel() {
  const { t } = useTranslation()
  const [hours, setHours] = useState(24)
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['digest', hours],
    queryFn: () => digestApi.get(hours),
    staleTime: 10 * 60_000,
    // Switching the window used to blank the whole panel — including the
    // switch itself — and paint it again a moment later. The control looked
    // broken because it disappeared under the cursor. Keeping the previous
    // edition on screen while the new one loads makes the change read as a
    // change instead of as a reload.
    placeholderData: keepPreviousData,
    // The harvester ticks every 10 minutes and the server caches for 15, but
    // an OPEN page never asked again — it refetched on mount and on window
    // focus and otherwise sat there. A situation report is exactly the screen
    // somebody leaves open on a second monitor, so it has to age itself out.
    //
    // Five minutes, and NOT in the background: a hidden tab polling an
    // authority feed pipeline all night buys nothing, and returning to the
    // tab already triggers a refetch.
    refetchInterval: 5 * 60_000,
    refetchIntervalInBackground: false,
  })

  if (isLoading) return <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>

  // A failed request must NOT render as "no data". This is the situation
  // report: "nothing happened" and "we could not check" are the one pair of
  // statements that must never look alike. The service behind this is careful
  // about exactly that — every degraded source comes back as a stated note —
  // and the panel used to undo that care one level up, because useQuery
  // yields `data === undefined` on error just as it does on an empty result.
  if (isError || !data) {
    return (
      <LoadFailed compact what={t('loadfail.what.digest')}
                  hint={t('digest.failed_hint')} loading={isFetching}
                  onRetry={() => refetch()} />
    )
  }

  const kinds = Object.entries(data.news || {})

  return (
    <Space direction="vertical" size={14} style={{ width: '100%' }}>
      <Space style={{ width: '100%', justifyContent: 'space-between' }} wrap>
        <Space>
          <Title level={4} style={{ margin: 0 }}>{t('digest.title')}</Title>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('digest.generated', { when: formatDateTime(data.generated_at) })}
          </Text>
        </Space>
        <Space>
          <Segmented aria-label={t('a11y.digest_period')}
            size="small" value={hours}
            onChange={(v) => setHours(v as number)}
            options={[{ label: '24 h', value: 24 }, { label: '48 h', value: 48 },
                      { label: '7 d', value: 168 }]}
          />
          <Button aria-label={t('a11y.refresh')} size="small" icon={<ReloadOutlined />} loading={isFetching}
                  onClick={() => refetch()} />
        </Space>
      </Space>

      {/* Own translated string, not the API's: this sentence states the
          sovereignty boundary, and it was English-only in a four-language
          product. `data.scope` remains for API consumers. */}
      <Alert type="info" showIcon message={t('digest.scope')} />
      {(data.notes || []).map((n: any, i: number) => {
        const code = typeof n === 'string' ? '' : n?.code
        const detail = typeof n === 'string' ? n : (n?.detail || '')
        const text = code
          ? t(`digest.note_${code}`, { defaultValue: n?.message || code })
          : detail
        return (
          <Alert key={i} type="warning" showIcon
                 message={detail && code ? `${text} (${detail})` : text} />
        )
      })}

      <Row gutter={[14, 14]}>
        {/* ── Exploited vulnerabilities ── */}
        <Col xs={24} lg={12}>
          <Card size="small" title={<Space><BugOutlined />{t('digest.kev', { days: data.kev_days })}</Space>}>
            {(data.kev || []).length === 0 ? (
              <Text type="secondary">{t('digest.kev_none')}</Text>
            ) : (
              <Space direction="vertical" size={6} style={{ width: '100%' }}>
                {(data.kev || []).slice(0, 10).map((v: any) => (
                  <div key={v.cve}>
                    <Space size={6} wrap>
                      <a href={v.url} target="_blank" rel="noopener noreferrer">
                        <Text strong>{v.cve}</Text>
                      </a>
                      {/* The one flag that changes priority: already used in
                          ransomware campaigns. */}
                      {String(v.ransomware).toLowerCase() === 'known' && (
                        <Tag color="red">{t('digest.kev_ransomware')}</Tag>
                      )}
                      <Text type="secondary" style={{ fontSize: 12 }}>{v.added}</Text>
                    </Space>
                    <div><Text style={{ fontSize: 12 }}>{v.vendor} {v.product} — {v.name}</Text></div>
                  </div>
                ))}
              </Space>
            )}
          </Card>
        </Col>

        {/* ── Ransomware victims ── */}
        <Col xs={24} lg={12}>
          {/* Independent of the time window above: this is the most recent
              leak-site postings, not "postings in the last N hours". Measured
              across 24 h / 48 h / 7 d the section is byte-identical, which is
              a large part of why the window switch felt like it did nothing. */}
          <Card size="small" title={<Space><WarningOutlined />{t('digest.victims')}
            <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
              {t('digest.window_independent')}
            </Text></Space>}
                extra={data.victims_home?.length
                  ? <Tag color="red">{t('digest.victims_home', { n: data.victims_home.length })}</Tag>
                  : null}>
            {(data.victims || []).length === 0 ? (
              <Text type="secondary">{t('digest.victims_none')}</Text>
            ) : (
              <Space direction="vertical" size={6} style={{ width: '100%' }}>
                {(data.victims || []).slice(0, 10).map((v: any, i: number) => (
                  <Space key={i} size={6} wrap>
                    <Tag color={['CH', 'LI', 'DE', 'AT'].includes(v.country) ? 'red' : 'default'}>
                      {v.country || '—'}
                    </Tag>
                    <Text strong style={{ fontSize: 13 }}>{v.victim}</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {v.group}{v.activity ? ` · ${v.activity}` : ''}
                    </Text>
                  </Space>
                ))}
              </Space>
            )}
          </Card>
        </Col>

        {/* ── News by source kind ── */}
        <Col span={24}>
          <Card size="small" title={<Space><FileTextOutlined />
            {t('digest.news', { n: data.news_total, h: data.window_hours })}
            {data.news_shown < data.news_total && (
              <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
                {t('digest.news_shown', { n: data.news_shown })}
              </Text>
            )}</Space>}>
            {kinds.length === 0 ? (
              <Text type="secondary">{t('digest.news_none')}</Text>
            ) : (
              <Row gutter={[14, 14]}>
                {kinds.map(([kind, items]: any) => (
                  <Col xs={24} md={12} xl={8} key={kind}>
                    <Tag color={KIND_COLOUR[kind] || 'default'}>
                      {t(`news.kind_${kind}`, { defaultValue: kind })}
                    </Tag>
                    <Space direction="vertical" size={4}
                           style={{ width: '100%', marginTop: 6 }}>
                      {items.map((a: any, i: number) => (
                        <Tooltip key={i} title={a.summary || ''}>
                          <div>
                            <a href={a.url} target="_blank" rel="noopener noreferrer"
                               style={{ fontSize: 13 }}>{a.title}</a>
                            <div><Text type="secondary" style={{ fontSize: 11 }}>
                              {a.source} · {formatDateTime(a.published)}
                            </Text></div>
                          </div>
                        </Tooltip>
                      ))}
                    </Space>
                  </Col>
                ))}
              </Row>
            )}
          </Card>
        </Col>
      </Row>
    </Space>
  )
}

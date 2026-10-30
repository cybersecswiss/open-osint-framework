import { Alert, Button, List, Popover, Space, Tag, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import type { CrossHits } from '../../api/client'
import { displayLabel } from '../../utils/label'

const { Text } = Typography

/**
 * "These findings also occur in other cases" — the match that connects two
 * investigations nobody knew were about the same person. Only cases the
 * viewer may open are ever listed (filtered server-side).
 */
export default function CrossCaseBanner({ hits, entities }: { hits?: CrossHits; entities?: any[] }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const ids = Object.keys(hits?.matches || {})
  if (!hits || !ids.length) return null
  const byId = new Map((entities || []).map((e: any) => [String(e.id), e]))
  const otherCases = new Set(ids.flatMap((id) => hits.matches[id].map((h) => h.case_id)))

  const content = (
    <List
      size="small"
      style={{ maxWidth: 520, maxHeight: 360, overflowY: 'auto' }}
      dataSource={ids}
      renderItem={(id) => {
        const e = byId.get(id)
        return (
          <List.Item>
            <Space direction="vertical" size={2}>
              <Text strong>{e ? displayLabel(e.entity_type, e.label) : id}</Text>
              <Space size={4} wrap>
                {hits.matches[id].map((h) => {
                  const c = hits.cases[h.case_id]
                  return (
                    <Tag key={h.case_id} color="volcano" style={{ cursor: 'pointer' }}
                         onClick={() => navigate(`/cases/${h.case_id}`)}>
                      {c ? `${c.case_number} — ${c.title}` : h.case_id.slice(0, 8)}
                    </Tag>
                  )
                })}
              </Space>
            </Space>
          </List.Item>
        )
      }}
    />
  )
  return (
    <Alert
      type="warning"
      showIcon
      style={{ marginBottom: 12 }}
      message={t('cross.banner', { n: ids.length, cases: otherCases.size })}
      action={
        <Popover content={content} title={t('cross.popover_title')} trigger="click" placement="bottomRight">
          <Button size="small">{t('cross.show')}</Button>
        </Popover>
      }
    />
  )
}

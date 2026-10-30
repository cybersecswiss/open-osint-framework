import { useEffect, useMemo, useState } from 'react'
import { Modal, AutoComplete, Space, Tag, Typography, Alert, Button, message } from 'antd'
import { SwapOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { entityApi } from '../../api/client'
import { RELATIONS, normaliseRelation } from '../../utils/relations'
import { displayLabel } from '../../utils/label'
import { NODE_COLORS } from './GraphView'

const { Text } = Typography

/**
 * Confirm a link the investigator is drawing by hand.
 *
 * This is the step where an assertion enters the case, so it is deliberately
 * a dialog and not a one-click action. Three things have to be settled before
 * a link means anything, and all three are visible here rather than assumed:
 *
 *  - **What the relation is.** Stored as a language-independent key (see
 *    utils/relations.ts) so the same statement reads the same in every UI
 *    language and in every export.
 *  - **Which way round it runs.** "A controls B" reversed is a different
 *    claim about the case, so direction is shown as text and can be swapped —
 *    not inferred from which node happened to be right-clicked first.
 *  - **Whether it already exists.** A link the graph already holds is
 *    reported instead of silently drawn a second time; if a TOOL already
 *    asserted it, saying so matters more than adding the link, because a
 *    corroborated relation and a hand-drawn one are different evidence.
 *
 * What is committed carries `source = "manual"`. It must stay possible, in
 * the report and in the exports, to tell what a source stated from what an
 * investigator concluded.
 */
export default function LinkEntitiesModal({
  open, caseId, from, to, existingEdges, onClose, onDone,
}: {
  open: boolean
  caseId: string
  from: any
  to: any
  existingEdges: any[]
  onClose: () => void
  onDone: () => void
}) {
  const { t } = useTranslation()
  const [relation, setRelation] = useState<string>('associated_with')
  const [swapped, setSwapped] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (open) { setRelation('associated_with'); setSwapped(false) }
  }, [open, from, to])

  const src = swapped ? to : from
  const dst = swapped ? from : to

  /** Links the case already holds between these two, in either direction. */
  const between = useMemo(() => {
    if (!from || !to) return []
    const a = String(from.id), b = String(to.id)
    return (existingEdges || []).filter((e: any) => {
      const f = String(e.from_entity), g = String(e.to_entity)
      return (f === a && g === b) || (f === b && g === a)
    })
  }, [existingEdges, from, to])

  // Compare against the NORMALISED relation — what will actually be stored.
  // Matching on the raw input would let "Same Person" past the duplicate
  // check and then land as the `same_person` that is already there.
  const duplicate = useMemo(
    () => between.find((e: any) => String(e.from_entity) === String(src?.id)
      && String(e.to_entity) === String(dst?.id)
      && e.relation_type === normaliseRelation(relation)),
    [between, src, dst, relation],
  )

  const chip = (e: any) => (
    <Tag color={NODE_COLORS[e?.entity_type] || NODE_COLORS.default}>
      {displayLabel(e?.entity_type, e?.label) || e?.label || e?.id}
    </Tag>
  )

  const save = async () => {
    if (!src || !dst || !relation) return
    const rel = normaliseRelation(relation)
    if (!rel) return
    setSaving(true)
    try {
      // No entities — both endpoints already exist in the case. The edge id
      // is left out on purpose: the server derives it, so redrawing the same
      // link collapses instead of adding a second identical edge.
      await entityApi.commit(caseId, {
        entities: [],
        edges: [{
          from_entity: String(src.id),
          to_entity: String(dst.id),
          relation_type: rel,
          source: 'manual',
          confidence: 1.0,
        }],
      })
      message.success(t('graph_map.link_saved'))
      onDone()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || t('graph_map.link_failed'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={open}
      onCancel={onClose}
      onOk={save}
      okButtonProps={{ loading: saving,
        disabled: !normaliseRelation(relation) || !!duplicate }}
      okText={t('graph_map.link_save')}
      cancelText={t('common.cancel')}
      title={t('graph_map.link_title')}
      width={560}
    >
      <Space direction="vertical" size={14} style={{ width: '100%' }}>
        <Space wrap align="center">
          {chip(src)}
          <Text type="secondary">→</Text>
          {chip(dst)}
          <Button size="small" icon={<SwapOutlined />} onClick={() => setSwapped((v) => !v)}>
            {t('graph_map.link_swap')}
          </Button>
        </Space>

        <div>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('graph_map.link_relation')}
          </Text>
          {/* One field, both ways in: pick a preset or type your own. Two
              separate controls made the same choice look like two choices. */}
          <AutoComplete
            value={relation}
            onChange={(v) => setRelation(String(v ?? ''))}
            style={{ width: '100%', marginTop: 4 }}
            placeholder={t('graph_map.link_custom')}
            options={RELATIONS.map((r) => ({
              value: r.value,
              label: (
                <Space size={6}>
                  <span>{t(r.labelKey)}</span>
                  <Text type="secondary" style={{ fontSize: 11 }}>{r.value}</Text>
                </Space>
              ),
            }))}
            filterOption={(input, opt) => {
              const q = input.toLowerCase()
              const r = RELATIONS.find((x) => x.value === opt?.value)
              return !!r && (r.value.includes(q) || t(r.labelKey).toLowerCase().includes(q))
            }}
          />
          <Text type="secondary" style={{ fontSize: 11 }}>
            {t('graph_map.link_stored_as', { value: normaliseRelation(relation) })}
          </Text>
        </div>

        {duplicate && (
          <Alert type="warning" showIcon message={t('graph_map.link_duplicate')} />
        )}

        {!duplicate && between.length > 0 && (
          <Alert
            type="info"
            showIcon
            message={t('graph_map.link_existing', { count: between.length })}
            description={
              <Space direction="vertical" size={2}>
                {between.map((e: any) => (
                  <Text key={String(e.id)} style={{ fontSize: 12 }}>
                    {e.relation_type}
                    {' · '}
                    <Text type="secondary">
                      {e.source === 'manual'
                        ? t('graph_map.link_by_hand')
                        : e.source || t('graph_map.link_by_unknown')}
                    </Text>
                  </Text>
                ))}
              </Space>
            }
          />
        )}

        <Alert type="info" showIcon message={t('graph_map.link_note')} />
      </Space>
    </Modal>
  )
}

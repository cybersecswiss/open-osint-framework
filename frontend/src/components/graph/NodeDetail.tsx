import { Card, Descriptions, Button, Space, Tag, Typography, message, Tooltip, Empty, Input } from 'antd'
import { EyeOutlined, StarOutlined, CopyOutlined, LinkOutlined, DeleteOutlined, AimOutlined, EditOutlined, CheckOutlined, CloseOutlined, CameraOutlined, MergeCellsOutlined } from '@ant-design/icons'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { displayLabel } from '../../utils/label'

const { Text, Paragraph } = Typography

interface Props {
  node: Record<string, any> | null
  onMonitor: (node: Record<string, any>) => void
  onToggleRelevant?: (node: Record<string, any>) => void
  onDelete?: (node: Record<string, any>) => void
  /** Open the advanced/pivot search ("Erweiterte Suche") from this node. */
  onPivot?: (node: Record<string, any>) => void
  /** Rename the entity's label. */
  onRename?: (node: Record<string, any>, label: string) => void
  /** Persist the investigator's own note on this node. */
  onSaveNotes?: (node: Record<string, any>, notes: string) => void
  /** Save the page behind this finding (screenshot + archive + hash). */
  onCaptureEvidence?: (node: Record<string, any>) => void
  capturing?: boolean
  /** "Same thing": fold other nodes of the case into this one. */
  onMerge?: (node: Record<string, any>) => void
  /** The same finding in other cases the viewer may open. */
  crossHits?: { case_id: string; case_number?: string; title?: string }[]
}

// Internal cytoscape/graph fields we don't want to surface to the analyst.
const HIDDEN_KEYS = new Set([
  'id', 'entity_type', '_size', '_show_label', '_relevant',
  'platform',        // shown as a chip in the header instead
  'confidence',      // superseded by the Admiralty rating in the header
  'admiralty',       // shown as a chip in the header instead
  'corroborated_by', // shown as its own block — it is the strongest signal
  'relevance_score', // a ranking aid, not a property of the finding
  'aliases',         // merged-in names — shown as chips in the header
  'notes',           // editable field of its own, below
])

/** Admiralty rating → colour. Green only for "1" — confirmed by other
 *  sources — because that is the one grade the framework will not assign
 *  without two independent tools agreeing. */
function ratingColor(admiralty: string): string {
  const credibility = admiralty.slice(1)
  if (credibility === '1') return 'green'
  if (credibility === '2') return 'blue'
  if (credibility === '3') return 'gold'
  return 'orange'
}

const URL_RE = /https?:\/\/[^\s)<>"']+/g

function copy(text: string, t: any) {
  navigator.clipboard.writeText(text)
    .then(() => message.success(t('graph.ctx_copied')))
    .catch(() => message.error(t('graph.ctx_copy_failed')))
}

/** Render a leaf value with auto-link, copy button, and monospace
 *  for hashes / addresses. Falls back to JSON.stringify for objects. */
function renderValue(value: any, t: any): JSX.Element {
  if (value === null || value === undefined || value === '') {
    return <Text type="secondary">—</Text>
  }
  if (typeof value === 'boolean') {
    return <Tag color={value ? 'green' : 'default'}>{value ? '✓' : '✗'}</Tag>
  }
  if (typeof value === 'number') {
    return <Text code>{String(value)}</Text>
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <Text type="secondary">[]</Text>
    return (
      <ul style={{ margin: 0, paddingLeft: 16 }}>
        {value.slice(0, 50).map((v, i) => (
          <li key={i}>{renderValue(v, t)}</li>
        ))}
        {value.length > 50 && (
          <li><Text type="secondary">…{value.length - 50} {t('common.more')}</Text></li>
        )}
      </ul>
    )
  }
  if (typeof value === 'object') {
    return (
      <Descriptions column={1} size="small" bordered style={{ marginTop: 4 }}>
        {Object.entries(value).map(([k, v]) => (
          <Descriptions.Item key={k} label={<Text type="secondary">{k}</Text>}>
            {renderValue(v, t)}
          </Descriptions.Item>
        ))}
      </Descriptions>
    )
  }

  // Strings — detect URL(s) inside, hashes, long text
  const s = String(value)
  const isUrl = /^https?:\/\//.test(s)
  const looksLikeHash = /^[a-f0-9]{32,}$/i.test(s)
  const hasUrl = URL_RE.test(s) && !isUrl
  URL_RE.lastIndex = 0  // reset stateful regex

  const copyBtn = (
    <Tooltip title={t('graph.ctx_copy_label')}>
      <Button aria-label={t('graph.ctx_copy_label')} size="small" type="text" icon={<CopyOutlined />}
              onClick={() => copy(s, t)} />
    </Tooltip>
  )

  if (isUrl) {
    return (
      <Space size={4} wrap>
        <a href={s} target="_blank" rel="noreferrer" style={{ wordBreak: 'break-all' }}>
          <LinkOutlined /> {s.length > 80 ? s.slice(0, 80) + '…' : s}
        </a>
        {copyBtn}
      </Space>
    )
  }
  if (looksLikeHash) {
    return (
      <Space size={4}>
        <Text code copyable={false} style={{ fontSize: 11, wordBreak: 'break-all' }}>
          {s.length > 24 ? s.slice(0, 16) + '…' + s.slice(-6) : s}
        </Text>
        {copyBtn}
      </Space>
    )
  }
  if (hasUrl) {
    // Render mixed text with embedded links as a paragraph.
    const parts: (string | JSX.Element)[] = []
    let last = 0
    let i = 0
    s.replace(URL_RE, (m, idx) => {
      if (idx > last) parts.push(s.slice(last, idx))
      parts.push(
        <a key={i++} href={m} target="_blank" rel="noreferrer">{m}</a>
      )
      last = idx + m.length
      return m
    })
    if (last < s.length) parts.push(s.slice(last))
    return <span style={{ wordBreak: 'break-word' }}>{parts}</span>
  }
  return (
    <Space size={4} style={{ alignItems: 'flex-start' }}>
      <Paragraph style={{ margin: 0, wordBreak: 'break-word', maxWidth: 320 }}
                 ellipsis={{ rows: 4, expandable: true, symbol: t('common.more') }}>
        {s}
      </Paragraph>
      {copyBtn}
    </Space>
  )
}

export default function NodeDetail({ node, onMonitor, onToggleRelevant, onDelete, onPivot, onRename, onSaveNotes, onCaptureEvidence, capturing, onMerge, crossHits }: Props) {
  const navigate = useNavigate()
  const { t } = useTranslation()
  const [editing, setEditing] = useState(false)
  const [labelVal, setLabelVal] = useState('')
  const [noteVal, setNoteVal] = useState('')
  const [, setNoteDirty] = useState(false)

  // Reset the draft when a different node is selected, otherwise the note
  // typed on one node follows the analyst to the next — which in a case file
  // is not a cosmetic bug.
  useEffect(() => {
    setNoteVal(node?.notes || '')
    setEditing(false)
  }, [node?.id])

  if (!node) {
    return (
      <Card size="small">
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
               description={t('graph.no_selection')} />
      </Card>
    )
  }

  const entries = Object.entries(node)
    .filter(([k]) => !HIDDEN_KEYS.has(k))
    .filter(([k]) => !k.startsWith('_'))
    .sort(([a], [b]) => a.localeCompare(b))

  const isRelevant = node.is_relevant === true
  const conf = typeof node.confidence === 'number' ? node.confidence : null
  const admiralty: string | null = node.admiralty || null
  const sources: string[] = Array.isArray(node.corroborated_by) ? node.corroborated_by : []
  const isVirtual = node.virtual === true
  const aliases: { entity_type: string; label: string }[] = Array.isArray(node.aliases) ? node.aliases : []

  const titleArea = (
    <Space size={6} wrap>
      <Tag color="blue">{node.entity_type}</Tag>
      {node.platform && <Tag color="geekblue">{node.platform}</Tag>}
      {admiralty ? (
        <Tooltip title={t('graph.admiralty_hint')}>
          <Tag color={ratingColor(admiralty)}>{admiralty}</Tag>
        </Tooltip>
      ) : conf !== null && conf > 0 ? (
        <Tag color={conf >= 0.85 ? 'green' : conf >= 0.6 ? 'gold' : 'orange'}>
          {Math.round(conf * 100)}%
        </Tag>
      ) : null}
      {sources.length > 1 && (
        <Tooltip title={sources.join(', ')}>
          <Tag color="green">✓ {t('graph.confirmed_by_n', { n: sources.length })}</Tag>
        </Tooltip>
      )}
      {isVirtual && (
        <Tooltip title={t('graph.placeholder_hint')}>
          <Tag>{t('graph.placeholder')}</Tag>
        </Tooltip>
      )}
      {isRelevant && <Tag color="gold">★ {t('graph.relevant')}</Tag>}
      {!!crossHits?.length && crossHits.map((h) => (
        <Tooltip key={h.case_id} title={t('cross.node_hint', { title: h.title || '' })}>
          <Tag color="volcano" style={{ cursor: 'pointer' }} onClick={() => navigate(`/cases/${h.case_id}`)}>
            {t('cross.node_tag', { number: h.case_number || h.case_id.slice(0, 8) })}
          </Tag>
        </Tooltip>
      ))}
      {aliases.length > 0 && (
        <Tooltip title={t('merge.aliases_hint')}>
          <Tag color="cyan">{t('merge.aliases', { names: aliases.map((a) => a.label).join(', ') })}</Tag>
        </Tooltip>
      )}
    </Space>
  )

  return (
    <Card size="small" title={titleArea}
          styles={{ body: { maxHeight: '70vh', overflowY: 'auto' } }}>
      {editing ? (
        <Space.Compact style={{ width: '100%', marginBottom: 8 }}>
          <Input aria-label={t('a11y.edit_label')} autoFocus value={labelVal} onChange={(e) => setLabelVal(e.target.value)}
                 onPressEnter={() => { if (labelVal.trim()) { onRename?.(node, labelVal.trim()); setEditing(false) } }} />
          <Button aria-label={t('a11y.confirm_label')} icon={<CheckOutlined />} type="primary"
                  onClick={() => { if (labelVal.trim()) { onRename?.(node, labelVal.trim()); setEditing(false) } }} />
          <Button aria-label={t('a11y.cancel_edit')} icon={<CloseOutlined />} onClick={() => setEditing(false)} />
        </Space.Compact>
      ) : node.label && (
        <Paragraph strong style={{ marginBottom: 8, wordBreak: 'break-word' }}>
          {displayLabel(node.entity_type, node.label)}
          {onRename && (
            <Tooltip title={t('graph.rename')}>
              <Button aria-label={t('graph.rename')} size="small" type="text" icon={<EditOutlined />}
                      onClick={() => { setLabelVal(node.label); setEditing(true) }} />
            </Tooltip>
          )}
        </Paragraph>
      )}
      {node.url && (
        <Paragraph style={{ marginBottom: 12 }}>
          <a href={node.url} target="_blank" rel="noreferrer">
            <LinkOutlined /> {node.url}
          </a>
        </Paragraph>
      )}
      {sources.length > 0 && (
        <Paragraph style={{ marginBottom: 12 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('graph.confirmed_by')}:{' '}
          </Text>
          <Space size={4} wrap>
            {sources.map((s) => (
              <Tag key={s} color={sources.length > 1 ? 'green' : 'default'}
                   style={{ marginInlineEnd: 0 }}>
                {s}
              </Tag>
            ))}
          </Space>
        </Paragraph>
      )}

      {onSaveNotes && (
        <div style={{ marginBottom: 12 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>{t('graph.notes')}</Text>
          <Input.TextArea
            value={noteVal}
            onChange={(e) => setNoteVal(e.target.value)}
            placeholder={t('graph.notes_placeholder')}
            autoSize={{ minRows: 2, maxRows: 6 }}
            style={{ marginTop: 4 }}
          />
          {noteVal !== (node.notes || '') && (
            <Space size={4} style={{ marginTop: 4 }}>
              <Button size="small" type="primary" icon={<CheckOutlined />}
                      onClick={() => { onSaveNotes(node, noteVal); setNoteDirty(false) }}>
                {t('common.save')}
              </Button>
              <Button size="small" onClick={() => setNoteVal(node.notes || '')}>
                {t('common.cancel')}
              </Button>
            </Space>
          )}
        </div>
      )}

      <Descriptions column={1} size="small" bordered>
        {entries
          .filter(([k]) => !['label', 'url'].includes(k))
          .map(([k, v]) => (
            <Descriptions.Item key={k} label={k}>
              {renderValue(v, t)}
            </Descriptions.Item>
          ))}
      </Descriptions>
      <Space style={{ marginTop: 12 }} wrap>
        {onPivot && (
          <Button size="small" type="primary" ghost icon={<AimOutlined />}
                  onClick={() => onPivot(node)}>
            {t('pivot.button')}
          </Button>
        )}
        <Button size="small" icon={<EyeOutlined />} onClick={() => onMonitor(node)}>
          {t('graph.add_monitoring')}
        </Button>
        {onCaptureEvidence && (node.url || ['url', 'website', 'onion_address', 'onion', 'domain', 'subdomain'].includes(node.entity_type)) && (
          <Tooltip title={t('evidence.node_hint')}>
            <Button size="small" icon={<CameraOutlined />} loading={capturing}
                    onClick={() => onCaptureEvidence(node)}>
              {t('evidence.node_button')}
            </Button>
          </Tooltip>
        )}
        {onToggleRelevant && (
          <Button aria-label={t('a11y.toggle_relevant')} size="small" icon={<StarOutlined />}
                  type={isRelevant ? 'primary' : 'default'}
                  onClick={() => onToggleRelevant(node)}>
            {isRelevant ? t('graph.ctx_unmark_relevant') : t('graph.ctx_mark_relevant')}
          </Button>
        )}
        {onMerge && !isVirtual && (
          <Tooltip title={t('merge.button_hint')}>
            <Button size="small" icon={<MergeCellsOutlined />} onClick={() => onMerge(node)}>
              {t('merge.button')}
            </Button>
          </Tooltip>
        )}
        {onDelete && (
          <Button size="small" danger icon={<DeleteOutlined />}
                  onClick={() => onDelete(node)}>
            {t('graph.ctx_delete_fp')}
          </Button>
        )}
      </Space>
    </Card>
  )
}

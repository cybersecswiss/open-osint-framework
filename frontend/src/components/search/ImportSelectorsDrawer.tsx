import { useMemo, useState } from 'react'
import {
  Drawer, Input, Button, Space, Tag, Checkbox, Alert, Typography, Empty,
  message, Collapse, Badge, Tooltip,
} from 'antd'
import { FileTextOutlined, PlusOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { entityApi, searchApi } from '../../api/client'
import {
  extractSelectors, TYPE_TO_ENTITY, TYPE_TO_QUERY_TYPE, type Extracted,
} from '../../utils/extractSelectors'
import { availableQueryTypes } from '../../utils/queryTypes'
import { imagesFromPaste, readQrPayloads } from '../../utils/pastedImage'
import { displayLabel } from '../../utils/label'

const { Text, Paragraph } = Typography

/**
 * Start a case from the document it actually starts from.
 *
 * A case does not begin with one value. It begins with a report, a warrant, a
 * complaint form: two numbers, an e-mail, an alias, a wallet, a link. Until
 * now each of those had to be typed in individually, and in practice the ones
 * further down the page were the ones that never got entered.
 *
 * **The pasted text is never sent anywhere and never stored.** Extraction runs
 * in the browser (utils/extractSelectors.ts); what leaves this drawer is only
 * the selectors the investigator ticked, which are the same kind of value the
 * case already holds. That distinction is the whole reason this is acceptable
 * where an attachment store is not: a phone number in a case file is a
 * finding — a sealed report copied into a second system is a second case file,
 * with its own retention, its own chain of custody and its own disclosure
 * problem.
 *
 * It proposes, it does not decide. Nothing is pre-ticked, every candidate
 * shows its type and how often it appeared, and the text stays visible next to
 * the list so a wrong extraction is obvious rather than silent.
 */
export default function ImportSelectorsDrawer({
  open, caseId, onClose, onCommitted,
}: {
  open: boolean
  caseId: string
  onClose: () => void
  onCommitted: () => void
}) {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [committing, setCommitting] = useState(false)
  const [scanning, setScanning] = useState(false)

  const found = useMemo(() => extractSelectors(text), [text])

  // Which selectors can this tenant actually run a search on? The extractor
  // and the module manifests are two lists that must agree, and they drifted
  // once already: eight types were searchable for months while the extractor
  // could not see them. Rather than duplicating the manifest here, the
  // drawer reads it and says which candidates lead nowhere — a value nothing
  // can act on is still worth storing as a case fact, but the investigator
  // should not expect a search button for it.
  const { data: mods } = useQuery({
    queryKey: ['search-modules'], queryFn: searchApi.modules, staleTime: 60_000,
    enabled: open,
  })
  const searchableTypes = useMemo(
    () => availableQueryTypes(Object.values(mods?.manifests || {})),
    [mods],
  )
  // Pasting a screenshot: decode any QR in it and append the payload to the
  // text box, where the normal extraction picks it up. Appending rather than
  // replacing is deliberate — the analyst sees what was read out of the
  // picture and can correct it, which they could not do if the value simply
  // appeared in the candidate list.
  const onPaste = async (e: React.ClipboardEvent) => {
    const images = imagesFromPaste(e.nativeEvent as ClipboardEvent)
    if (!images.length) return
    e.preventDefault()
    setScanning(true)
    try {
      const found: string[] = []
      for (const img of images) {
        try {
          found.push(...(await readQrPayloads(img)))
        } catch {
          // A picture that cannot be decoded is the normal case, not an error.
        }
      }
      if (!found.length) {
        message.info(t('import_sel.qr_none'))
        return
      }
      setText((prev) => `${prev}${prev && !prev.endsWith('\n') ? '\n' : ''}${found.join('\n')}\n`)
      message.success(t('import_sel.qr_found', { count: found.length }))
    } finally {
      setScanning(false)
    }
  }

  const isSearchable = (f: Extracted) =>
    // Unknown until the manifests arrive — assume yes rather than paint the
    // whole list as dead on a slow network.
    searchableTypes.size === 0
    || searchableTypes.has(TYPE_TO_QUERY_TYPE[f.type] || f.type)

  const groups = useMemo(() => {
    const by = new Map<string, Extracted[]>()
    for (const f of found) {
      if (!by.has(f.type)) by.set(f.type, [])
      by.get(f.type)!.push(f)
    }
    return [...by.entries()].sort((a, b) => b[1].length - a[1].length
      || a[0].localeCompare(b[0]))
  }, [found])

  const keyOf = (f: Extracted) => `${f.type}::${f.value}`
  const allKeys = useMemo(() => found.map(keyOf), [found])

  const toggle = (k: string) => setChecked((prev) => {
    const n = new Set(prev)
    n.has(k) ? n.delete(k) : n.add(k)
    return n
  })
  const setGroup = (keys: string[], on: boolean) => setChecked((prev) => {
    const n = new Set(prev)
    keys.forEach((k) => (on ? n.add(k) : n.delete(k)))
    return n
  })

  const reset = () => {
    setText('')
    setChecked(new Set())
  }

  const commit = async () => {
    const picked = found.filter((f) => checked.has(keyOf(f)))
    if (!picked.length) return
    setCommitting(true)
    try {
      // The server recomputes the entity ID from (type, label) — the uuid
      // sent here is only a handle for the request, never an identity.
      const entities = picked.map((f) => ({
        id: crypto.randomUUID(),
        entity_type: TYPE_TO_ENTITY[f.type] || f.type,
        label: f.value,
        // Honest provenance: this came out of a document the investigator
        // holds, not out of a tool. No Admiralty rating is claimed — the
        // framework cannot judge a source it never saw, and asserting one
        // here would be a worse defect than leaving it unrated.
        source: 'manual',
        data: { origin: 'text_import' },
      }))
      const r = await entityApi.commit(caseId, { entities, edges: [] })
      message.success(t('import_sel.committed', { count: r.committed_entities }))
      onCommitted()
      reset()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || t('import_sel.commit_failed'))
    } finally {
      setCommitting(false)
    }
  }

  const checkedCount = checked.size

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={620}
      title={<Space><FileTextOutlined />{t('import_sel.title')}</Space>}
      styles={{ body: { paddingTop: 12 } }}
      footer={
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Text type="secondary">{t('import_sel.selected', { count: checkedCount })}</Text>
          <Space>
            <Button onClick={reset} disabled={!text && !checkedCount}>
              {t('import_sel.clear')}
            </Button>
            <Button
              type="primary" icon={<PlusOutlined />}
              disabled={!checkedCount} loading={committing}
              onClick={commit}
            >
              {t('import_sel.add_selected', { count: checkedCount })}
            </Button>
          </Space>
        </Space>
      }
    >
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Alert
          type="info"
          showIcon
          message={t('import_sel.privacy_head')}
          description={<Paragraph style={{ margin: 0 }}>{t('import_sel.privacy')}</Paragraph>}
        />

        <Input.TextArea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onPaste={onPaste}
          rows={8}
          allowClear
          placeholder={t('import_sel.placeholder')}
          style={{ fontFamily: 'monospace', fontSize: 12 }}
        />

        <Text type="secondary" style={{ fontSize: 12 }}>
          {scanning ? t('import_sel.qr_scanning') : t('import_sel.qr_hint')}
        </Text>

        {text.trim() && found.length === 0 && (
          <Empty description={t('import_sel.nothing_found')} style={{ padding: 16 }} />
        )}

        {found.length > 0 && (
          <>
            <Space wrap>
              <Text strong>{t('import_sel.found', { count: found.length })}</Text>
              <Button size="small" onClick={() => setGroup(allKeys, true)}>
                {t('import_sel.select_all')}
              </Button>
              <Button size="small" onClick={() => setChecked(new Set())}>
                {t('import_sel.select_none')}
              </Button>
            </Space>

            <Collapse
              size="small"
              defaultActiveKey={groups.map(([type]) => type)}
              items={groups.map(([type, list]) => {
                const keys = list.map(keyOf)
                const on = keys.filter((k) => checked.has(k)).length
                return {
                  key: type,
                  label: (
                    <Space>
                      <Tag>{type}</Tag>
                      <Badge count={list.length} showZero color="#8c8c8c" />
                      {on > 0 && <Text type="secondary" style={{ fontSize: 12 }}>
                        {t('import_sel.n_selected', { n: on })}
                      </Text>}
                    </Space>
                  ),
                  extra: (
                    <Checkbox aria-label={t('a11y.select_all_selectors')}
                      checked={on === keys.length}
                      indeterminate={on > 0 && on < keys.length}
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => setGroup(keys, e.target.checked)}
                    />
                  ),
                  children: (
                    <Space direction="vertical" size={4} style={{ width: '100%' }}>
                      {list.map((f) => (
                        <Checkbox
                          key={keyOf(f)}
                          checked={checked.has(keyOf(f))}
                          onChange={() => toggle(keyOf(f))}
                        >
                          <Space size={6}>
                            <Text style={{ wordBreak: 'break-all' }}>
                              {displayLabel(TYPE_TO_ENTITY[f.type] || f.type, f.value) || f.value}
                            </Text>
                            {f.count > 1 && (
                              <Text type="secondary" style={{ fontSize: 11 }}>
                                {t('import_sel.times', { n: f.count })}
                              </Text>
                            )}
                            {f.decoded && (
                              // A value the investigator cannot find in their
                              // own paste needs to be explainable, or it looks
                              // invented.
                              <Tooltip title={t('import_sel.decoded_hint')}>
                                <Tag color="purple" style={{ marginInlineEnd: 0 }}>
                                  {t('import_sel.decoded')}
                                </Tag>
                              </Tooltip>
                            )}
                            {!isSearchable(f) && (
                              <Tooltip title={t('import_sel.not_searchable_hint')}>
                                <Tag style={{ marginInlineEnd: 0 }}>
                                  {t('import_sel.not_searchable')}
                                </Tag>
                              </Tooltip>
                            )}
                          </Space>
                        </Checkbox>
                      ))}
                    </Space>
                  ),
                }
              })}
            />

            <Text type="secondary" style={{ fontSize: 12 }}>
              {t('import_sel.after_hint')}
            </Text>
          </>
        )}
      </Space>
    </Drawer>
  )
}

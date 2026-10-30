import { useMemo, useState } from 'react'
import { Alert, Modal, Select, Tag, Typography, message } from 'antd'
import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { entityApi } from '../../api/client'
import { displayLabel } from '../../utils/label'

const { Paragraph } = Typography

/**
 * Pick the nodes that are the same as `target`. They disappear into it: their
 * links move over, their sources count for it, their names stay as aliases.
 * Not undoable — the modal says so, because a wrong merge in a case file is
 * a wrong statement about identity.
 */
export default function MergeModal({ caseId, target, entities, onClose, onMerged }: {
  caseId: string
  target: any
  entities: any[]
  onClose: () => void
  onMerged: () => void
}) {
  const { t } = useTranslation()
  const [sources, setSources] = useState<string[]>([])
  const options = useMemo(() => entities
    .filter((e) => e.id !== target.id && e.virtual !== true)
    .map((e) => ({ value: e.id, label: `${displayLabel(e.entity_type, e.label)} · ${e.entity_type}` })),
  [entities, target.id])

  const mut = useMutation({
    mutationFn: () => entityApi.merge(caseId, target.id, sources),
    onSuccess: (r: any) => {
      message.success(t('merge.done', { n: r?.merged?.length ?? sources.length, rewired: r?.edges_rewired ?? 0 }))
      onMerged()
      onClose()
    },
    onError: (e: any) => message.error(e?.response?.data?.detail === 'merge_needs_customer_store'
      ? t('merge.err_store') : (e?.response?.data?.detail || t('merge.err'))),
  })

  return (
    <Modal open title={t('merge.title')} onCancel={onClose} onOk={() => mut.mutate()}
           okText={t('merge.ok', { n: sources.length })} okButtonProps={{ disabled: !sources.length, danger: true }}
           confirmLoading={mut.isPending} cancelText={t('common.cancel')} width={620}>
      <Paragraph>
        {t('merge.intro')} <Tag color="blue">{displayLabel(target.entity_type, target.label)}</Tag>
      </Paragraph>
      <Select mode="multiple" showSearch optionFilterProp="label" style={{ width: '100%' }}
              placeholder={t('merge.pick')} options={options} value={sources} onChange={setSources}
              aria-label={t('merge.pick')} />
      <Alert type="warning" showIcon style={{ marginTop: 12 }} message={t('merge.warning')} />
    </Modal>
  )
}

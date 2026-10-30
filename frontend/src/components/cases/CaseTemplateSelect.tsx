import { Select } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { searchApi, type Playbook } from '../../api/client'

/** All playbooks, independent of a selector type — shared cache key. */
export function useAllPlaybooks(): Playbook[] {
  const q = useQuery({
    queryKey: ['playbooks', 'all'],
    queryFn: () => searchApi.playbooks(),
    staleTime: 10 * 60 * 1000,
  })
  return q.data?.playbooks || []
}

/**
 * The offence type a case starts from. Sets the search preset, the report
 * outline and the typical next tools — every one of them can still be
 * changed; the template is a starting point, not a rule.
 */
export default function CaseTemplateSelect(props: { value?: string | null; onChange?: (v: string | null) => void }) {
  const { t } = useTranslation()
  const playbooks = useAllPlaybooks()
  return (
    <Select
      allowClear
      value={props.value ?? undefined}
      onChange={(v) => props.onChange?.(v ?? null)}
      placeholder={t('case_template.none')}
      options={playbooks.map((pb) => ({ value: pb.key, label: t(`search.pb_${pb.key}`, { defaultValue: pb.key }) }))}
    />
  )
}

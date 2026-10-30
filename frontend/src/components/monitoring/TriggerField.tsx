import { Alert, Checkbox, Space, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { alertsApi } from '../../api/client'

const { Text } = Typography

/** Old trigger names → what the pipeline actually raises. */
export function useTriggers() {
  return useQuery({ queryKey: ['monitoring-triggers'], queryFn: alertsApi.triggers, staleTime: 60 * 60 * 1000 })
}

/**
 * Map stored values onto the triggers that exist. A config saved with the
 * old six-value list keeps its meaning (`new_account_found` → `new_account`);
 * values that can never fire are returned separately so the form can say
 * so instead of showing a checkbox that does nothing.
 */
export function normaliseTriggers(stored: string[] | undefined, legacy: Record<string, string> | undefined,
                                  available: string[]): { values: string[]; dropped: string[] } {
  const values = new Set<string>(); const dropped: string[] = []
  for (const v of stored || []) {
    const m = available.includes(v) ? v : legacy?.[v]
    if (m) values.add(m); else dropped.push(v)
  }
  return { values: [...values], dropped }
}

/**
 * The alert triggers the backend can really produce (GET /monitoring/triggers).
 * Fetched rather than hard-coded: a fixed list drifts and ends up offering
 * triggers that never fire. No selection means every trigger.
 */
export default function TriggerField({ value, onChange, dropped = [] }: {
  value?: string[]; onChange?: (v: string[]) => void; dropped?: string[]
}) {
  const { t } = useTranslation()
  const q = useTriggers()
  const available = q.data?.available || []
  return (
    <Space direction="vertical" size={4}>
      <Checkbox.Group value={value} onChange={(v) => onChange?.(v as string[])}>
        <Space direction="vertical">
          {available.map((a) => (
            <Checkbox key={a.value} value={a.value}>
              {t(`monitoring.trigger_${a.value}`, { defaultValue: a.description })}
            </Checkbox>
          ))}
        </Space>
      </Checkbox.Group>
      <Text type="secondary" style={{ fontSize: 12 }}>{t('monitoring.triggers_empty_all')}</Text>
      {dropped.length > 0 && (
        <Alert type="warning" showIcon style={{ marginTop: 4 }}
               message={t('monitoring.triggers_dropped', {
                 list: dropped.map((d) => t(`monitoring.trigger_${d}`, { defaultValue: d })).join(', ') })} />
      )}
    </Space>
  )
}

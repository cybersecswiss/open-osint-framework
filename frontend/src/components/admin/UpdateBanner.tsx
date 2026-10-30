import { Alert, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { tenantApi } from '../../api/client'
import { formatDate } from '../../utils/datetime'

const { Paragraph, Text } = Typography

/** Cached for an hour: a release does not appear every minute. */
export function useUpdateStatus(enabled: boolean) {
  return useQuery({
    queryKey: ['update-status'],
    queryFn: tenantApi.updateStatus,
    enabled,
    staleTime: 60 * 60 * 1000,
    retry: false,
  })
}

/**
 * "A newer version of your data store is available" — with what changed, in
 * the admin's language, and the one command to run on their server. Only the
 * tenant can update their agent; the operator has no access to it.
 */
export default function UpdateBanner() {
  const { t, i18n } = useTranslation()
  const { data } = useUpdateStatus(true)
  if (!data || data.state !== 'outdated') return null
  const lang = (i18n.language || 'de').split('-')[0]
  const changes: string[] = data.changes?.[lang] || data.changes?.de || data.changes?.en || []
  return (
    <Alert
      type="info"
      showIcon
      style={{ marginBottom: 16 }}
      message={t('update.title', { latest: data.latest || '?', installed: data.installed || t('update.unknown') })}
      description={
        <div>
          {data.released_at && <Text type="secondary">{t('update.released', { date: formatDate(data.released_at) })}</Text>}
          {changes.length > 0 && (
            <ul style={{ margin: '6px 0 8px 18px', padding: 0 }}>
              {changes.map((c) => <li key={c}>{c}</li>)}
            </ul>
          )}
          <Paragraph style={{ marginBottom: 0 }}>
            {t('update.how')} <Text code copyable>{data.command}</Text>
          </Paragraph>
          <Text type="secondary" style={{ fontSize: 12 }}>{t('update.safety')}</Text>{' '}
          <a href="/handbook?page=changelog">{t('update.all_changes')}</a>
        </div>
      }
    />
  )
}

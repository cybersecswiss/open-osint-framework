import { Alert, Button, Empty, Space, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'

const { Text } = Typography

/**
 * "We could not fetch this" — said once, the same way, everywhere.
 *
 * ## Why this component exists
 *
 * The same defect turned up in many independent places, always in the same
 * shape: a failed request rendered as an ordinary empty result.
 *
 *   * a blank white page instead of "sign-in failed"
 *   * "0 active cases" instead of "the backend did not answer"
 *   * "no data" on the situation report instead of "could not check"
 *   * "no sources configured" instead of "the list did not load"
 *   * an empty case table instead of "the list did not load"
 *   * "job not found" instead of "could not ask" — while the search
 *     was still running on the server
 *
 * Each was fixed on its own, which left slightly different wordings and
 * no reason for the next author to do it at all. This is the reason: one
 * import, and the honest sentence comes with it.
 *
 * ## The rule it encodes
 *
 * **Never let a failure look like an answer.** "Nothing found", "not
 * configured" and "does not exist" are statements about the world; a failed
 * request is a statement about the request. In an investigative tool the
 * difference decides whether somebody concludes their work is gone.
 *
 * So every rendering here says three things: that the fetch failed, that
 * this is not a statement about the data, and how to try again.
 *
 * ## Usage
 *
 *   if (isError) return <LoadFailed onRetry={refetch} />
 *   {isError && <LoadFailed compact onRetry={refetch} what={t('cases.list')} />}
 *
 * `what` names the thing that could not be loaded when a generic sentence
 * would be vaguer than it needs to be. `compact` renders an inline banner
 * for a page that still has other content worth showing; the default is a
 * block for a view that has nothing else.
 */
export default function LoadFailed({
  onRetry, what, hint, compact = false, loading = false,
}: {
  onRetry?: () => void
  /** Names the thing, e.g. "the case list". Optional. */
  what?: string
  /** Replaces the default second sentence when the context needs a better one. */
  hint?: string
  compact?: boolean
  loading?: boolean
}) {
  const { t } = useTranslation()
  const title = what
    ? t('loadfail.title_what', { what })
    : t('loadfail.title')
  const body = hint || t('loadfail.hint')

  const retry = onRetry ? (
    <Button size="small" icon={<ReloadOutlined />} loading={loading}
            onClick={onRetry}>
      {t('loadfail.retry')}
    </Button>
  ) : null

  if (compact) {
    return (
      <Alert type="error" showIcon style={{ marginBottom: 12 }}
             message={title} description={body} action={retry} />
    )
  }

  return (
    <Empty
      image={Empty.PRESENTED_IMAGE_SIMPLE}
      description={
        <Space direction="vertical" size={6}>
          <Text strong>{title}</Text>
          <Text type="secondary" style={{ fontSize: 12, maxWidth: 420, display: 'block' }}>
            {body}
          </Text>
        </Space>
      }
      style={{ padding: 32 }}
    >
      {retry}
    </Empty>
  )
}

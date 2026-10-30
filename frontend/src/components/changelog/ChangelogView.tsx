import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Collapse, Empty, Input, Segmented, Space, Spin, Tag, Typography } from 'antd'
import { useTranslation } from 'react-i18next'
import { formatDate } from '../../utils/datetime'

const { Title, Paragraph, Text } = Typography

type Lang = 'de' | 'fr' | 'it' | 'en'
type L10n = Partial<Record<Lang, string>>
export interface ChangelogItem { id: string; type: 'new' | 'improved' | 'fixed' | 'security'; text: L10n }
export interface ChangelogRelease {
  version: string
  date: string
  kind: 'upcoming' | 'release' | 'development'
  summary?: L10n
  items: ChangelogItem[]
}

// Same live-editable directory as the handbook (bind-mounted, no rebuild).
// The single source for this page, the admin tab and — via scripts/release.sh
// — the "what's new" list of the update hint.
const URL_ = '/wiki/changelog.json'

const TYPE_COLOR: Record<ChangelogItem['type'], string> = {
  new: 'green', improved: 'blue', fixed: 'orange', security: 'red',
}
const TYPE_ORDER: ChangelogItem['type'][] = ['security', 'new', 'improved', 'fixed']

export function pick(t: L10n | undefined, lang: string): string {
  if (!t) return ''
  return t[lang as Lang] || t.de || t.en || Object.values(t)[0] || ''
}

export function useChangelog() {
  const [data, setData] = useState<ChangelogRelease[] | null>(null)
  const [error, setError] = useState(false)
  useEffect(() => {
    let cancelled = false
    fetch(URL_, { cache: 'no-cache' })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      // Only released versions are shown. Entries collected for the next
      // release ("unreleased") stay out of sight until release.sh gives them a
      // version number — the customer sees what they can actually have.
      .then((d) => { if (!cancelled) setData(Array.isArray(d?.releases)
        ? d.releases.filter((r: ChangelogRelease) => r.version !== 'unreleased' && r.kind !== 'upcoming') : []) })
      .catch(() => { if (!cancelled) setError(true) })
    return () => { cancelled = true }
  }, [])
  return { data, error }
}

/**
 * The user-facing changelog: every version from the first development
 * state to the upcoming release, newest first. Written for the authority,
 * not for developers — security items say what improved, never how it
 * could have been attacked.
 *
 * Layout: 130+ entries in one list are unreadable. Only the
 * newest versions are open; a closed version still shows its summary and a
 * count per type. Items are grouped by type. A type filter and a search open
 * exactly the versions that have matches.
 */
export default function ChangelogView({ compact = false }: { compact?: boolean }) {
  const { t, i18n } = useTranslation()
  const lang = (i18n.language || 'de').split('-')[0]
  const { data, error } = useChangelog()
  const [type, setType] = useState<'all' | ChangelogItem['type']>('all')
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState<string[] | null>(null)

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (data || []).map((rel) => ({
      rel,
      items: rel.items.filter((it) => (type === 'all' || it.type === type)
        && (!q || pick(it.text, lang).toLowerCase().includes(q))),
    }))
  }, [data, type, query, lang])

  if (error) return <Alert type="error" showIcon message={t('changelog.load_error')} />
  if (!data) return <Spin />
  if (!data.length) return <Empty />

  const filtering = type !== 'all' || query.trim() !== ''
  // Default: only the current version open.
  const defaultOpen = data.slice(0, 1).map((r) => r.version)
  const activeKeys = filtering
    ? filtered.filter((f) => f.items.length).map((f) => f.rel.version)
    : (open ?? defaultOpen)
  const visible = filtered.filter((f) => !filtering || f.items.length)
  const total = filtered.reduce((n, f) => n + f.items.length, 0)

  return (
    <div style={{ maxWidth: 900 }}>
      {!compact && (
        <>
          <Title level={2} style={{ marginTop: 0 }}>{t('changelog.title')}</Title>
          <Paragraph type="secondary">{t('changelog.intro')}</Paragraph>
        </>
      )}
      <Space wrap style={{ marginBottom: 12 }}>
        <Segmented
          value={type}
          onChange={(v) => setType(v as any)}
          options={[
            { value: 'all', label: t('changelog.filter_all') },
            ...TYPE_ORDER.map((ty) => ({ value: ty, label: t(`changelog.type_${ty}`) })),
          ]}
        />
        <Input.Search allowClear placeholder={t('changelog.search')} style={{ width: 240 }}
                      value={query} onChange={(e) => setQuery(e.target.value)} />
        {filtering
          ? <Text type="secondary">{t('changelog.matches', { n: total })}</Text>
          : <Button size="small" type="link" onClick={() =>
              setOpen(activeKeys.length === data.length ? [] : data.map((r) => r.version))}>
              {activeKeys.length === data.length ? t('changelog.collapse_all') : t('changelog.expand_all')}
            </Button>}
      </Space>
      {filtering && !visible.length && <Empty description={t('changelog.no_match')} />}
      <Collapse
        activeKey={activeKeys}
        onChange={(k) => { if (!filtering) setOpen(k as string[]) }}
        items={visible.map(({ rel, items }) => {
          const counts = TYPE_ORDER.map((ty) => [ty, items.filter((i) => i.type === ty).length] as const)
            .filter(([, n]) => n > 0)
          return {
            key: rel.version,
            label: (
              <div>
                <Space align="baseline" wrap size={8}>
                  <Text strong style={{ fontSize: 16 }}>
                    {rel.version === 'unreleased' ? t('changelog.upcoming_title') : rel.version}
                  </Text>
                  <Text type="secondary">{formatDate(rel.date)}</Text>
                  <Tag color={rel.kind === 'release' ? 'green' : rel.kind === 'upcoming' ? 'purple' : 'default'}>
                    {t(`changelog.kind_${rel.kind}`)}
                  </Tag>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {counts.map(([ty, n]) => `${n} ${t(`changelog.type_${ty}`)}`).join(' · ')}
                  </Text>
                </Space>
                {rel.summary && (
                  <div style={{ marginTop: 2 }}><Text type="secondary">{pick(rel.summary, lang)}</Text></div>
                )}
              </div>
            ),
            children: (
              <div>
                {TYPE_ORDER.map((ty) => {
                  const group = items.filter((i) => i.type === ty)
                  if (!group.length) return null
                  return (
                    <div key={ty} style={{ marginBottom: 10 }}>
                      <Tag color={TYPE_COLOR[ty]} style={{ marginBottom: 4 }}>{t(`changelog.type_${ty}`)}</Tag>
                      <ul style={{ margin: '2px 0 0 0', paddingLeft: 20 }}>
                        {group.map((it) => <li key={it.id} style={{ padding: '2px 0' }}>{pick(it.text, lang)}</li>)}
                      </ul>
                    </div>
                  )
                })}
              </div>
            ),
          }
        })}
      />
    </div>
  )
}

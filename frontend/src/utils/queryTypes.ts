/**
 * Grouped, manifest-driven query-type options for the search selectors.
 *
 * Purely presentational: it does NOT change which module handles which
 * type. It groups the flat type list into logical categories and shows
 * only the types the tenant's available modules actually support (from
 * the /search/modules manifests), so the dropdown never offers a dead
 * type. Any manifest type not covered by a group falls into "More" so a
 * newly added module's query_type is never hidden.
 */

// Category → member query_types, in display order.
export const QUERY_TYPE_GROUPS: { key: string; types: string[] }[] = [
  { key: 'identity',  types: ['username', 'email', 'phone', 'gaia'] },
  { key: 'corporate', types: ['company_name', 'person_name', 'address', 'company_id', 'gln'] },
  { key: 'infra',     types: ['domain', 'ip', 'url', 'hash', 'asn', 'cve'] },
  { key: 'crypto',    types: ['btc_address', 'eth_address'] },
  { key: 'contact',   types: ['pgp_fingerprint', 'jabber_id', 'tox_id', 'session_id'] },
  { key: 'messenger', types: ['tg_channel', 'tg_search', 'tg_msg_search', 'tg_user', 'tg_geo', 'discord_invite', 'discord_id'] },
  // Transport assets. Its own group rather than folded into
  // `corporate`: an investigator holding an IMO number is not doing company
  // research, and burying a ship under "Firmen & Personen" is how a
  // capability stays unused.
  { key: 'transport', types: ['vessel', 'imo_number', 'aircraft'] },
  { key: 'media',     types: ['image_url'] },
  { key: 'darknet',   types: ['onion_address'] },
  { key: 'other',     types: ['keyword'] },
]

const GROUPED = new Set(QUERY_TYPE_GROUPS.flatMap((g) => g.types))

interface GroupedOption {
  label: string
  title: string
  options: { value: string; label: string }[]
}

/** Build antd Select grouped options from the set of supported types. */
export function queryTypeGroupedOptions(
  available: Set<string>,
  t: (k: string, o?: any) => string,
): GroupedOption[] {
  const groups: GroupedOption[] = QUERY_TYPE_GROUPS.map((g) => ({
    label: t(`search.qtgroup_${g.key}`),
    title: g.key,
    options: g.types
      .filter((ty) => available.has(ty))
      .map((ty) => ({ value: ty, label: t(`search.type_${ty}`) })),
  })).filter((g) => g.options.length > 0)

  const leftover = [...available].filter((ty) => !GROUPED.has(ty))
  if (leftover.length) {
    groups.push({
      label: t('search.qtgroup_more'),
      title: 'more',
      options: leftover.map((ty) => ({
        value: ty, label: t(`search.type_${ty}`, { defaultValue: ty }),
      })),
    })
  }
  return groups
}

/** First supported type in display order — a safe default/fallback. */
export function firstAvailableType(available: Set<string>): string | undefined {
  for (const g of QUERY_TYPE_GROUPS) {
    for (const ty of g.types) if (available.has(ty)) return ty
  }
  return [...available][0]
}

/** Union of every query_type across the given module manifests. */
export function availableQueryTypes(moduleList: any[]): Set<string> {
  const s = new Set<string>()
  for (const m of moduleList) {
    for (const tool of m.tools || []) {
      for (const qt of tool.query_types || []) s.add(qt)
    }
  }
  return s
}

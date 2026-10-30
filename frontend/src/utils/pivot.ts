import { displayLabel } from './label'

/**
 * Derive a sensible advanced-search ("Erweiterte Suche") seed from a
 * finding/entity: the value to search for + the query_type most tools
 * expect. Returns null when the entity can't meaningfully be pivoted on
 * (e.g. a password fingerprint with no stored cleartext). The user can
 * still change the query_type in the drawer.
 */
export interface PivotSeed { query: string; type: string }

// entity_type → query_type for the common cases.
const TYPE_TO_QT: Record<string, string> = {
  email_address: 'email',
  email: 'email',
  username: 'username',
  domain: 'domain',
  dns_a: 'domain', dns_aaaa: 'domain', dns_mx: 'domain',
  dns_ns: 'domain', dns_cname: 'domain', dns_txt: 'domain',
  ip: 'ip', ip_address: 'ip',
  phone: 'phone', phone_number: 'phone',
  btc_address: 'btc_address',
  eth_address: 'eth_address',
  // Telegram nodes (from messenger/telegram/forums-linkbase) pivot straight
  // into the Telegram tools rather than a generic keyword search.
  telegram_channel: 'tg_channel',
  telegram_user: 'tg_user',
  keyword: 'keyword',
  // A location node (registered seat, EXIF GPS, visual geolocation, Telegram
  // geo) pivots into corporate/geo_ch, which resolves it to an address,
  // building, parcel and canton. Without this it fell through to `keyword`,
  // i.e. a full-text search for a place name — which no tool here answers
  // usefully and which is how these nodes stayed dead ends.
  location: 'address',
  // A person or company node pivots as a NAME, not as free text. Both types
  // reach the same tools either way, but `keyword` is the wrong default and
  // costs the name-first tools their intended query_type.
  person: 'person_name',
  organization: 'company_name',
  // A UID found by shab_registry pivots into zefix_registry, which answers
  // it with the company's CURRENT register entry — purpose, capital,
  // previous names and the branch/takeover network. That chain is the whole
  // reason the two register tools exist side by side.
  company_id: 'company_id',
  // With onion_scrape enabled, pivoting an onion node reads that service.
  onion_service: 'onion_address',
  breach: 'keyword',
  first_name: 'keyword', last_name: 'keyword',
}

export function pivotSeed(entity: any): PivotSeed | null {
  if (!entity) return null
  const et = entity.entity_type as string
  const d = entity.data || {}

  // Social account labels are "platform/username" — pivot on the handle.
  if (et === 'social_account') {
    const handle = d.username || d.account ||
      (entity.label || '').split('/').pop()
    return handle ? { query: String(handle), type: 'username' } : null
  }

  const value = displayLabel(et, entity.label)
  if (!value) return null
  const type = TYPE_TO_QT[et] || 'keyword'
  return { query: value, type }
}

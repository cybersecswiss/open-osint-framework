/**
 * Narrowing facets for free-text searches.
 *
 * A facet is appended to the query, so "Crimson Wolves" + "Zürich" runs
 * "Crimson Wolves Zürich" as an additional pass. The backend does the actual
 * expansion (routers/search.py::_expand_queries) — this file only supplies
 * the suggestions.
 *
 * The values are deliberately NOT translated. They are search terms, not UI
 * labels: a canton is searched under its official name ("Genève", "Ticino"),
 * which is also how it appears in the sources. Translating them would
 * silently change what gets searched depending on the analyst's UI language.
 * Only the group headings are translated.
 *
 * The field accepts free text too — no curated list covers every need
 * (a city, a district, a street name).
 */

export interface FacetGroup {
  /** i18n key for the group heading */
  key: string
  values: string[]
}

export const FACET_GROUPS: FacetGroup[] = [
  {
    key: 'region',
    values: ['Schweiz', 'Deutschschweiz', 'Romandie', 'Ticino'],
  },
  {
    // Official cantonal names — the spelling used in official sources.
    key: 'canton',
    values: [
      'Zürich', 'Bern', 'Luzern', 'Uri', 'Schwyz', 'Obwalden', 'Nidwalden',
      'Glarus', 'Zug', 'Fribourg', 'Solothurn', 'Basel-Stadt',
      'Basel-Landschaft', 'Schaffhausen', 'Appenzell Ausserrhoden',
      'Appenzell Innerrhoden', 'St. Gallen', 'Graubünden', 'Aargau',
      'Thurgau', 'Ticino', 'Vaud', 'Valais', 'Neuchâtel', 'Genève', 'Jura',
    ],
  },
  {
    key: 'international',
    values: ['Europa', 'International', 'Deutschland', 'Österreich',
             'Frankreich', 'Italien'],
  },
  {
    // Phenomenon areas, phrased as fields of crime — never as an accusation
    // against a named group (same framing as the threat catalogue).
    key: 'phenomenon',
    values: ['Drogenhandel', 'Waffenhandel', 'Geldwäscherei',
             'Menschenhandel', 'Schleusertätigkeit', 'Cybercrime',
             'Erpressung', 'Rockerkriminalität'],
  },
]

/** Max facets per search — must mirror MAX_FACETS in routers/search.py. */
export const MAX_FACETS = 5

/**
 * Selector types a facet can meaningfully narrow — must mirror
 * `_FACETABLE_QUERY_TYPES` in routers/search.py. Free text only: appending
 * "Zürich" to an e-mail address, a hash or a wallet yields a selector that
 * matches nothing, so those types drop facets on both sides.
 *
 * `company_name` / `person_name` behave like `keyword`: a company or
 * person name narrows exactly like a keyword, and "Example Trading" + "Genève"
 * is the case the `corporate` module was built for.
 */
export const FACETABLE_TYPES = new Set(['keyword', 'company_name', 'person_name'])

export const isFacetable = (queryType: string) => FACETABLE_TYPES.has(queryType)

/** antd Select option groups. */
export function facetOptions(t: (k: string) => string) {
  return FACET_GROUPS.map((g) => ({
    label: t(`search.facetgroup_${g.key}`),
    title: g.key,
    options: g.values.map((v) => ({ value: v, label: v })),
  }))
}

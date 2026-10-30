/**
 * How a case map is arranged: where the nodes sit and which boxes the
 * investigator drew around them.
 *
 * Kept as plain functions, away from the component, because the awkward parts
 * are not about drawing — they are about what happens when the case CHANGES
 * under an arrangement somebody already made. Three rules are load-bearing:
 *
 *  1. **A new finding must never move what is already placed.** A search that
 *     adds twelve nodes to a map an investigator spent ten minutes arranging
 *     must leave those ten minutes intact. Only nodes without a stored
 *     position get placed, and they get placed beside the existing picture —
 *     not on top of it, and not at (0,0) where they would pile up.
 *
 *  2. **A group's box is derived, never stored.** What is stored is the
 *     decision — these nodes belong together, and this is what I call them.
 *     The rectangle follows from where the members are, so a box can never
 *     end up somewhere its contents are not.
 *
 *  3. **An aggregated link is not a link.** When a group is collapsed, the
 *     connections its members have to the outside are drawn as one line per
 *     neighbour. That line stands for N assertions and says so; drawing it
 *     like an ordinary edge would invent a relation nobody asserted.
 */

export interface Pos { x: number; y: number }

export interface LayoutGroup {
  id: string
  label: string
  color: string
  members: string[]
  collapsed: boolean
}

export interface CaseLayout {
  positions: Record<string, Pos>
  groups: LayoutGroup[]
}

export const EMPTY_LAYOUT: CaseLayout = { positions: {}, groups: [] }

/** Tolerates anything the API might return, including {} or a null. */
export function normaliseLayout(raw: any): CaseLayout {
  const positions: Record<string, Pos> = {}
  for (const [k, v] of Object.entries((raw?.positions as any) || {})) {
    const p = v as any
    if (typeof p?.x === 'number' && typeof p?.y === 'number') {
      positions[String(k)] = { x: p.x, y: p.y }
    }
  }
  const groups: LayoutGroup[] = ((raw?.groups as any[]) || [])
    .filter((g) => g && g.id)
    .map((g) => ({
      id: String(g.id),
      label: String(g.label || ''),
      color: String(g.color || ''),
      members: (g.members || []).map((m: any) => String(m)),
      collapsed: !!g.collapsed,
    }))
  return { positions, groups }
}

export const NODE_W = 200
export const NODE_H = 52
/** Breathing room between a group's outermost node and its box. */
export const GROUP_PAD = 28
/** Extra space at the top of a box for its name. */
export const GROUP_HEADER = 26

/**
 * Ids that still need placing, i.e. everything the stored layout has not
 * seen. Separated from the placing itself so a caller can tell whether an
 * automatic pass is needed at all.
 */
export function unplaced(ids: string[], layout: CaseLayout): string[] {
  return ids.filter((id) => !layout.positions[id])
}

/**
 * Where to drop nodes the arrangement has never seen.
 *
 * They go in a column to the RIGHT of everything already placed, so an
 * existing arrangement keeps its shape and the new arrivals are visibly new
 * rather than scattered into it. On an empty map this is simply a grid.
 */
export function placeNew(
  ids: string[], layout: CaseLayout, perColumn = 8,
): Record<string, Pos> {
  const known = Object.values(layout.positions)
  const startX = known.length
    ? Math.max(...known.map((p) => p.x)) + NODE_W + 80
    : 0
  const startY = known.length ? Math.min(...known.map((p) => p.y)) : 0
  const out: Record<string, Pos> = {}
  ids.forEach((id, i) => {
    out[id] = {
      x: startX + Math.floor(i / perColumn) * (NODE_W + 60),
      y: startY + (i % perColumn) * (NODE_H + 34),
    }
  })
  return out
}

/**
 * Move a group's members into a tight block near where they already are.
 *
 * This exists because a derived box around scattered members is a LIE: it
 * grows to cover everything between them, and every unrelated node that
 * happens to fall inside it reads as a member. Membership has to be legible
 * from the picture or the box is decoration.
 *
 * The block is centred on the members' own centroid, so grouping moves them
 * as little as it can — the investigator's arrangement is disturbed once, on
 * purpose, at the moment they ask for a group, and not afterwards.
 */
export function packMembers(
  members: string[], positions: Record<string, Pos>,
  others: string[] = [], perRow = 3,
): Record<string, Pos> {
  const placed = members.filter((m) => positions[m])
  if (!placed.length) return {}

  const cols = Math.min(perRow, placed.length)
  const stepX = NODE_W + 40
  const stepY = NODE_H + 30
  const rel = placed.map((_m, i) => ({
    x: (i % cols) * stepX,
    y: Math.floor(i / cols) * stepY,
  }))

  // Translate the finished block so its centroid lands on the members' own
  // centroid. Doing it after the fact rather than deriving an origin keeps
  // this exact for a ragged last row, where a computed origin is off.
  const cx = placed.reduce((a, m) => a + positions[m].x, 0) / placed.length
  const cy = placed.reduce((a, m) => a + positions[m].y, 0) / placed.length
  const rcx = rel.reduce((a, p) => a + p.x, 0) / rel.length
  const rcy = rel.reduce((a, p) => a + p.y, 0) / rel.length

  const blockW = (cols - 1) * stepX + NODE_W
  const blockH = (Math.ceil(placed.length / cols) - 1) * stepY + NODE_H
  const strangers = others
    .filter((id) => !members.includes(id) && positions[id])
    .map((id) => positions[id])

  // Slide the block until no NON-member sits inside it.
  //
  // The alternative — nudging the strangers aside — would move nodes the
  // investigator never selected, which is a surprising thing for "group
  // these five" to do. Moving only what was asked about is the smaller
  // surprise, and it is what makes "inside the box = in the group" true
  // instead of merely usually true.
  let offX = 0
  let offY = 0
  for (let step = 0; step < 40; step++) {
    const x0 = cx - rcx + offX - GROUP_PAD
    const y0 = cy - rcy + offY - GROUP_PAD - GROUP_HEADER
    const x1 = x0 + blockW + GROUP_PAD * 2
    const y1 = y0 + blockH + GROUP_PAD * 2 + GROUP_HEADER
    const clash = strangers.some((p) =>
      p.x + NODE_W > x0 && p.x < x1 && p.y + NODE_H > y0 && p.y < y1)
    if (!clash) break
    offY += stepY          // straight down: predictable, and keeps the
    offX += 0              // horizontal reading order of the map intact
  }

  const out: Record<string, Pos> = {}
  placed.forEach((m, i) => {
    out[m] = {
      x: Math.round(cx - rcx + offX + rel[i].x),
      y: Math.round(cy - rcy + offY + rel[i].y),
    }
  })
  return out
}

/**
 * Ids that sit inside a group's box without belonging to it.
 *
 * Reported rather than prevented: the map is the investigator's, and a node
 * parked inside a box is not an error. But the UI needs to know, because a
 * stranger inside the rectangle is exactly what makes a group unreadable —
 * so it can offer to tidy up instead of silently looking wrong.
 */
export function strangersInBox(
  box: GroupBox, positions: Record<string, Pos>, candidates: string[],
): string[] {
  const members = new Set(box.members)
  return candidates.filter((id) => {
    if (members.has(id)) return false
    const p = positions[id]
    if (!p) return false
    return p.x + NODE_W > box.x && p.x < box.x + box.w
      && p.y + NODE_H > box.y && p.y < box.y + box.h
  })
}

export interface GroupBox {
  id: string
  label: string
  color: string
  collapsed: boolean
  members: string[]
  x: number
  y: number
  w: number
  h: number
}

/**
 * The rectangle for each group, computed from where its members sit.
 *
 * A group whose members have all been removed from the map yields no box —
 * an empty rectangle floating on the canvas would be a leftover, not a
 * grouping. The caller decides whether to drop such a group entirely; this
 * function does not silently delete the investigator's decision.
 */
export function groupBoxes(
  groups: LayoutGroup[], positions: Record<string, Pos>, visible: Set<string>,
): GroupBox[] {
  const out: GroupBox[] = []
  for (const g of groups) {
    const pts = g.members
      .filter((m) => visible.has(m) && positions[m])
      .map((m) => positions[m])
    if (!pts.length) continue
    const minX = Math.min(...pts.map((p) => p.x))
    const minY = Math.min(...pts.map((p) => p.y))
    const maxX = Math.max(...pts.map((p) => p.x)) + NODE_W
    const maxY = Math.max(...pts.map((p) => p.y)) + NODE_H
    out.push({
      id: g.id, label: g.label, color: g.color, collapsed: g.collapsed,
      members: g.members,
      x: minX - GROUP_PAD,
      y: minY - GROUP_PAD - GROUP_HEADER,
      w: (maxX - minX) + GROUP_PAD * 2,
      h: (maxY - minY) + GROUP_PAD * 2 + GROUP_HEADER,
    })
  }
  return out
}

/** entity id → id of the collapsed group hiding it, if any. */
export function collapsedOwner(groups: LayoutGroup[]): Map<string, string> {
  const m = new Map<string, string>()
  for (const g of groups) {
    if (!g.collapsed) continue
    for (const id of g.members) m.set(id, g.id)
  }
  return m
}

export interface RoutedEdge {
  id: string
  source: string
  target: string
  /** How many real edges this line stands for. 1 = itself. */
  count: number
  /** True when endpoints were replaced by a collapsed group. */
  aggregated: boolean
  /** The single underlying edge when count === 1, for the context menu. */
  edge: any
}

/**
 * Re-point edges whose endpoints are hidden inside a collapsed group.
 *
 * Edges that end up with both ends in the SAME collapsed group disappear —
 * they are internal to a box the user chose not to look inside. Everything
 * else is merged per (source, target) pair and carries the number of real
 * links behind it, so an aggregate can be labelled as an aggregate.
 */
export function routeEdges(
  edges: any[], groups: LayoutGroup[], visible: Set<string>,
): RoutedEdge[] {
  const owner = collapsedOwner(groups)
  const merged = new Map<string, RoutedEdge>()
  for (const e of edges) {
    const rawFrom = String(e.from_entity)
    const rawTo = String(e.to_entity)
    const from = owner.get(rawFrom) || rawFrom
    const to = owner.get(rawTo) || rawTo
    if (from === to) continue                  // internal to a closed box
    const fromOk = owner.has(rawFrom) || visible.has(rawFrom)
    const toOk = owner.has(rawTo) || visible.has(rawTo)
    if (!fromOk || !toOk) continue             // an end is not on the map
    const rerouted = owner.has(rawFrom) || owner.has(rawTo)
    if (!rerouted) {
      // Nothing was collapsed here, so this edge stays itself. Two real
      // edges between the same pair are two assertions — merging them would
      // hide one and, worse, make the investigator's own link unreachable
      // for the right-click that retracts it.
      merged.set(String(e.id), {
        id: String(e.id), source: from, target: to,
        count: 1, aggregated: false, edge: e,
      })
      continue
    }
    const key = `agg:${from}->${to}`
    const cur = merged.get(key)
    if (cur) {
      cur.count += 1
      cur.edge = null                          // no single edge to act on
    } else {
      merged.set(key, {
        id: key, source: from, target: to,
        count: 1, aggregated: true, edge: e,
      })
    }
  }
  return [...merged.values()]
}

import { useEffect, useMemo, useRef, useState } from 'react'
import cytoscape from 'cytoscape'
// @ts-expect-error — fcose has its own untyped registration
import fcose from 'cytoscape-fcose'
import { Spin, Empty, Space, Button, Checkbox, Select, Tag, Slider, Dropdown, MenuProps, message, Tooltip } from 'antd'
import {
  ExpandOutlined,
  FullscreenOutlined,
  PlayCircleOutlined,
  CameraOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'

cytoscape.use(fcose)

interface GraphData {
  entities: Array<{
    id: string
    entity_type: string
    label: string
    data: Record<string, any>
    is_relevant?: boolean | null
    admiralty?: string | null
    corroborated_by?: string[]
    notes?: string | null
    url?: string | null
    relevance_score?: number
  }>
  edges: Array<{
    id: string; from_entity: string; to_entity: string; relation_type: string
    /** Tool that asserted the relation, when the runner reported one. */
    source?: string | null
  }>
}

interface Props {
  data: GraphData | null
  loading: boolean
  onNodeClick: (node: any) => void
  /** Double-click expands a node into a fresh search.
   * Caller switches to the search tab and pre-fills the form. */
  onNodeExpand?: (node: any) => void
  /** Context-menu actions. Caller decides what they do
   * (typically: open a quick-create monitoring modal pre-filled with
   * this entity / toggle the entity's is_relevant flag / drop the
   * entity as a false positive). Each action is omitted from the
   * menu when the corresponding callback is unset. */
  onAddMonitoring?: (node: any) => void
  onToggleRelevant?: (node: any) => void
  onDeleteEntity?: (node: any) => void
  /** Optional case identifier — used to name the screenshot file. */
  caseLabel?: string
}

export const NODE_COLORS: Record<string, string> = {
  person: '#1677ff',
  social_account: '#52c41a',
  organization: '#faad14',
  email_address: '#ff4d4f',
  domain: '#722ed1',
  username: '#13c2c2',
  ip_address: '#eb2f96',
  phone_number: '#a0d911',
  location: '#fa8c16',
  telegram_channel: '#229ed9',
  telegram_message: '#3aa8e0',
  telegram_media: '#7cc6ea',
  telegram_user: '#0088cc',
  telegram_ioc: '#d4380d',
  telegram_linked_channel: '#b37feb',
  search_link: '#adc6ff',
  crime_forum: '#cf1322',
  forum_hit: '#f5222d',
  threat_actor: '#a8071a',
  onion_service: '#391085',
  google_account: '#ea4335',
  stealer_infection: '#d4380d',
  pgp_key: '#7cb305',
  pgp_fingerprint: '#5b8c00',
  wallet_label: '#fa541c',
  service: '#08979c',
  vulnerability: '#cf1322',
  favicon_hash: '#d48806',
  typosquat_domain: '#d4380d',
  image: '#13a8a8', camera: '#08979c',
  seizure_notice: '#a8071a',
  dating_profile: '#eb2f96',
  // The two Swiss authority sources. A FINMA warning is the strongest
  // negative statement any source here makes about a company, so it gets
  // the alarm red the ransomware/seizure nodes use; a court decision is a
  // document, not an accusation, and reads in the neutral slate of a record.
  warning_entry: '#cf1322',
  court_decision: '#595959',
  // Deep-sea blue for the hull, a lighter air blue for the airframe; their
  // permanent identifiers a shade darker than the asset they belong to, so
  // a graph shows at a glance which node cannot be renamed away.
  vessel: '#0958d9',
  aircraft: '#1677ff',
  imo_number: '#003eb3',
  aircraft_serial: '#0958d9',
  // The health-professional GLN, in the same darker shade the other
  // rename-proof identifiers use.
  gln: '#003eb3',
  jabber_id: '#9254de',
  tox_id: '#642ab5',
  session_id: '#391085',
  default: '#8c8c8c',
}

type LayoutName = 'breadthfirst' | 'fcose' | 'concentric' | 'circle' | 'grid' | 'cose'

// Order = order in the dropdown. breadthfirst is first because it's
// the new default — best fit for OSINT cases where a single query
// fans out into siblings (sites/breaches/aliases), so the eye reads
// "what came back from this selector" at a glance.
const LAYOUT_KEYS: LayoutName[] = ['breadthfirst', 'fcose', 'concentric', 'circle', 'grid', 'cose']

const CAPS = [50, 100, 250, 500, 1000]

// Zoom bounds for the manual +/- buttons and the vertical slider. The
// wheel still works as before; these just give the on-screen controls a
// sane, clamped range so the slider maps cleanly and the buttons can't
// zoom into oblivion. ZOOM_STEP is multiplicative per +/- click.
const MIN_ZOOM = 0.1
const MAX_ZOOM = 4
const ZOOM_STEP = 1.3

export default function GraphView({
  data, loading, onNodeClick, onNodeExpand,
  onAddMonitoring, onToggleRelevant, onDeleteEntity, caseLabel,
}: Props) {
  const { t } = useTranslation()
  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef = useRef<cytoscape.Core | null>(null)

  // ── controls ────────────────────────────────────────────────
  // breadthfirst gives a tree-like view with the queried selector at
  // the top and discovered findings layered below — much more
  // readable for a typical OSINT case than the organic fcose blob.
  const [layout, setLayout] = useState<LayoutName>('breadthfirst')
  // Default 100 — at this size Cytoscape's pan/zoom stays smooth on
  // a typical investigator laptop. Bump via the dropdown to 250/500/1000
  // when needed; layout time scales O(N²) with fcose.
  const [cap, setCap] = useState<number>(100)
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set())
  const [showLabels, setShowLabels] = useState<boolean>(true)
  // Live zoom level, mirrored from cytoscape so the +/- buttons and the
  // vertical slider stay in sync no matter how the user zoomed (wheel,
  // buttons, slider, or a layout auto-fit).
  const [zoom, setZoom] = useState<number>(1)
  // Hash of the last rendered topology so polling refetches that
  // don't change the visible set don't trigger an expensive
  // re-layout (was the actual cause of "zoom feels laggy" — every
  // poll = full layout re-run).
  const lastTopoRef = useRef<string>("")

  // Right-click context menu state. Anchored to a 1×1 invisible div
  // positioned at the click coordinates, with Antd's Dropdown.
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; node: any } | null>(null)

  // ── Connection path (D2) ──────────────────────────────────────
  // Two picked nodes, the shortest chain between them, and the tool that
  // asserted each link. Pure client-side maths on the graph already loaded:
  // no new collection, nothing stored, nothing leaves the browser.
  const [pathMode, setPathMode] = useState(false)
  const [pathEnds, setPathEnds] = useState<string[]>([])
  const [pathHops, setPathHops] = useState<any[] | null>(null)
  // The cytoscape tap handler is registered once, so it would capture the
  // first render's `pathMode`. A ref keeps it reading the current value.
  const pathModeRef = useRef(false)
  useEffect(() => { pathModeRef.current = pathMode }, [pathMode])

  const pickPathEnd = (id: string) => {
    setPathEnds((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id)
      return prev.length >= 2 ? [prev[1], id] : [...prev, id]
    })
  }

  // entity types and counts in the (uncapped) data
  const typeCounts = useMemo(() => {
    const m: Record<string, number> = {}
    if (data) {
      for (const e of data.entities) m[e.entity_type] = (m[e.entity_type] || 0) + 1
    }
    return m
  }, [data])

  // ── one-shot cytoscape init ─────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return
    cyRef.current = cytoscape({
      container: containerRef.current,
      // Zoom & rendering performance:
      //   - wheelSensitivity 0.2: smaller steps, smoother feel
      //   - textureOnViewport + hideEdgesOnViewport + hideLabelsOnViewport:
      //     during pan/zoom, render the canvas as a texture instead of
      //     redrawing every node. ~10× speed-up at >300 nodes.
      //   - motionBlur off: paint on every frame, not blur-stacked.
      //   - pixelRatio 1: skip retina-doubling on the offscreen buffer.
      wheelSensitivity: 0.2,
      textureOnViewport: true,
      hideEdgesOnViewport: true,
      hideLabelsOnViewport: true,
      motionBlur: false,
      pixelRatio: 1,
      style: [
        {
          selector: 'node',
          style: {
            'background-color': (ele: any) =>
              NODE_COLORS[ele.data('entity_type')] || NODE_COLORS.default,
            'label': '',
            'color': '#262626',
            'font-size': '9px',
            'text-valign': 'bottom',
            'text-halign': 'center',
            'text-outline-color': '#fff',
            'text-outline-width': 2,
            // Kompakt: lange Labels (URLs, hashes, IBANs) werden mit
            // Ellipsis abgeschnitten. Volle Wert sieht der Analyst in
            // der NodeDetail-Karte rechts.
            'text-max-width': '120px',
            'text-wrap': 'ellipsis',
            'text-overflow-wrap': 'anywhere',
            'width': 'data(_size)',
            'height': 'data(_size)',
            'border-width': 0,
          } as any,
        },
        {
          selector: 'node[?_show_label]',
          style: { label: 'data(label)' } as any,
        },
        {
          selector: 'node:selected',
          style: { 'border-width': 3, 'border-color': '#1677ff', label: 'data(label)' } as any,
        },
        {
          selector: 'node.hovered',
          style: { label: 'data(label)', 'border-width': 2, 'border-color': '#1677ff' } as any,
        },
        {
          // Corroborated findings get a double ring. Deliberately declared
          // BEFORE the relevance rule so an analyst's own gold flag still
          // wins the border when both apply.
          selector: 'node[?_corroborated]',
          style: {
            'border-width': 3,
            'border-color': '#389e0d',
            'border-style': 'double',
          } as any,
        },
        {
          // Entities the investigator marked as relevant
          // get a gold border + halo so they pop out from the rest of
          // the graph. Heavier styling than the original 3px border so
          // analysts can tell at a glance which nodes were flagged.
          // The list view also shows a star icon for these.
          selector: 'node[?_relevant]',
          style: {
            'border-width': 6,
            'border-color': '#faad14',
            'border-style': 'solid',
            'overlay-padding': 6,
            'overlay-color': '#faad14',
            'overlay-opacity': 0.18,
            label: 'data(label)',
          } as any,
        },
        {
          selector: 'edge',
          style: {
            width: 1,
            'line-color': '#bfbfbf',
            'target-arrow-color': '#bfbfbf',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            opacity: 0.6,
            label: '',
          } as any,
        },
        {
          selector: 'edge.adjacent-to-hover',
          style: {
            width: 2,
            'line-color': '#1677ff',
            'target-arrow-color': '#1677ff',
            opacity: 1,
            label: 'data(relation_type)',
            color: '#595959',
            'font-size': '9px',
          } as any,
        },
        // ── Connection path (D2) ──
        // "How are these two related?" is the question an investigator asks
        // most and could until now only answer by staring at the graph. The
        // path is drawn, everything else recedes — dimming rather than hiding,
        // because the surrounding structure is what makes a path readable.
        {
          selector: '.dimmed',
          style: { opacity: 0.12 } as any,
        },
        {
          selector: 'node.onpath',
          style: {
            'border-width': 4,
            'border-color': '#fa8c16',
            opacity: 1,
          } as any,
        },
        {
          selector: 'edge.onpath',
          style: {
            width: 3,
            'line-color': '#fa8c16',
            'target-arrow-color': '#fa8c16',
            opacity: 1,
            label: 'data(relation_type)',
            color: '#d46b08',
            'font-size': '9px',
          } as any,
        },
        {
          selector: 'node.pathend',
          style: {
            'border-width': 5,
            'border-color': '#d4380d',
            opacity: 1,
          } as any,
        },
      ],
    })

    // Clamp the zoom range so the slider maps to it cleanly and the
    // wheel/buttons can't zoom past usable limits. Keep React state in
    // sync with every zoom change (wheel, button, slider, layout-fit).
    cyRef.current.minZoom(MIN_ZOOM)
    cyRef.current.maxZoom(MAX_ZOOM)
    cyRef.current.on('zoom', () => {
      if (cyRef.current) setZoom(cyRef.current.zoom())
    })

    cyRef.current.on('tap', 'node', (e) => {
      const d = e.target.data()
      // In path mode a tap picks an endpoint instead of opening the detail —
      // otherwise every pick would also swap the side panel, which is exactly
      // the context switch this feature exists to avoid.
      if (pathModeRef.current) { pickPathEnd(d.id); return }
      onNodeClick(d)
    })

    // Double-click expands. Cytoscape only fires `dbltap`
    // for two taps on the same element within ~250 ms.
    cyRef.current.on('dbltap', 'node', (e) => {
      const node = e.target.data()
      onNodeExpand?.(node)
    })

    // Right-click opens a context menu. cxttap fires for
    // both right-click and long-press on touch. We use the original
    // DOM event's clientX/Y because that's the cleanest way to anchor
    // a position-fixed Dropdown in viewport space; cytoscape's
    // renderedPosition is canvas-relative which is fine but adds a
    // bounding-rect lookup per click.
    //
    // setTimeout(0): cytoscape fires cxttap synchronously inside the
    // browser's contextmenu event, so the same event continues to
    // bubble. Antd's outside-click detector on the document then sees
    // the right-click as "click outside the dropdown" and fires
    // onOpenChange(false) immediately — the menu briefly opens and
    // disappears. Deferring the state update lets the original event
    // finish before the dropdown mounts, so Antd doesn't conflate the
    // opening click with an outside click.
    cyRef.current.on('cxttap', 'node', (e) => {
      const node = e.target.data()
      const orig = e.originalEvent as MouseEvent | undefined
      // Defensive position fallback: if originalEvent is missing for
      // some reason, derive it from cytoscape's canvas-relative coords.
      let x = orig?.clientX
      let y = orig?.clientY
      if (x == null || y == null) {
        const rect = containerRef.current?.getBoundingClientRect()
        x = (rect?.left || 0) + (e.renderedPosition?.x || 0)
        y = (rect?.top || 0) + (e.renderedPosition?.y || 0)
      }
      const finalX = x, finalY = y
      setTimeout(() => setCtxMenu({ x: finalX, y: finalY, node }), 0)
    })
    // Click anywhere on the canvas (not on a node) closes the menu.
    cyRef.current.on('tap', (e) => {
      if (e.target === cyRef.current) setCtxMenu(null)
    })

    cyRef.current.on('mouseover', 'node', (e) => {
      const n = e.target
      n.addClass('hovered')
      n.connectedEdges().addClass('adjacent-to-hover')
    })
    cyRef.current.on('mouseout', 'node', (e) => {
      const n = e.target
      n.removeClass('hovered')
      n.connectedEdges().removeClass('adjacent-to-hover')
    })

    // Native DOM listener with capture-phase: prevents the browser's
    // own context menu AND stops the event from bubbling to Antd's
    // document-level outside-click detector. React's onContextMenu
    // wasn't enough on its own — by the time React's synthetic event
    // ran, the right-click had already reached the document.
    const containerEl = containerRef.current
    const suppressContextMenu = (e: Event) => {
      e.preventDefault()
      e.stopPropagation()
    }
    containerEl.addEventListener('contextmenu', suppressContextMenu, true)

    return () => {
      containerEl.removeEventListener('contextmenu', suppressContextMenu, true)
      cyRef.current?.destroy()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── data + layout effect ────────────────────────────────────
  useEffect(() => {
    if (!cyRef.current || !data) return
    const cy = cyRef.current

    // 1. apply type filter + cap
    const visible = data.entities.filter((e) => !hiddenTypes.has(e.entity_type))
    const capped = visible.slice(0, cap)
    const validIds = new Set(capped.map((e) => e.id))

    // Skip the rebuild + relayout if neither the visible set nor any
    // is_relevant flag has changed since last render. Cytoscape's
    // layout pass is the single most expensive operation here, and
    // polling refetches typically return the same data — running
    // fcose on every 3-second poll is the actual cause of the laggy
    // feeling the user reported.
    const topoHash = [
      layout, cap, showLabels,
      ...capped.map((e) => `${e.id}:${e.entity_type}:${e.is_relevant ? 1 : 0}`),
      ...data.edges
        .filter((e) => validIds.has(e.from_entity) && validIds.has(e.to_entity))
        .map((e) => e.id),
    ].join("|")
    if (topoHash === lastTopoRef.current) return
    lastTopoRef.current = topoHash

    cy.batch(() => {
      cy.elements().remove()
    })

    // 2. compute degree per node (for size scaling)
    const degree: Record<string, number> = {}
    for (const e of data.edges) {
      if (validIds.has(e.from_entity)) degree[e.from_entity] = (degree[e.from_entity] || 0) + 1
      if (validIds.has(e.to_entity))   degree[e.to_entity]   = (degree[e.to_entity]   || 0) + 1
    }
    const maxDegree = Math.max(1, ...Object.values(degree))

    const nodes = capped.map((e: any) => {
      const d = degree[e.id] || 0
      // size 16..48 by degree; constant 22 if all isolated
      const size = maxDegree === 0
        ? 22
        : Math.round(16 + (d / maxDegree) * 32)
      return {
        data: {
          id: e.id,
          label: e.label,
          entity_type: e.entity_type,
          is_relevant: e.is_relevant,
          _size: size,
          _show_label: showLabels,
          // Cytoscape style selectors can't read nullable booleans
          // robustly via [?prop] when the prop is missing — coerce.
          _relevant: e.is_relevant === true,
          // Several independent tools reported this. Node size follows
          // DEGREE, which makes the loudest source lead visually; this is
          // the counterweight, marking the best-supported node rather than
          // the most connected one.
          _corroborated: Array.isArray(e.corroborated_by) && e.corroborated_by.length > 1,
          ...e.data,
          // AFTER the data spread on purpose: these are real columns now and
          // must win over any same-named leftover a runner stashed in `data`.
          admiralty: e.admiralty ?? null,
          corroborated_by: e.corroborated_by ?? [],
          notes: e.notes ?? null,
          relevance_score: e.relevance_score ?? 0,
          url: e.url || (e.data as any)?.url || null,
        },
      }
    })
    const edges = data.edges
      .filter((e) => validIds.has(e.from_entity) && validIds.has(e.to_entity))
      .map((e) => ({
        data: {
          id: e.id,
          source: e.from_entity,
          target: e.to_entity,
          relation_type: e.relation_type,
          // The tool that asserted the relation — deliberately NOT under
          // `source`: cytoscape reserves that key for the edge's source NODE,
          // so storing it there would be silently overwritten by the node id.
          tool: (e as any).source || null,
        },
      }))
    cy.batch(() => cy.add([...nodes, ...edges]))

    // 3. run layout — skip animation entirely when there are many
    // nodes. Animated transitions on >150 nodes add seconds of pause.
    const layoutOpts: any = {
      name: layout,
      animate: capped.length < 100,
      padding: 40,
      fit: true,
    }
    if (layout === 'fcose') {
      Object.assign(layoutOpts, {
        quality: capped.length > 300 ? 'draft' : 'default',
        nodeRepulsion: 4500,
        idealEdgeLength: 70,
        edgeElasticity: 0.45,
        nestingFactor: 0.1,
        gravity: 0.25,
        gravityRange: 3.8,
        randomize: true,
        nodeSeparation: 75,
        packComponents: true,
      })
    } else if (layout === 'concentric') {
      Object.assign(layoutOpts, {
        concentric: (n: any) => degree[n.data('id')] || 0,
        levelWidth: () => 2,
        minNodeSpacing: 30,
      })
    } else if (layout === 'breadthfirst') {
      // Tree-like layout — top-down, queried selectors at the root.
      // We pick roots heuristically: nodes with the highest degree
      // are typically the queried selectors (every tool emits edges
      // back to them). Falls back to "the singleton with most
      // children" if degrees are tied.
      const sortedByDegree = Object.entries(degree)
        .sort(([, a], [, b]) => b - a)
      const topDeg = sortedByDegree[0]?.[1] || 0
      const rootIds = sortedByDegree
        .filter(([, d]) => d === topDeg && topDeg > 0)
        .slice(0, 5)
        .map(([id]) => id)
      Object.assign(layoutOpts, {
        directed: false,
        spacingFactor: 1.3,
        nodeDimensionsIncludeLabels: showLabels,
        avoidOverlap: true,
        // Setting `roots` to a CSS selector list pins those nodes at
        // the top of the tree.
        roots: rootIds.length
          ? rootIds.map((id) => `#${CSS.escape(id)}`).join(',')
          : undefined,
      })
    }
    cy.layout(layoutOpts).run()
  }, [data, layout, cap, hiddenTypes, showLabels])

  // ── D2: highlight the shortest chain between the two picked nodes ──
  // Runs after the rebuild above (same dependency on `data`), so a re-search
  // that redraws the graph re-applies the highlight instead of leaving stale
  // classes behind.
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.elements().removeClass('onpath dimmed pathend')
    setPathHops(null)
    if (!pathMode || pathEnds.length < 2) return

    const a = cy.getElementById(pathEnds[0])
    const b = cy.getElementById(pathEnds[1])
    // A pick can point at a node the type filter or the node cap just
    // removed — say so rather than silently showing nothing.
    if (!a.length || !b.length) { setPathHops([]); return }

    // Undirected on purpose: an investigator asks whether two things are
    // connected, not whether one points at the other. Unweighted, so the
    // answer is the fewest hops — the shortest EXPLANATION, which is what
    // gets written in a report.
    const res = cy.elements().aStar({ root: a, goal: b, directed: false })
    cy.elements().addClass('dimmed')
    a.removeClass('dimmed'); b.removeClass('dimmed')
    a.addClass('pathend'); b.addClass('pathend')
    if (!res.found) { setPathHops([]); return }

    res.path.removeClass('dimmed')
    res.path.addClass('onpath')
    const hops: any[] = []
    res.path.forEach((ele: any) => {
      hops.push(ele.isEdge()
        ? { kind: 'edge', relation: ele.data('relation_type'), tool: ele.data('tool') }
        : { kind: 'node', label: ele.data('label'), type: ele.data('entity_type') })
    })
    setPathHops(hops)
  }, [pathEnds, pathMode, data])

  // ── derived UI state ────────────────────────────────────────
  const totalEntities = data?.entities.length ?? 0
  const visibleCount = useMemo(() => {
    if (!data) return 0
    return Math.min(
      cap,
      data.entities.filter((e) => !hiddenTypes.has(e.entity_type)).length
    )
  }, [data, cap, hiddenTypes])

  const isEmpty = !loading && totalEntities === 0

  const fit = () => cyRef.current?.fit(undefined, 50)

  const clampZoom = (z: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z))
  // Zoom around the viewport centre so repeated +/- clicks don't drift
  // the graph toward a corner. renderedPosition is in canvas px.
  const zoomTo = (level: number) => {
    const cy = cyRef.current
    if (!cy) return
    cy.zoom({
      level: clampZoom(level),
      renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 },
    })
  }

  const replay = () => {
    if (!cyRef.current) return
    cyRef.current.layout({ name: layout, animate: true, fit: true, padding: 40 } as any).run()
  }
  const screenshot = () => {
    if (!cyRef.current) return
    const blob = cyRef.current.png({ output: 'blob', bg: '#ffffff', full: true, scale: 2 })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    const slug = (caseLabel || 'case').toString().replace(/[^a-zA-Z0-9_-]/g, '_')
    a.download = `${slug}-graph-${new Date().toISOString().slice(0, 10)}.png`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  // Build context-menu items. We drop "Expand" if no callback was wired
  // (i.e. the caller doesn't know how to handle it) so users don't see
  // a dead option.
  const ctxMenuItems: MenuProps['items'] = ctxMenu
    ? [
        { key: 'show', label: t('graph.ctx_show'), onClick: () => { onNodeClick(ctxMenu.node); setCtxMenu(null) } },
        ...(onNodeExpand
          ? [{ key: 'expand', label: t('graph.ctx_expand'), onClick: () => { onNodeExpand(ctxMenu.node); setCtxMenu(null) } }]
          : []),
        ...(onToggleRelevant ? [{
          key: 'mark_relevant',
          label: ctxMenu.node?.is_relevant
            ? t('graph.ctx_unmark_relevant')
            : t('graph.ctx_mark_relevant'),
          onClick: () => { onToggleRelevant(ctxMenu.node); setCtxMenu(null) },
        }] : []),
        ...(onAddMonitoring ? [{
          key: 'add_monitoring',
          label: t('graph.ctx_add_monitoring'),
          onClick: () => { onAddMonitoring(ctxMenu.node); setCtxMenu(null) },
        }] : []),
        ...(onDeleteEntity ? [{
          key: 'delete_fp',
          label: t('graph.ctx_delete_fp'),
          danger: true,
          onClick: () => { onDeleteEntity(ctxMenu.node); setCtxMenu(null) },
        }] : []),
        { type: 'divider' as const },
        {
          key: 'copy_label',
          label: t('graph.ctx_copy_label'),
          onClick: () => {
            navigator.clipboard.writeText(ctxMenu.node.label || ctxMenu.node.id || '')
              .then(() => message.success(t('graph.ctx_copied')))
              .catch(() => message.error(t('graph.ctx_copy_failed')))
            setCtxMenu(null)
          },
        },
        {
          key: 'copy_id',
          label: t('graph.ctx_copy_id'),
          onClick: () => {
            navigator.clipboard.writeText(String(ctxMenu.node.id || ''))
              .then(() => message.success(t('graph.ctx_copied')))
              .catch(() => message.error(t('graph.ctx_copy_failed')))
            setCtxMenu(null)
          },
        },
      ]
    : []

  return (
    <div style={{ display: 'flex', gap: 12 }}>
      {/* ── Sidebar controls ── */}
      <div style={{ width: 200, flex: '0 0 200px' }}>
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <div style={{ fontSize: 11, color: '#8c8c8c', marginBottom: 4 }}>{t('graph.ctrl_layout')}</div>
            <Select aria-label={t('a11y.graph_layout')}
              value={layout}
              onChange={(v) => setLayout(v as LayoutName)}
              options={LAYOUT_KEYS.map((k) => ({ value: k, label: t(`graph.layout_${k}`) }))}
              size="small"
              style={{ width: '100%' }}
            />
          </div>

          <div>
            <div style={{ fontSize: 11, color: '#8c8c8c', marginBottom: 4 }}>
              {t('graph.ctrl_render_cap', { visible: cap, total: totalEntities })}
            </div>
            <Slider aria-label={t('a11y.graph_node_cap')}
              min={0}
              max={CAPS.length - 1}
              value={CAPS.indexOf(cap)}
              onChange={(idx) => setCap(CAPS[idx])}
              tooltip={{ formatter: (i) => `${CAPS[i!]}` }}
              marks={CAPS.reduce((m, n, i) => ({ ...m, [i]: '' }), {})}
              step={1}
            />
          </div>

          <Checkbox checked={showLabels} onChange={(e) => setShowLabels(e.target.checked)}>
            {t('graph.ctrl_show_labels')}
          </Checkbox>

          {/* ── D2: connection path ── */}
          <div>
            <Checkbox
              checked={pathMode}
              onChange={(e) => {
                setPathMode(e.target.checked)
                if (!e.target.checked) setPathEnds([])
              }}
            >
              {t('graph.path_mode')}
            </Checkbox>
            {pathMode && (
              <div style={{ marginTop: 6, fontSize: 11 }}>
                {pathEnds.length < 2 ? (
                  <span style={{ color: '#8c8c8c' }}>
                    {t('graph.path_pick', { count: 2 - pathEnds.length })}
                  </span>
                ) : pathHops === null ? null : pathHops.length === 0 ? (
                  <span style={{ color: '#d4380d' }}>{t('graph.path_none')}</span>
                ) : (
                  <div>
                    <div style={{ color: '#8c8c8c', marginBottom: 4 }}>
                      {t('graph.path_hops', {
                        count: pathHops.filter((h) => h.kind === 'edge').length,
                      })}
                    </div>
                    {pathHops.map((h, i) => (
                      h.kind === 'node' ? (
                        <div key={i} style={{ wordBreak: 'break-all' }}>
                          <Tag color={NODE_COLORS[h.type] || NODE_COLORS.default}
                               style={{ marginRight: 4 }}>{' '}</Tag>
                          {h.label}
                        </div>
                      ) : (
                        <div key={i} style={{ paddingLeft: 10, color: '#8c8c8c' }}>
                          ↓ {h.relation}
                          {/* Which tool asserted the link — a chain is only
                              as good as the weakest claim in it. */}
                          {h.tool ? ` · ${h.tool}` : ''}
                        </div>
                      )
                    ))}
                  </div>
                )}
                {pathEnds.length > 0 && (
                  <Button size="small" type="link" style={{ padding: 0, marginTop: 4 }}
                          onClick={() => setPathEnds([])}>
                    {t('graph.path_reset')}
                  </Button>
                )}
              </div>
            )}
          </div>

          <div>
            <div style={{ fontSize: 11, color: '#8c8c8c', marginBottom: 4 }}>{t('graph.ctrl_filter_type')}</div>
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              {Object.entries(typeCounts)
                .sort((a, b) => b[1] - a[1])
                .map(([type, count]) => (
                  <Checkbox
                    key={type}
                    checked={!hiddenTypes.has(type)}
                    onChange={(e) => {
                      const next = new Set(hiddenTypes)
                      if (e.target.checked) next.delete(type)
                      else next.add(type)
                      setHiddenTypes(next)
                    }}
                  >
                    <Tag
                      color={NODE_COLORS[type] || NODE_COLORS.default}
                      style={{ marginRight: 4 }}
                    >
                      {' '}
                    </Tag>
                    <span style={{ fontSize: 12 }}>
                      {type} ({count})
                    </span>
                  </Checkbox>
                ))}
            </Space>
          </div>

          <Space>
            <Button size="small" icon={<FullscreenOutlined />} onClick={fit}>
              {t('graph.ctrl_fit')}
            </Button>
            <Button size="small" icon={<PlayCircleOutlined />} onClick={replay}>
              {t('graph.ctrl_replay')}
            </Button>
          </Space>

          <Button
            size="small"
            icon={<CameraOutlined />}
            block
            onClick={screenshot}
            disabled={!data || totalEntities === 0}
          >
            {t('graph.ctrl_screenshot')}
          </Button>
        </Space>
      </div>

      {/* ── Canvas ── */}
      <div
        style={{
          position: 'relative',
          flex: 1,
          height: 600,
          background: '#fafafa',
          border: '1px solid #f0f0f0',
          borderRadius: 8,
        }}
      >
        {loading && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              zIndex: 10,
            }}
          >
            <Spin size="large" />
          </div>
        )}
        {isEmpty && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Empty description={t('graph.no_data')} />
          </div>
        )}
        {/* WCAG 2.1 — the canvas itself.
            Cytoscape draws into a <canvas>, which is invisible to a screen
            reader and unreachable by keyboard. Three things make that
            defensible rather than merely acknowledged:

            1. `role="application"` plus a label and a description, so
               assistive technology announces WHAT this is and how many
               nodes it holds instead of an unnamed graphic (SC 1.1.1,
               SC 4.1.2).
            2. `tabIndex={0}` and arrow/+/- handling, so the view can be
               panned and zoomed without a mouse (SC 2.1.1). Deliberately
               NOT a node-by-node focus walk: 600 nodes make a tab order
               that is worse than no tab order, and the equivalent
               *content* is the findings table, not this picture.
            3. A named, focusable alternative right above it. SC 1.1.1 is
               satisfied by an equivalent, and the equivalent exists — it
               was simply never announced as one. */}
        <div
          ref={containerRef}
          role="application"
          tabIndex={0}
          aria-label={t('graph.canvas_label', { count: totalEntities })}
          aria-describedby="graph-a11y-note"
          onKeyDown={(e) => {
            const cy = cyRef.current
            if (!cy) return
            const STEP = e.shiftKey ? 200 : 60
            switch (e.key) {
              case 'ArrowLeft':  cy.panBy({ x: STEP, y: 0 }); break
              case 'ArrowRight': cy.panBy({ x: -STEP, y: 0 }); break
              case 'ArrowUp':    cy.panBy({ x: 0, y: STEP }); break
              case 'ArrowDown':  cy.panBy({ x: 0, y: -STEP }); break
              case '+': case '=': zoomTo(zoom * ZOOM_STEP); break
              case '-': case '_': zoomTo(zoom / ZOOM_STEP); break
              case '0': fit(); break
              default: return
            }
            // Only now — a key we did not handle must keep bubbling, or
            // Tab would stop working inside the canvas.
            e.preventDefault()
          }}
          style={{ width: '100%', height: '100%' }}
          // Suppress the browser's native context menu on the canvas
          // — otherwise it pops up on top of our Antd Dropdown when
          // the user right-clicks a node.
          onContextMenu={(e) => e.preventDefault()}
        />
        {/* Referenced by aria-describedby above. Visually hidden rather
            than absent: it is the sentence that tells a screen-reader user
            where the usable version of this data is, and it would be noise
            for everyone else. */}
        <span
          id="graph-a11y-note"
          style={{
            position: 'absolute', width: 1, height: 1, padding: 0, margin: -1,
            overflow: 'hidden', clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap',
            border: 0,
          }}
        >
          {t('a11y.graph_alternative_body')} {t('graph.canvas_keys')}
        </span>
        {data && totalEntities > 0 && (
          <div
            style={{
              position: 'absolute',
              top: 8,
              right: 8,
              background: 'rgba(255,255,255,0.95)',
              color: '#595959',
              border: '1px solid #f0f0f0',
              padding: '4px 10px',
              borderRadius: 4,
              fontSize: 11,
              pointerEvents: 'none',
            }}
          >
            <ExpandOutlined /> {visibleCount} / {totalEntities}
          </div>
        )}

        {/* Map-style zoom controls, bottom-right: + button, vertical
            slider (live %), - button, and a fit-to-screen button. The
            mouse wheel keeps working as before — these are an addition. */}
        {!isEmpty && (
          <div
            style={{
              position: 'absolute',
              bottom: 12,
              right: 12,
              zIndex: 11,
              background: 'rgba(255,255,255,0.95)',
              border: '1px solid #f0f0f0',
              borderRadius: 8,
              boxShadow: '0 1px 4px rgba(0,0,0,0.15)',
              padding: 6,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 6,
            }}
          >
            <Tooltip title={t('graph.zoom_in')} placement="left">
              <Button aria-label={t('graph.zoom_in')}
                size="small"
                shape="circle"
                icon={<ZoomInOutlined />}
                onClick={() => zoomTo(zoom * ZOOM_STEP)}
                disabled={zoom >= MAX_ZOOM}
              />
            </Tooltip>
            <Slider aria-label={t('a11y.graph_zoom')}
              vertical
              min={MIN_ZOOM}
              max={MAX_ZOOM}
              step={0.05}
              value={zoom}
              onChange={zoomTo}
              style={{ height: 110, margin: '4px 0' }}
              tooltip={{ formatter: (v) => `${Math.round((v ?? 1) * 100)}%` }}
            />
            <Tooltip title={t('graph.zoom_out')} placement="left">
              <Button aria-label={t('graph.zoom_out')}
                size="small"
                shape="circle"
                icon={<ZoomOutOutlined />}
                onClick={() => zoomTo(zoom / ZOOM_STEP)}
                disabled={zoom <= MIN_ZOOM}
              />
            </Tooltip>
            <Tooltip title={t('graph.ctrl_fit')} placement="left">
              <Button aria-label={t('graph.ctrl_fit')}
                size="small"
                shape="circle"
                icon={<FullscreenOutlined />}
                onClick={fit}
              />
            </Tooltip>
          </div>
        )}
      </div>

      {/* Context menu — anchored to an invisible 1×1 div positioned at
          the click coordinates. Antd Dropdown keeps it on screen even
          near viewport edges. */}
      {ctxMenu && (
        <Dropdown
          open
          menu={{ items: ctxMenuItems }}
          onOpenChange={(o) => { if (!o) setCtxMenu(null) }}
          trigger={['click']}
          getPopupContainer={() => document.body}
        >
          <div
            style={{
              position: 'fixed',
              left: ctxMenu.x,
              top: ctxMenu.y,
              width: 1,
              height: 1,
              pointerEvents: 'none',
            }}
          />
        </Dropdown>
      )}
    </div>
  )
}

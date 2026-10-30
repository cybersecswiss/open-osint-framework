import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ReactFlow, {
  Background, Controls, MiniMap, Handle, Position, MarkerType,
  useNodesState, useEdgesState, ReactFlowProvider, useReactFlow,
} from 'reactflow'
import 'reactflow/dist/style.css'
import dagre from 'dagre'
import {
  Empty, Button, Space, Spin, Dropdown, Alert, Typography, Modal, Input, Tag,
} from 'antd'
import type { MenuProps } from 'antd'
import { ReloadOutlined, CloseOutlined, GroupOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { NODE_COLORS } from './GraphView'
import { EntityIcon } from './entityIcons'
import {
  EMPTY_LAYOUT, groupBoxes, packMembers, placeNew, routeEdges, unplaced,
  NODE_W, NODE_H, type CaseLayout, type LayoutGroup, type Pos,
} from '../../utils/caseLayout'

/**
 * Maltego-style, curated case graph (react-flow). Shows only entities the
 * investigator has added to the map (is_relevant === true) and draws the
 * edges between any two on-map entities.
 *
 * **The arrangement is part of the case.** Where the nodes sit and which
 * boxes were drawn around them is stored with the case (in the CUSTOMER's
 * store, like `notes` — it is the investigator's work, not the operator's
 * business), so it survives a reload, a different case, a different machine
 * and a colleague opening the file. Before that, every visit re-ran an
 * automatic layout and threw the arrangement away, which made the map
 * useless for exactly the thing a map is for: holding a picture in place
 * while you think about it.
 *
 * Two consequences worth stating, because both are easy to get wrong:
 *
 *  - **A new finding never moves what is already placed.** Nodes the layout
 *    has not seen are placed beside the existing picture, not into it.
 *  - **A group's box is derived from its members**, so it cannot end up
 *    somewhere its contents are not. Collapsing one bundles its members'
 *    outside connections into one line per neighbour, drawn thick and
 *    labelled with how many links it stands for — an aggregate must not
 *    read as a single asserted relation.
 *
 * Right-clicking a node also lets the investigator draw a link BY HAND
 * ("verknüpfen von …" → "verknüpfen mit …"). Such a link is an assertion the
 * investigator makes, not something a source stated, and it is drawn dashed
 * and in a different colour for exactly that reason. The distinction is
 * carried in the data too (`source = "manual"`), so it survives into the
 * report and the exports rather than living only on screen.
 */

const { Text } = Typography

/** Colour for links the investigator drew, distinct from any tool's. */
const MANUAL_EDGE_COLOR = '#fa8c16'
const GROUP_COLORS = ['#1677ff', '#52c41a', '#722ed1', '#eb2f96', '#13c2c2', '#d46b08']
const COLLAPSED_W = 240
const COLLAPSED_H = 64

const col = (type: string) => (NODE_COLORS as any)[type] || NODE_COLORS.default

function EntityNode({ data, selected }: any) {
  const c = col(data.type)
  const linking = !!data.linking
  const g = data.groupColor
  // The left border stays the ENTITY TYPE everywhere, including inside a
  // group. It was briefly overwritten with the group colour, which meant the
  // type — the one colour the icons, the minimap and the timeline all share —
  // vanished exactly where several nodes are being compared. Group membership
  // gets its own channel instead: a ring around the node plus a name tag.
  return (
    <div style={{ position: 'relative' }}>
    {g && (
      <div style={{
        position: 'absolute', top: -9, left: 8, zIndex: 2,
        background: g, color: '#fff', fontSize: 9, lineHeight: '13px',
        padding: '0 6px', borderRadius: 7, maxWidth: 150,
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        pointerEvents: 'none',
      }}>{data.groupLabel}</div>
    )}
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8, background: '#fff',
      border: `1px solid ${linking ? MANUAL_EDGE_COLOR : g ? g : selected ? c : '#d9d9d9'}`,
      borderLeft: `4px solid ${c}`,
      borderRadius: 8, padding: '6px 10px', minWidth: 150, maxWidth: 230,
      boxShadow: linking ? `0 0 0 3px ${MANUAL_EDGE_COLOR}55`
        : selected ? `0 0 0 2px ${c}55`
        : g ? `0 0 0 2px ${g}33` : '0 1px 3px rgba(0,0,0,.12)',
    }}>
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <EntityIcon type={data.type} color={c} size={16} />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div title={data.label} style={{
          fontWeight: 600, fontSize: 12, overflow: 'hidden',
          textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>{data.label}</div>
        <div style={{
          fontSize: 10, color: '#999', overflow: 'hidden',
          textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>{data.type}</div>
      </div>
      <CloseOutlined title={data.removeTitle}
        onClick={(e) => { e.stopPropagation(); data.onRemove?.(data.entity) }}
        style={{ fontSize: 11, color: '#bbb', cursor: 'pointer' }} />
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
    </div>
  )
}

/**
 * The box around a group.
 *
 * Only the header strip takes the pointer. The body must stay transparent to
 * clicks or the box would swallow every interaction with the nodes it
 * contains — the group would look like a container and behave like a lid.
 */
function GroupNode({ data }: any) {
  const c = data.color || GROUP_COLORS[0]
  return (
    <div style={{
      width: data.w, height: data.h, borderRadius: 12,
      border: `2px ${data.collapsed ? 'solid' : 'dashed'} ${c}`,
      background: data.collapsed ? '#fff' : `${c}0d`,
      pointerEvents: 'none',
    }}>
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <div
        className="nodrag-none"
        style={{
          pointerEvents: 'all', cursor: 'grab',
          display: 'inline-flex', alignItems: 'center', gap: 6,
          background: c, color: '#fff', fontSize: 11, fontWeight: 600,
          padding: '2px 10px', borderRadius: '10px 0 10px 0', maxWidth: '100%',
        }}
      >
        <GroupOutlined style={{ fontSize: 11 }} />
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {data.label || data.fallbackLabel}
        </span>
        <span style={{ opacity: 0.8 }}>· {data.memberCount}</span>
      </div>
      {data.collapsed && (
        <div style={{ padding: '8px 12px', fontSize: 11, color: '#8c8c8c',
                      pointerEvents: 'none' }}>
          {data.collapsedHint}
        </div>
      )}
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  )
}

const nodeTypes = { entity: EntityNode, casegroup: GroupNode }

function autoArrange(ids: string[], edges: any[]): Record<string, Pos> {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 36, ranksep: 96, marginx: 24, marginy: 24 })
  g.setDefaultEdgeLabel(() => ({}))
  ids.forEach((id) => g.setNode(id, { width: NODE_W, height: NODE_H }))
  edges.forEach((e) => {
    if (g.hasNode(e.source) && g.hasNode(e.target)) g.setEdge(e.source, e.target)
  })
  dagre.layout(g)
  const out: Record<string, Pos> = {}
  ids.forEach((id) => {
    const p = g.node(id)
    if (p) out[id] = { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 }
  })
  return out
}

function Inner({
  data, loading, onNodeClick, onRemoveFromMap, onExpand,
  linkFrom, onLinkStart, onLinkTo, onLinkCancel, onDeleteEdge,
  layout: storedLayout, onLayoutChange,
}: any) {
  const { t } = useTranslation()
  const rf = useReactFlow()
  const [ctx, setCtx] = useState<{ x: number; y: number; entity: any } | null>(null)
  const [edgeCtx, setEdgeCtx] = useState<{ x: number; y: number; edge: any } | null>(null)
  const [groupCtx, setGroupCtx] = useState<{ x: number; y: number; group: LayoutGroup } | null>(null)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [renaming, setRenaming] = useState<LayoutGroup | null>(null)
  const [renameText, setRenameText] = useState('')

  const layout: CaseLayout = storedLayout || EMPTY_LAYOUT

  const onMap = useMemo(
    () => (data?.entities || []).filter((e: any) => e.is_relevant === true),
    [data])
  const idset = useMemo<Set<string>>(
    () => new Set(onMap.map((e: any) => String(e.id))), [onMap])

  const push = useCallback((next: CaseLayout) => onLayoutChange?.(next), [onLayoutChange])

  /**
   * Give every on-map node a position without touching the ones that have
   * one. On a case that was never arranged this is a full automatic pass;
   * afterwards it only ever adds.
   */
  useEffect(() => {
    if (!onMap.length) return
    const ids = onMap.map((e: any) => String(e.id))
    const missing = unplaced(ids, layout)
    if (!missing.length) return
    const known = Object.keys(layout.positions).length
    const added = known === 0
      ? autoArrange(ids, (data?.edges || []).map((ed: any) => ({
          source: String(ed.from_entity), target: String(ed.to_entity) })))
      : placeNew(missing, layout)
    push({ ...layout, positions: { ...layout.positions, ...added } })
  }, [onMap, layout, data, push])

  const groupOf = useMemo(() => {
    const m = new Map<string, LayoutGroup>()
    for (const g of layout.groups) for (const id of g.members) m.set(id, g)
    return m
  }, [layout.groups])

  const hidden = useMemo(() => {
    const s = new Set<string>()
    for (const g of layout.groups) if (g.collapsed) g.members.forEach((m) => s.add(m))
    return s
  }, [layout.groups])

  const boxes = useMemo(
    () => groupBoxes(layout.groups, layout.positions, idset),
    [layout.groups, layout.positions, idset])

  const built = useMemo(() => {
    const groupNodes = boxes.map((b) => ({
      id: b.id,
      type: 'casegroup',
      position: { x: b.x, y: b.y },
      zIndex: 0,
      selectable: false,
      data: {
        w: b.collapsed ? COLLAPSED_W : b.w,
        h: b.collapsed ? COLLAPSED_H : b.h,
        label: b.label, color: b.color, collapsed: b.collapsed,
        memberCount: b.members.filter((m) => idset.has(m)).length,
        fallbackLabel: t('graph_map.group_unnamed'),
        collapsedHint: t('graph_map.group_collapsed_hint'),
      },
      style: { width: b.collapsed ? COLLAPSED_W : b.w, height: b.collapsed ? COLLAPSED_H : b.h },
    }))

    const entityNodes = onMap
      .filter((e: any) => !hidden.has(String(e.id)))
      .map((e: any) => {
        const id = String(e.id)
        return {
          id, type: 'entity',
          position: layout.positions[id] || { x: 0, y: 0 },
          zIndex: 1,
          data: {
            label: e.label || e.id, type: e.entity_type, entity: e,
            onRemove: onRemoveFromMap, removeTitle: t('graph_map.remove'),
            linking: linkFrom && String(linkFrom.id) === id,
            groupColor: groupOf.get(id)?.color,
            groupLabel: groupOf.get(id)?.label || t('graph_map.group_unnamed'),
          },
        }
      })

    const routed = routeEdges(
      (data?.edges || []), layout.groups, idset)
    const re = routed.map((r) => {
      const manual = !r.aggregated && r.edge?.source === 'manual'
      const stroke = r.aggregated ? '#8c8c8c' : manual ? MANUAL_EDGE_COLOR : '#b0b0b0'
      return {
        id: r.id, source: r.source, target: r.target,
        data: { edge: r.edge, manual, aggregated: r.aggregated, count: r.count },
        label: r.aggregated
          ? t('graph_map.edge_bundle', { count: r.count })
          : r.edge?.relation_type,
        labelStyle: { fontSize: 10, fill: manual ? MANUAL_EDGE_COLOR : '#888' },
        labelBgStyle: { fill: '#fff', fillOpacity: 0.8 },
        style: r.aggregated
          ? { stroke, strokeWidth: Math.min(1.5 + r.count * 0.6, 6) }
          : manual
            ? { stroke, strokeWidth: 1.6, strokeDasharray: '6 4' }
            : { stroke },
        markerEnd: { type: MarkerType.ArrowClosed, color: stroke },
      }
    })
    return { rn: [...groupNodes, ...entityNodes], re }
  }, [onMap, idset, data, onRemoveFromMap, t, linkFrom, layout, boxes, hidden, groupOf])

  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])

  useEffect(() => {
    setNodes(built.rn as any)
    setEdges(built.re as any)
  }, [built, setNodes, setEdges])

  // Fit once per case, not on every change — refitting while somebody is
  // arranging nodes yanks the canvas out from under them.
  const fitted = useRef<string>('')
  useEffect(() => {
    const key = onMap.length ? String(onMap[0]?.case_id || onMap.length) : ''
    if (!onMap.length || fitted.current === key) return
    fitted.current = key
    setTimeout(() => rf.fitView({ padding: 0.2, duration: 300 }), 80)
  }, [onMap, rf])

  /** Persist a drag. Group headers drag their whole membership along. */
  const onNodeDragStop = useCallback((_e: any, node: any, dragged: any[]) => {
    const positions = { ...layout.positions }
    const moved = (dragged && dragged.length ? dragged : [node])
    let changed = false
    for (const n of moved) {
      if (n.type === 'casegroup') continue
      positions[n.id] = { x: Math.round(n.position.x), y: Math.round(n.position.y) }
      changed = true
    }
    // A group node was dragged: shift its members by the same delta, since
    // the box has no position of its own to store.
    const g = moved.find((n: any) => n.type === 'casegroup')
    if (g) {
      const b = boxes.find((x) => x.id === g.id)
      if (b) {
        const dx = g.position.x - b.x
        const dy = g.position.y - b.y
        const grp = layout.groups.find((x) => x.id === g.id)
        for (const m of grp?.members || []) {
          const p = positions[m]
          if (p) { positions[m] = { x: Math.round(p.x + dx), y: Math.round(p.y + dy) }; changed = true }
        }
      }
    }
    if (changed) push({ ...layout, positions })
  }, [layout, boxes, push])

  const relayout = useCallback(() => {
    const ids = onMap.map((e: any) => String(e.id))
    const positions = autoArrange(ids, (data?.edges || []).map((ed: any) => ({
      source: String(ed.from_entity), target: String(ed.to_entity) })))
    push({ ...layout, positions })
    setTimeout(() => rf.fitView({ padding: 0.2, duration: 300 }), 80)
  }, [onMap, data, layout, push, rf])

  const createGroup = useCallback(() => {
    const members = selectedIds.filter((id) => idset.has(id))
    if (members.length < 2) return
    // A node belongs to at most one group: two boxes claiming the same node
    // would draw two rectangles over one thing and neither would be true.
    const others = layout.groups
      .map((g) => ({ ...g, members: g.members.filter((m) => !members.includes(m)) }))
      .filter((g) => g.members.length > 0)
    const next: LayoutGroup = {
      id: `g${Date.now().toString(36)}`,
      label: '',
      color: GROUP_COLORS[others.length % GROUP_COLORS.length],
      members,
      collapsed: false,
    }
    // Tidy the members into a block, and slide that block clear of anything
    // that is NOT in the group. A box derived from scattered members grows
    // to cover everything between them, and then every unrelated node inside
    // it reads as a member — the box has to be legible or it is decoration.
    const packed = packMembers(
      members, layout.positions,
      [...idset].filter((id) => !members.includes(id)))
    push({
      ...layout,
      positions: { ...layout.positions, ...packed },
      groups: [...others, next],
    })
    setSelectedIds([])
    setRenaming(next)
    setRenameText('')
  }, [selectedIds, idset, layout, push])

  /** Put a node into an existing group, taking it out of any other one. */
  const addToGroup = useCallback((entityId: string, groupId: string) => {
    const groups = layout.groups
      .map((g) => (g.id === groupId
        ? { ...g, members: [...g.members.filter((m) => m !== entityId), entityId] }
        : { ...g, members: g.members.filter((m) => m !== entityId) }))
      .filter((g) => g.id === groupId || g.members.length > 0)
    const target = groups.find((g) => g.id === groupId)!
    const packed = packMembers(
      target.members, layout.positions,
      [...idset].filter((id) => !target.members.includes(id)))
    push({ ...layout, positions: { ...layout.positions, ...packed }, groups })
  }, [layout, idset, push])

  /** Re-tidy a group whose members have drifted apart again. */
  const tidyGroup = useCallback((groupId: string) => {
    const g = layout.groups.find((x) => x.id === groupId)
    if (!g) return
    const packed = packMembers(
      g.members, layout.positions,
      [...idset].filter((id) => !g.members.includes(id)))
    push({ ...layout, positions: { ...layout.positions, ...packed } })
  }, [layout, idset, push])

  const updateGroup = useCallback((id: string, patch: Partial<LayoutGroup>) => {
    push({
      ...layout,
      groups: layout.groups.map((g) => (g.id === id ? { ...g, ...patch } : g)),
    })
  }, [layout, push])

  const dropGroup = useCallback((id: string) => {
    push({ ...layout, groups: layout.groups.filter((g) => g.id !== id) })
  }, [layout, push])

  const short = (e: any) => {
    const l = String(e?.label || e?.id || '')
    return l.length > 28 ? `${l.slice(0, 27)}…` : l
  }

  const ctxItems: MenuProps['items'] = ctx ? [
    { key: 'show', label: t('graph.ctx_show'),
      onClick: () => { onNodeClick?.(ctx.entity); setCtx(null) } },
    ...(onExpand ? [{ key: 'expand', label: t('graph.ctx_expand'),
      onClick: () => { onExpand(ctx.entity); setCtx(null) } }] : []),
    ...(onLinkStart ? [{ type: 'divider' as const }] : []),
    ...(onLinkStart && !linkFrom ? [{
      key: 'link_from',
      label: t('graph_map.link_from'),
      onClick: () => { onLinkStart(ctx.entity); setCtx(null) },
    }] : []),
    ...(onLinkStart && linkFrom && String(linkFrom.id) !== String(ctx.entity.id) ? [{
      key: 'link_to',
      label: t('graph_map.link_to', { label: short(linkFrom) }),
      onClick: () => { onLinkTo?.(ctx.entity); setCtx(null) },
    }] : []),
    ...(onLinkStart && linkFrom ? [{
      key: 'link_cancel',
      label: t('graph_map.link_cancel'),
      onClick: () => { onLinkCancel?.(); setCtx(null) },
    }] : []),
    ...(layout.groups.length ? [
      { type: 'divider' as const },
      {
        key: 'add_to_group',
        label: t('graph_map.group_add_to'),
        children: layout.groups
          .filter((g) => g.id !== groupOf.get(String(ctx.entity?.id))?.id)
          .map((g) => ({
            key: `atg-${g.id}`,
            label: (
              <Space size={6}>
                <span style={{ display: 'inline-block', width: 10, height: 10,
                               borderRadius: 3, background: g.color }} />
                {g.label || t('graph_map.group_unnamed')}
                <Text type="secondary" style={{ fontSize: 11 }}>
                  · {g.members.filter((m) => idset.has(m)).length}
                </Text>
              </Space>
            ),
            onClick: () => { addToGroup(String(ctx.entity.id), g.id); setCtx(null) },
          })),
      },
    ] : []),
    ...(groupOf.has(String(ctx.entity?.id)) ? [
      { key: 'leave_group',
        label: t('graph_map.group_remove_member'),
        onClick: () => {
          const g = groupOf.get(String(ctx.entity.id))!
          const rest = g.members.filter((m) => m !== String(ctx.entity.id))
          if (rest.length < 2) dropGroup(g.id)
          else updateGroup(g.id, { members: rest })
          setCtx(null)
        } },
    ] : []),
    ...(onRemoveFromMap ? [
      { type: 'divider' as const },
      { key: 'remove', label: t('graph_map.remove'), danger: true,
        onClick: () => { onRemoveFromMap(ctx.entity); setCtx(null) } },
    ] : []),
  ] : []

  // Only a link the investigator drew can be retracted. A tool-asserted edge
  // is the record of what a source said; the menu says so instead of simply
  // not offering anything, because a missing option reads as a bug. The rule
  // is enforced by the server regardless — this is the explanation, not the
  // protection.
  const edgeCtxItems: MenuProps['items'] = edgeCtx ? (
    edgeCtx.edge?.data?.aggregated
      ? [{ key: 'agg', disabled: true,
           label: t('graph_map.edge_bundle_hint', { count: edgeCtx.edge.data.count }) }]
      : edgeCtx.edge?.data?.manual
        ? [{
            key: 'unlink',
            label: t('graph_map.unlink'),
            danger: true,
            onClick: () => { onDeleteEdge?.(edgeCtx.edge.data.edge); setEdgeCtx(null) },
          }]
        : [{
            key: 'not_manual',
            label: t('graph_map.unlink_blocked', {
              source: edgeCtx.edge?.data?.edge?.source || t('graph_map.link_by_unknown'),
            }),
            disabled: true,
          }]
  ) : []

  const groupCtxItems: MenuProps['items'] = groupCtx ? [
    { key: 'rename', label: t('graph_map.group_rename'),
      onClick: () => { setRenaming(groupCtx.group); setRenameText(groupCtx.group.label); setGroupCtx(null) } },
    { key: 'tidy', label: t('graph_map.group_tidy'),
      onClick: () => { tidyGroup(groupCtx.group.id); setGroupCtx(null) } },
    { key: 'collapse',
      label: groupCtx.group.collapsed ? t('graph_map.group_expand') : t('graph_map.group_collapse'),
      onClick: () => { updateGroup(groupCtx.group.id, { collapsed: !groupCtx.group.collapsed }); setGroupCtx(null) } },
    { key: 'color', label: t('graph_map.group_color'),
      children: GROUP_COLORS.map((c) => ({
        key: c,
        label: <Space size={6}><Tag color={c} style={{ width: 22 }}>{' '}</Tag>{c}</Space>,
        onClick: () => { updateGroup(groupCtx.group.id, { color: c }); setGroupCtx(null) },
      })) },
    { type: 'divider' as const },
    { key: 'ungroup', label: t('graph_map.group_dissolve'), danger: true,
      onClick: () => { dropGroup(groupCtx.group.id); setGroupCtx(null) } },
  ] : []

  if (loading && onMap.length === 0) return <Spin style={{ display: 'block', margin: '80px auto' }} />
  if (onMap.length === 0) return <Empty description={t('graph_map.empty')} style={{ padding: '60px 0' }} />

  const selectable = selectedIds.filter((id) => idset.has(id)).length

  return (
    <div style={{ position: 'relative', height: '72vh', border: '1px solid #eee', borderRadius: 8 }}>
      {linkFrom && (
        <Alert
          type="warning"
          showIcon
          style={{ position: 'absolute', top: 8, left: 8, zIndex: 6, maxWidth: '60%' }}
          message={t('graph_map.link_pending', { label: short(linkFrom) })}
          action={<Button size="small" onClick={() => onLinkCancel?.()}>
            {t('graph_map.link_cancel')}
          </Button>}
        />
      )}
      <ReactFlow
        nodes={nodes} edges={edges}
        onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        onNodeClick={(_e, n) => { if (n.type === 'entity') onNodeClick?.(n.data.entity) }}
        onNodeDoubleClick={(_e, n) => { if (n.type === 'entity') onExpand?.(n.data.entity) }}
        onNodeDragStop={onNodeDragStop}
        onSelectionChange={({ nodes: sel }) =>
          setSelectedIds((sel || []).filter((n: any) => n.type === 'entity').map((n: any) => n.id))}
        onNodeContextMenu={(e, n) => {
          e.preventDefault()
          setEdgeCtx(null)
          if (n.type === 'casegroup') {
            const g = layout.groups.find((x) => x.id === n.id)
            setCtx(null)
            if (g) setGroupCtx({ x: e.clientX, y: e.clientY, group: g })
          } else {
            setGroupCtx(null)
            setCtx({ x: e.clientX, y: e.clientY, entity: n.data.entity })
          }
        }}
        onEdgeContextMenu={(e, ed) => {
          e.preventDefault()
          setCtx(null); setGroupCtx(null)
          setEdgeCtx({ x: e.clientX, y: e.clientY, edge: ed })
        }}
        onPaneClick={() => { setCtx(null); setEdgeCtx(null); setGroupCtx(null) }}
        onMoveStart={() => { setCtx(null); setEdgeCtx(null); setGroupCtx(null) }}
        selectionOnDrag
        panOnDrag={[1, 2]}
        minZoom={0.15} maxZoom={2.5}
      >
        <Background gap={18} color="#f0f0f0" />
        <MiniMap pannable zoomable
          nodeColor={(n: any) => (n.type === 'casegroup'
            ? (n.data?.color || '#d9d9d9') : col(n.data?.type))} nodeStrokeWidth={2} />
        <Controls />
      </ReactFlow>

      <Space style={{ position: 'absolute', top: 8, right: 8, zIndex: 5 }}>
        {selectable >= 2 && (
          <Button size="small" type="primary" icon={<GroupOutlined />} onClick={createGroup}>
            {t('graph_map.group_create', { count: selectable })}
          </Button>
        )}
        <Button size="small" icon={<ReloadOutlined />} onClick={relayout}>
          {t('graph_map.relayout')}
        </Button>
      </Space>

      <div style={{ position: 'absolute', bottom: 8, left: 8, zIndex: 5,
                    background: '#ffffffcc', padding: '2px 8px', borderRadius: 4 }}>
        <Space size={12} wrap>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {t('graph_map.select_hint')}
          </Text>
          {edges.some((e: any) => e.data?.manual) && (
            <Space size={6}>
              <span style={{ display: 'inline-block', width: 22, borderTop:
                `2px dashed ${MANUAL_EDGE_COLOR}` }} />
              <Text type="secondary" style={{ fontSize: 11 }}>
                {t('graph_map.legend_manual')}
              </Text>
            </Space>
          )}
          {edges.some((e: any) => e.data?.aggregated) && (
            <Space size={6}>
              <span style={{ display: 'inline-block', width: 22, borderTop: '3px solid #8c8c8c' }} />
              <Text type="secondary" style={{ fontSize: 11 }}>
                {t('graph_map.legend_bundle')}
              </Text>
            </Space>
          )}
        </Space>
      </div>

      {/* Anchored to the pointer: react-flow owns the canvas, so the menu
          rides on a zero-size element at the click position instead. */}
      {ctx && (
        <Dropdown open menu={{ items: ctxItems }}
          onOpenChange={(o) => { if (!o) setCtx(null) }} trigger={['contextMenu']}>
          <div style={{ position: 'fixed', left: ctx.x, top: ctx.y, width: 1, height: 1 }} />
        </Dropdown>
      )}
      {edgeCtx && (
        <Dropdown open menu={{ items: edgeCtxItems }}
          onOpenChange={(o) => { if (!o) setEdgeCtx(null) }} trigger={['contextMenu']}>
          <div style={{ position: 'fixed', left: edgeCtx.x, top: edgeCtx.y, width: 1, height: 1 }} />
        </Dropdown>
      )}
      {groupCtx && (
        <Dropdown open menu={{ items: groupCtxItems }}
          onOpenChange={(o) => { if (!o) setGroupCtx(null) }} trigger={['contextMenu']}>
          <div style={{ position: 'fixed', left: groupCtx.x, top: groupCtx.y, width: 1, height: 1 }} />
        </Dropdown>
      )}

      <Modal
        open={!!renaming}
        title={t('graph_map.group_rename')}
        okText={t('graph_map.group_rename_ok')}
        cancelText={t('cases.cancel')}
        onCancel={() => setRenaming(null)}
        onOk={() => {
          if (renaming) updateGroup(renaming.id, { label: renameText.trim().slice(0, 80) })
          setRenaming(null)
        }}
      >
        <Input
          autoFocus
          value={renameText}
          maxLength={80}
          placeholder={t('graph_map.group_name_placeholder')}
          onChange={(e) => setRenameText(e.target.value)}
          onPressEnter={() => {
            if (renaming) updateGroup(renaming.id, { label: renameText.trim().slice(0, 80) })
            setRenaming(null)
          }}
        />
      </Modal>
    </div>
  )
}

export default function MaltegoGraph(props: any) {
  return <ReactFlowProvider><Inner {...props} /></ReactFlowProvider>
}

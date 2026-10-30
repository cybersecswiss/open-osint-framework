import { Alert, Button, Card, Col, Drawer, Dropdown, Form, Input, List, Modal, Popconfirm, Row, Select, Space, Spin, Table, Tabs, Tag, Tooltip, Typography, message } from 'antd'
import { EditOutlined, DeleteOutlined, FilePdfOutlined, StarFilled, StarOutlined, ThunderboltOutlined, ExportOutlined, FileTextOutlined, ReloadOutlined, LockOutlined } from '@ant-design/icons'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { casesApi, graphApi, entityApi, tenantApi, aiApi, exportApi, evidenceApi } from '../api/client'
import { useStore } from '../store/useStore'
import MaltegoGraph from '../components/graph/MaltegoGraph'
import NodeDetail from '../components/graph/NodeDetail'
import FindingsPanel from '../components/graph/FindingsPanel'
import TimelinePanel from '../components/graph/TimelinePanel'
import ActivityLogPanel from '../components/cases/ActivityLogPanel'
import CaseAccessFields from '../components/cases/CaseAccessFields'
import EvidencePanel, { evidenceErrorText } from '../components/cases/EvidencePanel'
import MergeModal from '../components/cases/MergeModal'
import CrossCaseBanner from '../components/cases/CrossCaseBanner'
import CaseTemplateSelect, { useAllPlaybooks } from '../components/cases/CaseTemplateSelect'
import DeltaPanel from '../components/graph/DeltaPanel'
import MapView, { countLocated } from '../components/map/MapView'
import SearchForm from '../components/search/SearchForm'
import MonitoringQuickCreate from '../components/monitoring/MonitoringQuickCreate'
import PivotDrawer from '../components/search/PivotDrawer'
import ImportSelectorsDrawer from '../components/search/ImportSelectorsDrawer'
import WorklistPanel from '../components/graph/WorklistPanel'
import LinkEntitiesModal from '../components/graph/LinkEntitiesModal'
import CasePhase, { type Phase } from '../components/cases/CasePhase'
import NextStepBar from '../components/cases/NextStepBar'
import { normaliseLayout, EMPTY_LAYOUT, type CaseLayout } from '../utils/caseLayout'
import { displayLabel } from '../utils/label'
import { pivotSeed, type PivotSeed } from '../utils/pivot'
import LoadFailed from '../components/LoadFailed'
import { blobErrorDetail } from '../utils/blobError'

// Same colours as GraphView so the type-tag in the list view matches
// the node colour in the graph view.
const TYPE_COLORS: Record<string, string> = {
  person: 'blue',
  social_account: 'green',
  organization: 'gold',
  email_address: 'red',
  domain: 'purple',
  username: 'cyan',
  ip_address: 'magenta',
  phone_number: 'lime',
  location: 'orange',
}

const STATUS_COLORS: Record<string, string> = {
  open: 'green', in_progress: 'blue', closed: 'default', archived: 'default',
}
const PRIO_COLORS: Record<string, string> = {
  normal: 'default', high: 'orange', urgent: 'red',
}

export default function CaseDetail() {
  const { t } = useTranslation()
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const user = useStore((s) => s.user)
  const isAdmin = user?.roles.includes('admin') ?? false
  const [selectedNode, setSelectedNode] = useState<any>(null)
  const [editing, setEditing] = useState(false)
  const [activeTab, setActiveTab] = useState('findings')
  const [expandPrefill, setExpandPrefill] = useState<{ query: string; type: string } | null>(null)
  // Graph context-menu's "Add to monitoring" opens this
  // modal pre-filled with the right-clicked entity.
  const [monitoringFor, setMonitoringFor] = useState<{ id: string; label: string } | null>(null)
  const [mergeFor, setMergeFor] = useState<any | null>(null)
  const allPlaybooks = useAllPlaybooks()
  // "Erweiterte Suche" (advanced/pivot search) drawer.
  const [pivotOpen, setPivotOpen] = useState(false)
  // "Bekanntes einfügen" — selectors out of a pasted report, parsed in the
  // browser. The text itself is never sent or stored; see the drawer.
  const [importOpen, setImportOpen] = useState(false)
  // Drawing a link by hand is two right-clicks apart, so the first half has
  // to be held somewhere: `linkFrom` is the pending source node, `linkTo` the
  // second node once picked (which opens the confirm dialog).
  const [linkFrom, setLinkFrom] = useState<any>(null)
  const [linkTo, setLinkTo] = useState<any>(null)

  // --- Case map arrangement -------------------------------------------
  // Held here rather than in the graph so it survives switching tabs, and
  // written back through a debounce: a drag emits a position on every drop,
  // and one HTTP write per drop would put a stream of mouse movements into
  // the customer's database.
  const { data: layoutRaw } = useQuery({
    queryKey: ['layout', id],
    queryFn: () => entityApi.getLayout(id!),
    enabled: !!id,
    staleTime: 60_000,
  })
  const [layout, setLayout] = useState<CaseLayout>(EMPTY_LAYOUT)
  const layoutLoaded = useRef<string>('')
  useEffect(() => {
    if (!id || layoutRaw === undefined || layoutLoaded.current === id) return
    layoutLoaded.current = id
    setLayout(normaliseLayout(layoutRaw))
  }, [id, layoutRaw])

  const saveTimer = useRef<any>(null)
  const saveFailed = useRef(false)
  const onLayoutChange = (next: CaseLayout) => {
    setLayout(next)
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => {
      entityApi.putLayout(id!, next).then(() => { saveFailed.current = false })
        .catch((e: any) => {
          // Told once, not on every retry: a map that silently stops saving
          // is worse than one that says so, and a message per drag is noise.
          if (!saveFailed.current) {
            saveFailed.current = true
            message.warning(e?.response?.data?.detail || t('graph_map.layout_save_failed'))
          }
        })
    }, 700)
  }
  useEffect(() => () => { if (saveTimer.current) clearTimeout(saveTimer.current) }, [])
  const [pivotSeedVal, setPivotSeedVal] = useState<PivotSeed | null>(null)
  // Same queryKey as WorklistPanel: the bar and the tab share ONE agent
  // round-trip instead of paying for it twice.
  const { data: worklist } = useQuery({
    queryKey: ['worklist', id],
    queryFn: () => graphApi.getWorklist(id!),
    enabled: !!id,
    staleTime: 60_000,
  })
  const { data: retention } = useQuery({
    queryKey: ['retention', id], queryFn: () => casesApi.retention(id!),
    enabled: !!id, staleTime: 5 * 60_000,
  })
  /**
   * Refresh everything the case view derives from.
   *
   * One function on purpose. The refresh used to be eleven scattered
   * `invalidateQueries({ queryKey: ['graph', id] })` calls — and the bar at
   * the top of the case reads TWO queries, so every one of those left the
   * suggestion stale: deleting thirty findings updated the list underneath
   * while the line above it still named the old number. A suggestion that
   * lags behind what the analyst just did is worse than none, because it
   * looks current.
   *
   * Anything added later that the case view reads belongs in here, not in a
   * new call at the site that changed the data.
   */
  const refreshCase = useCallback(() => {
    if (!id) return
    qc.invalidateQueries({ queryKey: ['graph', id] })
    qc.invalidateQueries({ queryKey: ['worklist', id] })
    qc.invalidateQueries({ queryKey: ['delta', id] })
  }, [qc, id])

  const openPivot = (node?: any) => {
    setPivotSeedVal(node ? pivotSeed(node) : null)
    setPivotOpen(true)
  }
  const [form] = Form.useForm()

  // Six queries feed this page. The two that carry the page get a real
  // error state: without one, a failed graph fetch renders an EMPTY graph,
  // and on the surface an investigator works on that reads as "this case has
  // no findings" — the one thing a failed request must never say.
  //
  // The other four (layout, worklist, retention, licence) stay quiet on
  // purpose: each degrades into a sensible default — no saved positions, no
  // work list, no retention line, no AI button — and none of them can be
  // mistaken for a statement about the evidence.
  const { data: caseData, isError: caseError, refetch: refetchCase } = useQuery({
    queryKey: ['case', id],
    queryFn: () => casesApi.get(id!),
    enabled: !!id,
  })

  const {
    data: graphData, isLoading: graphLoading, isError: graphError,
    isFetching: graphFetching, refetch: refetchGraph,
  } = useQuery({
    queryKey: ['graph', id],
    queryFn: () => graphApi.getGraph(id!),
    enabled: !!id,
  })

  // Warn before the graph gets slow rather than silently capping it: a cap
  // without paging hides findings, and hiding findings is worse than a
  // sluggish canvas. The report caps its picture at 70 nodes and prints how
  // many it left out — same principle, different remedy for a live canvas.
  const GRAPH_BUSY = 800
  // Same selector in another case — one agent query, refreshed with the graph.
  const { data: crossHits } = useQuery({
    queryKey: ['cross-hits', id, (graphData?.entities || []).length],
    queryFn: () => graphApi.crossHits(id!),
    enabled: !!id && !!graphData,
    staleTime: 60 * 1000,
  })
  const nodeCount = (graphData?.entities || []).length
  // Real findings without an Admiralty rating. Findings collected before the
  // scale was introduced stay unrated — a row only becomes citable when its
  // source is scanned again (ARCHITECTURE.md §4).
  const unratedLegacy = (graphData?.entities || []).filter(
    (e: any) => !e.admiralty && !(e.data || {}).virtual).length

  // AI function (KI-Verknüpfung) — the button only renders if the tenant's
  // license has it enabled. Result is shown in a drawer (suggestions only).
  const { data: license } = useQuery({ queryKey: ['license'], queryFn: tenantApi.getLicense })
  const [aiOpen, setAiOpen] = useState(false)
  // Async: start a job, poll for the result (large cases exceed the proxy /
  // Cloudflare request timeout, so a synchronous call 504s/524s).
  const [aiState, setAiState] = useState<{ loading: boolean; error?: string; data?: any }>({ loading: false })
  const runAi = async () => {
    setAiOpen(true); setAiState({ loading: true }); setAiAdded(new Set())
    try {
      const { job_id } = await aiApi.link(id!)
      for (let i = 0; i < 180; i++) {
        await new Promise((r) => setTimeout(r, 2000))
        const s = await aiApi.linkStatus(id!, job_id)
        if (s.status === 'done') { setAiState({ loading: false, data: s }); return }
        if (s.status === 'error') { setAiState({ loading: false, error: s.detail || t('case_detail.ai_failed') }); return }
      }
      setAiState({ loading: false, error: t('case_detail.ai_failed') })
    } catch (e: any) {
      setAiState({ loading: false, error: e?.response?.data?.detail || t('case_detail.ai_failed') })
    }
  }
  const ai = aiState.data?.suggestions as any
  // Accept an AI suggestion → persist the edge(s) + put the endpoints on the
  // map (is_relevant), so the link shows in the graph.
  const [aiAdded, setAiAdded] = useState<Set<string>>(new Set())
  const applyMut = useMutation({
    mutationFn: async (p: { key: string; edges: any[]; nodeIds: string[] }) => {
      await aiApi.apply(id!, p.edges)
      // The edge is stored; putting its endpoints on the map is the second
      // half. If that half fails the graph does not change, so reporting a
      // flat success would leave the investigator staring at an unchanged
      // canvas after being told it worked.
      const marked = await Promise.all(p.nodeIds.map((nid) =>
        entityApi.setRelevant(id!, nid, true).then(() => true).catch(() => false)))
      return { partial: marked.some((x) => !x) }
    },
    onSuccess: (d: any, p) => {
      setAiAdded((s) => new Set(s).add(p.key))
      if (d?.partial) message.warning(t('case_detail.ai_added_partial'))
      else message.success(t('case_detail.ai_added'))
      refreshCase()
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('case_detail.ai_failed')),
  })

  const updateMut = useMutation({
    mutationFn: (data: any) => casesApi.update(id!, data),
    onSuccess: () => {
      message.success(t('case_detail.msg_updated'))
      qc.invalidateQueries({ queryKey: ['case', id] })
      qc.invalidateQueries({ queryKey: ['cases'] })
      setEditing(false)
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('case_detail.msg_update_failed')),
  })

  const deleteMut = useMutation({
    mutationFn: () => casesApi.delete(id!),
    onSuccess: () => {
      message.success(t('cases.msg_deleted'))
      qc.invalidateQueries({ queryKey: ['cases'] })
      navigate('/cases')
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('cases.msg_delete_failed')),
  })

  const relevanceMut = useMutation({
    mutationFn: ({ id: eid, value }: { id: string; value: boolean }) =>
      entityApi.setRelevant(id!, eid, value),
    onSuccess: (_data, vars) => {
      // Toast confirms the click registered — earlier the layout
      // re-shuffle from the refetch made the gold-border change easy
      // to miss, so users thought the action did nothing.
      message.success(vars.value
        ? t('case_detail.marked_relevant')
        : t('case_detail.unmarked_relevant'))
      refreshCase()
    },
    onError: (e: any) =>
      message.error(e?.response?.data?.detail || t('case_detail.relevance_failed')),
  })

  const toggleRelevant = (node: any) => {
    relevanceMut.mutate({ id: node.id, value: !node.is_relevant })
  }

  const renameMut = useMutation({
    mutationFn: ({ eid, label }: { eid: string; label: string }) => entityApi.rename(id!, eid, label),
    onSuccess: () => {
      message.success(t('case_detail.renamed'))
      refreshCase()
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('case_detail.rename_failed')),
  })
  const renameEntity = (node: any, label: string) => renameMut.mutate({ eid: node.id, label })

  // Save the page behind a finding into the case's evidence (customer store).
  const captureMut = useMutation({
    mutationFn: (eid: string) => evidenceApi.capture(id!, { entity_id: eid }),
    onSuccess: () => {
      message.success(t('evidence.saved'))
      qc.invalidateQueries({ queryKey: ['evidence', id] })
      qc.invalidateQueries({ queryKey: ['case-activity', id] })
    },
    onError: (e: any) => message.error(evidenceErrorText(t, e)),
  })

  const notesMut = useMutation({
    mutationFn: ({ eid, notes }: { eid: string; notes: string }) =>
      entityApi.setNotes(id!, eid, notes),
    onSuccess: (_d, { eid, notes }) => {
      message.success(t('case_detail.note_saved'))
      // Reflect it locally straight away: the graph query refetches, but the
      // open panel would otherwise show the pre-save value until it lands.
      setSelectedNode((cur: any) => (cur && cur.id === eid ? { ...cur, notes } : cur))
      refreshCase()
    },
    onError: (e: any) =>
      message.error(e?.response?.data?.detail || t('case_detail.note_save_failed')),
  })
  const saveNotes = (node: any, notes: string) =>
    notesMut.mutate({ eid: node.id, notes })

  // Exports stream as a blob so the browser saves the file rather than
  // rendering a 300 KB STIX bundle as text. The server picks the filename;
  // we only read it back off the response.
  const [exporting, setExporting] = useState(false)
  const runExport = async (format: string) => {
    setExporting(true)
    try {
      const blob = await exportApi.download(id!, format)
      const suffix = format === 'maltego' ? 'maltego.csv'
        : format === 'csv' ? 'csv' : `${format}.json`
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${caseData?.case_number || id}.${suffix}`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e: any) {
      // Blob response: the server's reason has to be read out of it.
      message.error((await blobErrorDetail(e)) || t('case_detail.export_failed'))
    } finally {
      setExporting(false)
    }
  }

  const deleteEntityMut = useMutation({
    mutationFn: (eid: string) => entityApi.delete(id!, eid),
    onSuccess: (_d, eid) => {
      message.success(t('case_detail.entity_deleted'))
      // Snap the deleted node out of the panel + refresh the graph.
      setSelectedNode((cur: any) => (cur && cur.id === eid ? null : cur))
      refreshCase()
    },
    onError: (e: any) =>
      message.error(e?.response?.data?.detail || t('case_detail.entity_delete_failed')),
  })

  // Retracting a link the investigator drew. The server refuses anything a
  // tool asserted, so an error here is shown verbatim rather than replaced
  // with a generic failure — the reason IS the useful part.
  const deleteEdgeMut = useMutation({
    mutationFn: (eid: string) => entityApi.deleteEdge(id!, eid),
    onSuccess: () => {
      message.success(t('graph_map.unlink_done'))
      refreshCase()
    },
    onError: (e: any) =>
      message.error(e?.response?.data?.detail || t('graph_map.unlink_failed')),
  })

  const deleteEdge = (edge: any) => {
    Modal.confirm({
      title: t('graph_map.unlink_confirm_title'),
      content: t('graph_map.unlink_confirm_body', {
        relation: edge.relation_type || '',
      }),
      okText: t('graph_map.unlink'),
      okType: 'danger',
      cancelText: t('cases.cancel'),
      onOk: () => deleteEdgeMut.mutate(String(edge.id)),
    })
  }

  const deleteEntity = (node: any) => {
    Modal.confirm({
      title: t('case_detail.confirm_delete_entity_title'),
      content: t('case_detail.confirm_delete_entity_body', { label: node.label || node.id }),
      okText: t('case_detail.confirm_delete_entity_ok'),
      okType: 'danger',
      cancelText: t('cases.cancel'),
      onOk: () => deleteEntityMut.mutate(node.id),
    })
  }

  useEffect(() => {
    if (editing && caseData) {
      form.setFieldsValue({
        title: caseData.title,
        description: caseData.description,
        status: caseData.status,
        priority: caseData.priority,
        assigned_to: caseData.assigned_to,
        restricted: !!caseData.restricted,
        members: caseData.members || [],
        template: caseData.template ?? null,
      })
    }
  }, [editing, caseData, form])

  // Only the creator or an admin decides who sees a case (server: 403).
  const canManageAccess = !!caseData && (
    !!user?.roles.includes('admin') || user?.username === caseData.created_by)

  const submit = () => form.validateFields().then((v) => {
    // Access fields the caller may not change are not sent at all — sending
    // them unchanged would still be refused as an access change.
    if (!canManageAccess) { delete v.restricted; delete v.members }
    updateMut.mutate(v)
  })

  // Graph double-click ("Expand from this node") opens the
  // search tab and pre-fills the form with this entity. The map below
  // covers entity types produced by the cybercrime-focused modules.
  const TYPE_TO_QUERY: Record<string, string> = {
    username: 'username',
    social_account: 'username',
    email_address: 'email',
    email: 'email',
    domain: 'domain',
    dns_a: 'domain',
    dns_aaaa: 'domain',
    dns_mx: 'domain',
    dns_ns: 'domain',
    dns_txt: 'domain',
    dns_cname: 'domain',
    whois_record: 'domain',
    ip: 'ip',
    ip_reputation: 'ip',
    malicious_url: 'url',
    vt_verdict: 'domain',
    breach: 'email',
    malware_sample: 'hash',
    btc_address: 'btc_address',
    eth_address: 'eth_address',
    onion_service: 'keyword',
    paste: 'keyword',
    telegram_channel: 'tg_channel',
    telegram_user: 'tg_user',
    telegram_linked_channel: 'tg_channel',
    discord_guild: 'discord_invite',
    discord_user: 'username',
  }
  const onExpandNode = (node: any) => {
    setExpandPrefill({
      query: node.label || node.username || node.id,
      type: TYPE_TO_QUERY[node.entity_type] || 'username',
    })
    setActiveTab('search')
  }

  // Findings arrive with their real attributes nested under `data`
  // (url, platform, password, …). The Graph tab flattens them via
  // cytoscape; the list/panel tabs pass raw rows. Normalise on select
  // so NodeDetail shows the prominent url-link and cleartext fields
  // consistently no matter which tab the node was picked from.
  const selectNode = (n: any) => {
    if (!n) { setSelectedNode(n); return }
    const { data, ...rest } = n
    const nested = data && typeof data === 'object' ? data : {}
    const merged: any = { ...nested, ...rest }
    // `url` is a real column, but older rows may predate it and leave it
    // empty. An empty column must not blank out the
    // link a runner had stashed in `data` — top level wins only when it
    // actually carries a value.
    if (!merged.url && nested.url) merged.url = nested.url
    setSelectedNode(merged)
  }

  // Flat entity rows for the Liste tab.
  const entityRows = useMemo(() => graphData?.entities || [], [graphData])
  // id → label, so the AI drawer can show human labels instead of uuids.
  const labelById = useMemo(() => {
    const m = new Map<string, string>()
    for (const e of graphData?.entities || []) m.set(String(e.id), e.label)
    return m
  }, [graphData])
  const labelOf = (eid: string) => labelById.get(String(eid)) || String(eid).slice(0, 8)
  // Ids already in the case — the pivot drawer badges/skips these.
  const existingIds = useMemo(
    () => new Set<string>((graphData?.entities || []).map((e: any) => String(e.id))),
    [graphData],
  )

  return (
    <div>
      {/*
        The findings on screen may not be the findings that exist.

        When the customer's agent cannot be reached, the backend answers from
        the framework's own copy and marks every such response
        `source: "local-fallback"`. It has always done so. Nothing in the
        interface read the field, so an investigator looking at a partial or
        stale graph had no way to know it — on the one screen where "is this
        everything?" is the whole question.

        The fix is cheap: the information was already in the response.
      */}
      {graphData?.source === 'local-fallback' && (
        <Alert
          type="warning" showIcon style={{ marginBottom: 12 }}
          message={t('case_detail.fallback_title')}
          description={t('case_detail.fallback_desc')}
          action={
            <Button size="small" icon={<ReloadOutlined />} loading={graphFetching}
                    onClick={() => refetchGraph()}>
              {t('loadfail.retry')}
            </Button>
          }
        />
      )}
      {/* wrap: with six actions and the status tags the header did not fit
          1440 px and pushed the page sideways. */}
      <Space wrap style={{ width: '100%', justifyContent: 'space-between', marginBottom: 8 }} align="start">
        <div>
          <Typography.Title level={3} style={{ marginBottom: 4 }}>
            {caseData?.case_number} — {caseData?.title}
          </Typography.Title>
          <Space size="small" wrap>
            {caseData?.status   && <Tag color={STATUS_COLORS[caseData.status] || 'default'}>{t(`cases.status_${caseData.status}`)}</Tag>}
            {caseData?.priority && <Tag color={PRIO_COLORS[caseData.priority] || 'default'}>{t(`cases.priority_${caseData.priority}`)}</Tag>}
            {caseData?.assigned_to && <Tag>{t('case_detail.assigned_label')}: {caseData.assigned_to}</Tag>}
            {caseData?.template && (
              <Tooltip title={t('case_template.tag_tooltip', {
                tools: (allPlaybooks.find((p) => p.key === caseData.template)?.next_steps || []).join(', ') })}>
                <Tag color="geekblue" style={{ cursor: 'pointer' }} onClick={() => setActiveTab('search')}>
                  {t(`search.pb_${caseData.template}`, { defaultValue: caseData.template })}
                </Tag>
              </Tooltip>
            )}
            {caseData?.restricted && (
              <Tooltip title={t('case_access.tag_tooltip', { members: [caseData.created_by, caseData.assigned_to, ...(caseData.members || [])].filter(Boolean).filter((v: string, i: number, a: string[]) => a.indexOf(v) === i).join(', ') })}>
                <Tag color="purple" icon={<LockOutlined />}>{t('case_access.tag')}</Tag>
              </Tooltip>
            )}
            {/* Retention was invisible: `delete_after` exists in the model and
                the purge does not read it. The real rule is tenant frist AND
                status closed AND last change older than that — so an open case
                is never deleted and reopening suspends the clock. Both sound,
                neither discoverable. */}
            {retention?.months ? (
              <Tooltip title={retention.note}>
                <Tag color={retention.purge_at ? 'orange' : 'default'}>
                  {retention.purge_at
                    ? t('case_detail.retention_until', { when: retention.purge_at.slice(0, 10) })
                    : t('case_detail.retention_open', { months: retention.months })}
                </Tag>
              </Tooltip>
            ) : null}
          </Space>
        </div>
        <Space wrap>
          {license?.ai_enabled && (
            <Tooltip title={t('case_detail.ai_hint')}>
              <Button
                type="primary" ghost
                icon={<ThunderboltOutlined />}
                onClick={runAi}
                disabled={!caseData}
              >
                {t('case_detail.ai_button')}
              </Button>
            </Tooltip>
          )}
          <Button
            icon={<FileTextOutlined />}
            onClick={() => setImportOpen(true)}
            disabled={!caseData}
          >
            {t('case_detail.import_button')}
          </Button>
          <Dropdown
            menu={{
              items: [
                { key: 'csv', label: t('case_detail.export_csv') },
                { key: 'maltego', label: t('case_detail.export_maltego') },
                { key: 'misp', label: t('case_detail.export_misp') },
                { key: 'stix', label: t('case_detail.export_stix') },
                { type: 'divider' as const },
                { key: '_hint', label: t('case_detail.export_hint'), disabled: true },
              ],
              onClick: ({ key }) => { if (!key.startsWith('_')) runExport(key) },
            }}
            disabled={!caseData}
          >
            <Button icon={<ExportOutlined />} loading={exporting}>
              {t('case_detail.export')}
            </Button>
          </Dropdown>
          <Button
            icon={<FilePdfOutlined />}
            onClick={() => navigate(`/cases/${id}/report`)}
            disabled={!caseData}
          >
            {t('case_detail.report_button')}
          </Button>
          <Button icon={<EditOutlined />} onClick={() => setEditing(true)} disabled={!caseData}>
            {t('case_detail.edit_button')}
          </Button>
          {isAdmin && (
            <Popconfirm
              title={t('cases.confirm_delete_title')}
              description={t('cases.confirm_delete_desc', { number: caseData?.case_number || '' })}
              okText={t('cases.delete')}
              okButtonProps={{ danger: true, loading: deleteMut.isPending }}
              cancelText={t('common.cancel')}
              onConfirm={() => deleteMut.mutate()}
            >
              <Button danger icon={<DeleteOutlined />} disabled={!caseData}>
                {t('case_detail.delete_button')}
              </Button>
            </Popconfirm>
          )}
        </Space>
      </Space>

      <Drawer
        title={<Space><ThunderboltOutlined /> {t('case_detail.ai_title')}</Space>}
        width={560} open={aiOpen} onClose={() => setAiOpen(false)}
      >
        {aiState.loading && (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin /><div style={{ marginTop: 12 }}><Typography.Text type="secondary">{t('case_detail.ai_running')}</Typography.Text></div>
          </div>
        )}
        {aiState.error && (
          <Alert type="error" showIcon message={aiState.error} />
        )}
        {ai && !aiState.loading && (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            {aiState.data?.note && <Alert type="info" showIcon message={aiState.data.note} />}
            {ai.error && <Alert type="warning" showIcon message={ai.error} description={ai.raw ? String(ai.raw).slice(0, 400) : undefined} />}
            {ai.narrative && (
              <div>
                <Typography.Title level={5}>{t('case_detail.ai_narrative')}</Typography.Title>
                <Typography.Paragraph>{ai.narrative}</Typography.Paragraph>
              </div>
            )}
            {Array.isArray(ai.identity_clusters) && ai.identity_clusters.length > 0 && (
              <div>
                <Typography.Title level={5}>{t('case_detail.ai_clusters')}</Typography.Title>
                <List size="small" dataSource={ai.identity_clusters} renderItem={(c: any, i: number) => {
                  const members: string[] = c.entity_ids || []
                  return (
                  <List.Item actions={members.length >= 2 ? [
                    <Button key="add" size="small" type="link" disabled={aiAdded.has(`c${i}`) || applyMut.isPending}
                      onClick={() => applyMut.mutate({ key: `c${i}`, nodeIds: members,
                        edges: members.slice(1).map((x) => ({ from_id: members[0], to_id: x, relation: 'same_identity', confidence: c.confidence })) })}>
                      {aiAdded.has(`c${i}`) ? t('case_detail.ai_added_short') : t('case_detail.ai_apply')}
                    </Button>,
                  ] : []}>
                    <div>
                      <Space wrap>
                        {members.map((eid: string) => <Tag key={eid}>{labelOf(eid)}</Tag>)}
                        {typeof c.confidence === 'number' && <Tag color="blue">{Math.round(c.confidence * 100)}%</Tag>}
                      </Space>
                      {c.rationale && <div><Typography.Text type="secondary" style={{ fontSize: 12 }}>{c.rationale}</Typography.Text></div>}
                    </div>
                  </List.Item>
                  )
                }} />
              </div>
            )}
            {Array.isArray(ai.suggested_edges) && ai.suggested_edges.length > 0 && (
              <div>
                <Typography.Title level={5}>{t('case_detail.ai_edges')}</Typography.Title>
                <List size="small" dataSource={ai.suggested_edges} renderItem={(e: any, i: number) => (
                  <List.Item actions={(e.from_id && e.to_id) ? [
                    <Button key="add" size="small" type="link" disabled={aiAdded.has(`e${i}`) || applyMut.isPending}
                      onClick={() => applyMut.mutate({ key: `e${i}`, nodeIds: [e.from_id, e.to_id],
                        edges: [{ from_id: e.from_id, to_id: e.to_id, relation: e.relation || 'related_to', confidence: e.confidence }] })}>
                      {aiAdded.has(`e${i}`) ? t('case_detail.ai_added_short') : t('case_detail.ai_apply')}
                    </Button>,
                  ] : []}>
                    <div>
                      <Space wrap>
                        <Tag>{labelOf(e.from_id)}</Tag>→<Tag color="purple">{e.relation}</Tag>→<Tag>{labelOf(e.to_id)}</Tag>
                        {typeof e.confidence === 'number' && <Tag color="blue">{Math.round(e.confidence * 100)}%</Tag>}
                      </Space>
                      {e.rationale && <div><Typography.Text type="secondary" style={{ fontSize: 12 }}>{e.rationale}</Typography.Text></div>}
                    </div>
                  </List.Item>
                )} />
              </div>
            )}
            {Array.isArray(ai.next_steps) && ai.next_steps.length > 0 && (
              <div>
                <Typography.Title level={5}>{t('case_detail.ai_next')}</Typography.Title>
                <List size="small" dataSource={ai.next_steps}
                  renderItem={(s: any) => <List.Item>{typeof s === 'string' ? s : JSON.stringify(s)}</List.Item>} />
              </div>
            )}
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t('case_detail.ai_disclaimer')}</Typography.Text>
          </Space>
        )}
      </Drawer>

      <CrossCaseBanner hits={crossHits} entities={graphData?.entities} />

      {id && (
        <NextStepBar
          caseId={id}
          entities={graphData?.entities}
          worklist={worklist}
          onGoTab={setActiveTab}
          onPaste={() => setImportOpen(true)}
          onReport={() => navigate(`/cases/${id}/report`)}
        />
      )}

      {/* Where the work stands. Above the tabs, because the tabs are the
          tools and this is the thread through them — their order follows the
          same path: triagieren → offene Selektoren → Bild → Chronologie →
          Änderungen. */}
      {caseData && (
        <Card size="small" style={{ marginBottom: 12 }}>
          <CasePhase
            phase={caseData.phase}
            disabled={updateMut.isPending}
            onChange={(next: Phase) => updateMut.mutate({ phase: next })}
          />
        </Card>
      )}

      {/* Failures the investigator has to know about, before the tabs.
          A silently empty graph is indistinguishable from a case with no
          findings. */}
      {caseError && (
        <LoadFailed compact what={t('loadfail.what.case')}
                    onRetry={() => refetchCase()} />
      )}
      {graphError && (
        <LoadFailed compact what={t('loadfail.what.graph')}
                    loading={graphFetching} onRetry={() => refetchGraph()} />
      )}
      {!graphError && nodeCount > GRAPH_BUSY && (
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
               message={t('case_detail.graph_busy', { n: nodeCount })}
               description={t('case_detail.graph_busy_hint')} />
      )}
      {unratedLegacy > 0 && (
        // Rated and unrated findings sitting side by side looks like a
        // judgement about the sources. It is not — it is the date the
        // Admiralty scale was introduced. Say so rather than let it read
        // as arbitrary.
        <Alert type="info" showIcon style={{ marginBottom: 12 }}
               message={t('case_detail.unrated_legacy', { n: unratedLegacy })}
               description={t('case_detail.unrated_legacy_hint')} />
      )}

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'findings',
            label: t('case_detail.tab_findings'),
            children: (
              <FindingsPanel
                data={graphData || null}
                loading={graphLoading}
                selected={selectedNode}
                onSelect={selectNode}
                onExpand={onExpandNode}
                onAddMonitoring={(node) =>
                  setMonitoringFor({ id: node.id, label: node.label || node.id })
                }
                onToggleRelevant={toggleRelevant}
                onDeleteEntity={deleteEntity}
                onOpenGraph={() => setActiveTab('graph')}
                onPivot={openPivot}
                caseId={id!}
                onRefresh={() => refreshCase()}
              />
            ),
          },
          {
            // "What did the last run add" — the question on a running case.
            // Same lazy rule as the delta tab below: an agent round-trip that
            // is worthless until someone looks at it.
            key: 'worklist',
            label: t('case_detail.tab_worklist'),
            children: activeTab === 'worklist'
              ? <WorklistPanel caseId={id!} onPivot={openPivot} />
              : null,
          },
          {
            key: 'graph',
            label: t('case_detail.tab_graph'),
            children: (
              <>
                {/* WCAG 2.1 SC 1.1.1 — the equivalent alternative, named.
                    The findings table has always held the same data; what
                    was missing is any statement that it IS the alternative
                    to a canvas nobody can operate with a keyboard. An
                    unannounced equivalent does not satisfy the criterion,
                    and it does not help the person who needs it either. */}
                <Alert
                  type="info"
                  showIcon
                  style={{ marginBottom: 12 }}
                  message={t('a11y.graph_alternative_title')}
                  description={
                    <>
                      {t('a11y.graph_alternative_body')}{' '}
                      <Button
                        type="link"
                        size="small"
                        style={{ padding: 0 }}
                        onClick={() => setActiveTab('findings')}
                      >
                        {t('a11y.graph_alternative_link')}
                      </Button>
                    </>
                  }
                />
              <Row gutter={16}>
                <Col span={selectedNode ? 18 : 24}>
                  <MaltegoGraph
                    data={graphData || null}
                    loading={graphLoading}
                    onNodeClick={selectNode}
                    onRemoveFromMap={toggleRelevant}
                    onExpand={onExpandNode}
                    linkFrom={linkFrom}
                    onLinkStart={(n: any) => { setLinkFrom(n); setLinkTo(null) }}
                    onLinkTo={(n: any) => setLinkTo(n)}
                    onLinkCancel={() => { setLinkFrom(null); setLinkTo(null) }}
                    onDeleteEdge={deleteEdge}
                    layout={layout}
                    onLayoutChange={onLayoutChange}
                  />
                </Col>
                {selectedNode && (
                  <Col span={6}>
                    <NodeDetail
                      node={selectedNode}
                      onMonitor={(n) =>
                        setMonitoringFor({ id: n.id, label: n.label || n.id })
                      }
                      onToggleRelevant={toggleRelevant}
                      onDelete={deleteEntity}
                      onPivot={openPivot}
                      onRename={renameEntity}
                      onSaveNotes={saveNotes}
                      onCaptureEvidence={(n) => captureMut.mutate(n.id)}
                      onMerge={(n) => setMergeFor(n)}
                      crossHits={(crossHits?.matches?.[selectedNode.id] || []).map((h) => ({
                        case_id: h.case_id, ...(crossHits?.cases?.[h.case_id] || {}) }))}
                      capturing={captureMut.isPending}
                    />
                  </Col>
                )}
              </Row>
              </>
            ),
          },
          {
            key: 'map',
            label: t('case_detail.tab_map', { count: countLocated(entityRows) }),
            children: activeTab === 'map'
              ? <MapView entities={entityRows} />
              : null,
          },
          {
            key: 'timeline',
            label: t('case_detail.tab_timeline'),
            children: activeTab === 'timeline'
              ? <TimelinePanel data={graphData || null} onSelect={selectNode} />
              : null,
          },
          {
            // Fetched lazily: it costs an agent round-trip and is worthless
            // until someone actually looks at it.
            key: 'delta',
            label: t('case_detail.tab_delta'),
            children: activeTab === 'delta'
              ? (
                <DeltaPanel
                  caseId={id!}
                  onSelect={(node) => { selectNode(node); setActiveTab('graph') }}
                />
              )
              : null,
          },
          {
            key: 'list',
            label: t('case_detail.tab_list', { count: entityRows.length }),
            children: (
              <Table
                size="small"
                rowKey="id"
                loading={graphLoading}
                dataSource={entityRows}
                pagination={{ pageSize: 50, showSizeChanger: true, pageSizeOptions: ['25', '50', '100', '250'] }}
                onRow={(row) => ({ onClick: () => selectNode(row), style: { cursor: 'pointer' } })}
                columns={[
                  {
                    title: <Tooltip title={t('case_detail.list_col_relevant')}><StarOutlined /></Tooltip>,
                    dataIndex: 'is_relevant',
                    key: 'is_relevant',
                    width: 48,
                    align: 'center' as const,
                    sorter: (a: any, b: any) => Number(!!a.is_relevant) - Number(!!b.is_relevant),
                    onCell: () => ({ onClick: (e: any) => e.stopPropagation() }),
                    render: (v: boolean | null, row: any) => (
                      <Button
                        type="text"
                        size="small"
                        aria-label={t('case_detail.list_col_relevant')}
                        onClick={() => toggleRelevant(row)}
                        icon={
                          v ? <StarFilled style={{ color: '#faad14' }} /> : <StarOutlined />
                        }
                      />
                    ),
                  },
                  {
                    title: t('case_detail.list_col_type'),
                    dataIndex: 'entity_type',
                    width: 160,
                    filters: [...new Set(entityRows.map((e: any) => e.entity_type))]
                      .map((tt: any) => ({ text: tt, value: tt })),
                    onFilter: (v, row: any) => row.entity_type === v,
                    render: (tt: string) => <Tag color={TYPE_COLORS[tt] || 'default'}>{tt}</Tag>,
                  },
                  {
                    title: t('case_detail.list_col_label'),
                    dataIndex: 'label',
                    sorter: (a: any, b: any) => (a.label || '').localeCompare(b.label || ''),
                    render: (v: string, row: any) =>
                      displayLabel(row.entity_type, v) || <span style={{ color: '#999' }}>—</span>,
                  },
                  {
                    title: t('case_detail.list_col_actions'),
                    key: 'actions',
                    width: 130,
                    align: 'right' as const,
                    onCell: () => ({ onClick: (e: any) => e.stopPropagation() }),
                    render: (_: unknown, row: any) => (
                      <Button size="small" onClick={() => onExpandNode(row)}>
                        {t('graph.ctx_expand')}
                      </Button>
                    ),
                  },
                ]}
              />
            ),
          },
          {
            key: 'evidence',
            label: t('case_detail.tab_evidence'),
            children: activeTab === 'evidence' ? <EvidencePanel caseId={id!} /> : null,
          },
          {
            key: 'activity',
            label: t('case_detail.tab_activity'),
            children: activeTab === 'activity' ? <ActivityLogPanel caseId={id!} /> : null,
          },
          {
            key: 'search',
            label: t('case_detail.tab_search'),
            children: (
              <SearchForm
                caseId={id!}
                onComplete={() => refreshCase()}
                prefill={expandPrefill}
                onPrefillConsumed={() => setExpandPrefill(null)}
              />
            ),
          },
        ]}
      />

      <Modal
        title={t('case_detail.modal_title', { number: caseData?.case_number || '' })}
        open={editing}
        onOk={submit}
        confirmLoading={updateMut.isPending}
        onCancel={() => setEditing(false)}
        width={600}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="title" label={t('case_detail.field_title')} rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label={t('case_detail.field_description')}>
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="status" label={t('case_detail.field_status')}>
            <Select
              options={[
                { value: 'open',        label: t('cases.status_open') },
                { value: 'in_progress', label: t('cases.status_in_progress') },
                { value: 'closed',      label: t('cases.status_closed') },
                { value: 'archived',    label: t('cases.status_archived') },
              ]}
            />
          </Form.Item>
          <Form.Item name="priority" label={t('case_detail.field_priority')}>
            <Select
              options={[
                { value: 'normal', label: t('cases.priority_normal') },
                { value: 'high',   label: t('cases.priority_high') },
                { value: 'urgent', label: t('cases.priority_urgent') },
              ]}
            />
          </Form.Item>
          <Form.Item name="template" label={t('case_template.label')}>
            <CaseTemplateSelect />
          </Form.Item>
          <CaseAccessFields canManage={canManageAccess} withAssignee />
        </Form>
      </Modal>

      {mergeFor && id && (
        <MergeModal
          caseId={id}
          target={mergeFor}
          entities={graphData?.entities || []}
          onClose={() => setMergeFor(null)}
          onMerged={() => { setSelectedNode(null); refreshCase() }}
        />
      )}

      {monitoringFor && id && (
        <MonitoringQuickCreate
          open
          onCancel={() => setMonitoringFor(null)}
          caseId={id}
          entityId={monitoringFor.id}
          entityLabel={monitoringFor.label}
        />
      )}

      {id && linkFrom && linkTo && (
        <LinkEntitiesModal
          open
          caseId={id}
          from={linkFrom}
          to={linkTo}
          existingEdges={graphData?.edges || []}
          onClose={() => setLinkTo(null)}
          onDone={() => {
            setLinkFrom(null)
            setLinkTo(null)
            refreshCase()
          }}
        />
      )}

      {id && (
        <ImportSelectorsDrawer
          open={importOpen}
          caseId={id}
          onClose={() => setImportOpen(false)}
          onCommitted={() => refreshCase()}
        />
      )}

      {id && (
        <PivotDrawer
          open={pivotOpen}
          caseId={id}
          seed={pivotSeedVal}
          existingIds={existingIds}
          onClose={() => setPivotOpen(false)}
          onCommitted={() => refreshCase()}
        />
      )}
    </div>
  )
}

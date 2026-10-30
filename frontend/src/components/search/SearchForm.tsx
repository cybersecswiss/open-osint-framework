import { Form, Input, Select, Checkbox, Button, Progress, Alert, Space, Modal, Row, Col, Tooltip, Tag, Table, Collapse, Typography, message } from 'antd'
import { PlusOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { useState, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { searchApi, casesApi, tenantApi } from '../../api/client'
import { lastPurpose, rememberPurpose } from '../../utils/purpose'
import { useStore } from '../../store/useStore'
import {
  queryTypeGroupedOptions, availableQueryTypes, firstAvailableType,
} from '../../utils/queryTypes'
import { searchProgressPercent } from '../../utils/progress'
import { facetOptions, isFacetable, MAX_FACETS } from '../../utils/facets'
import { detectType } from '../../utils/detectType'

const { Text } = Typography

interface Props {
  caseId?: string
  onComplete?: () => void
  /** Pre-fill from a graph "expand" action — query + query_type. */
  prefill?: { query?: string; type?: string; facets?: string[]; modules?: string[] } | null
  /** Called once the form has applied the prefill so the parent can clear it. */
  onPrefillConsumed?: () => void
  /** When true (standalone /search page), navigate to /search/{job_id}
   *  after submit so the user lands on the dedicated progress page.
   *  When false (CaseDetail tab), keep inline progress so the graph
   *  refreshes in the same view. */
  redirectAfterSubmit?: boolean
}

interface ToolDescriptor {
  tool: string
  label_key: string
  query_types: string[]
  default_query_type: string
  requires_key: boolean
  /** Admiralty source reliability A–F; "F" = declared nothing. */
  reliability?: string
  /** Declared cost of one run: fast | medium | slow (absent = medium). */
  latency_class?: string
}
interface ModuleManifest {
  name: string
  label_key: string
  category: string
  description_key?: string
  tools: ToolDescriptor[]
}
interface ModulesResponse {
  modules: string[]
  manifests: Record<string, ModuleManifest>
}

export default function SearchForm({ caseId, onComplete, prefill, onPrefillConsumed, redirectAfterSubmit }: Props) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const me = useStore((s) => s.user)
  const [form] = Form.useForm()
  const [newCaseForm] = Form.useForm()
  const [jobId, setJobId] = useState<string | null>(null)
  const [status, setStatus] = useState<string>('')
  const [polling, setPolling] = useState(false)
  const [toolProgress, setToolProgress] = useState<any[]>([])
  const [newCaseOpen, setNewCaseOpen] = useState(false)

  // Module manifests come from the backend (cached at API startup,
  // refreshable via POST /api/v1/search/modules/refresh). The query
  // type → modules mapping is computed entirely from this response.
  const { data: modulesData } = useQuery<ModulesResponse>({
    queryKey: ['search-modules'],
    queryFn: searchApi.modules,
    staleTime: 60_000,
  })
  const manifests = modulesData?.manifests || {}
  const moduleList = Object.values(manifests)
  const queryType: string = (Form.useWatch('query_type', form) as string) || 'username'
  // Facets fan the search out into one run per facet — show the analyst how
  // many runs a click will cost before they trigger it.
  const selectedFacets: string[] = (Form.useWatch('facets', form) as string[]) || []
  const facetCount = isFacetable(queryType) ? selectedFacets.length : 0
  const facetOpts = facetOptions(t)
  // Playbooks for the currently selected selector type. Refetched on type
  // change so `applies` is always about what is actually typed.
  const { data: playbookData } = useQuery({
    queryKey: ['playbooks', queryType],
    queryFn: () => searchApi.playbooks(queryType),
    enabled: !!queryType,
  })
  const playbooks = playbookData?.playbooks || []
  const [activePlaybook, setActivePlaybook] = useState<string | null>(null)

  // Tool-level selection (C1). Stored as EXCLUSIONS, not inclusions: a tool
  // added to a module later is then automatically part of the next search,
  // instead of silently missing because it was not in a list saved earlier.
  // Empty set = the previous behaviour, everything runs.
  const [excluded, setExcluded] = useState<Set<string>>(new Set())

  const selectedModules: string[] =
    (Form.useWatch('modules', form) as string[]) || []

  // Types actually supported by the tenant's available modules → grouped,
  // dead-type-free dropdown. Presentation only; module handling unchanged.
  const availableTypes = availableQueryTypes(moduleList)
  const typeOptions = queryTypeGroupedOptions(availableTypes, t)
  const visibleModules = moduleList.filter((m) =>
    m.tools.some((t) => t.query_types.includes(queryType))
  )
  const allowedModules = visibleModules.map((m) => m.name)
  // Type detection (G8). The form used to demand a classification before it
  // would do anything — somebody holding "+41 79 …" had to know that is
  // `phone`. This PROPOSES; it never decides. A wrong silent auto-switch
  // would be worse than asking, so the proposal is shown, explained, and
  // applied only on click.
  const typedQuery: string = (Form.useWatch('query', form) as string) || ''
  const guess = detectType(typedQuery)
  const guessUseful = !!guess && guess.type !== queryType && availableTypes.has(guess.type)

  // Tools the current (type, modules) combination would run, grouped by
  // module for display. Recomputed from the manifests, never stored.
  const toolGroups = visibleModules
    .filter((m) => (selectedModules.length ? selectedModules : allowedModules).includes(m.name))
    .map((m) => ({
      module: m,
      tools: m.tools.filter((tl: any) => tl.query_types.includes(queryType)),
    }))
    .filter((g) => g.tools.length > 0)
  const allTools = toolGroups.flatMap((g) => g.tools)
  const allToolNames = allTools.map((tl: any) => tl.tool)
  const chosenTools = allToolNames.filter((n) => !excluded.has(n))

  const { data: cases = [] } = useQuery({ queryKey: ['cases'], queryFn: casesApi.list })
  // Same cache key as the header, so this costs no extra request.
  const { data: tenantSettings } = useQuery({
    queryKey: ['tenant-settings'], queryFn: tenantApi.getSettings, staleTime: 5 * 60 * 1000,
  })
  const purposeRequired = !!tenantSettings?.require_search_purpose
  const formCaseId: string | undefined = Form.useWatch('case_id', form)
  const watchedCaseId = caseId || formCaseId
  // Investigators usually run many selectors under one order. The last
  // purpose used in a case is offered again for that case — in this browser
  // only, never sent anywhere but with the search itself.
  useEffect(() => {
    if (!watchedCaseId || form.getFieldValue('purpose')) return
    const last = lastPurpose(watchedCaseId)
    if (last) form.setFieldValue('purpose', last)
  }, [watchedCaseId, form])

  // "New case" inline: create the case, refresh the dropdown, auto-select it.
  const createCaseMutation = async (values: any) => {
    const created = await casesApi.create(values)
    qc.invalidateQueries({ queryKey: ['cases'] })
    form.setFieldValue('case_id', created.id)
    setNewCaseOpen(false)
    newCaseForm.resetFields()
    message.success(t('search.case_created', { number: created.case_number }))
  }

  // When the type changes, reset selection to all allowed modules so the
  // user never submits a stale combo that the backend can't usefully run.
  useEffect(() => {
    form.setFieldValue('modules', allowedModules)
    setActivePlaybook(null)
    // A different selector type means a different tool set, so an exclusion
    // list from the previous type would silently drop unrelated tools.
    setExcluded(new Set())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryType])

  // The authority's default playbook (Admin -> Settings), preselected once per
  // selector type — only where it fits the type, and never over a choice the
  // investigator already made for this type.
  // A case opened from a template brings its own playbook, which wins over
  // the authority-wide default.
  const { data: caseForTemplate } = useQuery({
    queryKey: ['case', caseId],
    queryFn: () => casesApi.get(caseId!),
    enabled: !!caseId,
  })
  const defaultPlaybook = caseForTemplate?.template || tenantSettings?.default_playbook || null
  const [autoAppliedFor, setAutoAppliedFor] = useState<string | null>(null)
  useEffect(() => {
    if (!defaultPlaybook || activePlaybook || autoAppliedFor === queryType) return
    const pb = playbooks.find((p) => p.key === defaultPlaybook)
    if (!pb || !pb.applies) return
    setActivePlaybook(pb.key)
    setAutoAppliedFor(queryType)
    form.setFieldValue('modules', pb.modules.filter((m) => allowedModules.includes(m)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaultPlaybook, playbooks, queryType, activePlaybook])

  // If the selected type isn't offered by any available module (e.g. a
  // module pack that lacks it), fall back to the first available type so
  // the form never sits on a dead selection.
  useEffect(() => {
    if (availableTypes.size && !availableTypes.has(queryType)) {
      const fb = firstAvailableType(availableTypes)
      if (fb) form.setFieldValue('query_type', fb)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modulesData])

  // Apply prefill from the graph "expand" action or the Lagebild page
  // exactly once. After we've populated the form we tell the parent to
  // clear it so a subsequent tab-switch doesn't reset what the user typed.
  // The form is filled but NOT submitted — the analyst decides what runs.
  useEffect(() => {
    if (prefill) {
      form.setFieldsValue({
        ...(prefill.query !== undefined ? { query: prefill.query } : {}),
        ...(prefill.type ? { query_type: prefill.type } : {}),
        ...(prefill.facets ? { facets: prefill.facets } : {}),
        // The News/RSS menu entry lands here with only the module preset —
        // the analyst still types the term.
        ...(prefill.modules ? { modules: prefill.modules } : {}),
      })
      onPrefillConsumed?.()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill])

  // Resume a still-running search after a browser refresh or tab switch.
  // The background job runs server-side regardless of the browser; here
  // we re-attach the inline progress to it so the state isn't "lost".
  // Only for the embedded (in-case) form — the standalone /search page
  // recovers from its bookmarkable /search/:job_id URL instead.
  useEffect(() => {
    if (redirectAfterSubmit || !caseId) return
    let cancelled = false
    ;(async () => {
      try {
        const job = await searchApi.latestForCase(caseId)
        if (cancelled || !job) return
        if (job.status === 'running' || job.status === 'queued') {
          setJobId(job.job_id)
          setStatus(job.status)
          setToolProgress(job.tool_progress || [])
          setPolling(true)
        }
      } catch {
        /* no active job to resume */
      }
    })()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId, redirectAfterSubmit])

  useEffect(() => {
    if (!jobId || !polling) return
    let lastEntityCount = -1
    const interval = setInterval(async () => {
      try {
        const res = await searchApi.status(jobId)
        setStatus(res.status)
        setToolProgress(res.tool_progress || [])
        // Results are persisted incrementally (per module) — refresh the
        // graph whenever the entity count grew so hits appear progressively
        // instead of all at once when the whole search finishes.
        const c = res.case_entity_count ?? 0
        if (c !== lastEntityCount) {
          lastEntityCount = c
          if (c > 0 && onComplete) onComplete()
        }
        if (
          res.status === 'completed' ||
          res.status === 'failed' ||
          res.status === 'partial'
        ) {
          setPolling(false)
          clearInterval(interval)
          if (onComplete) onComplete()
        }
      } catch {
        /* keep polling */
      }
    }, 3000)
    return () => clearInterval(interval)
  }, [jobId, polling, onComplete])

  const onFinish = async (values: any) => {
    setStatus('running')
    const targetCaseId = caseId || values.case_id

    // Priority and notes attach to the case, not to the search job
    // (the backend search endpoint has no priority/notes fields by design —
    // they describe the *case* the search belongs to). If the user filled
    // either, push them onto the case before we kick off the search.
    //
    // Notes get *appended* with a "[YYYY-MM-DD username]:" prefix —
    // earlier versions overwrote `description` and silently destroyed
    // the prior text. The append form keeps the case description as
    // a chronological log.
    if (targetCaseId && (values.priority || values.notes)) {
      const update: any = {}
      if (values.priority) update.priority = values.priority
      if (values.notes) {
        try {
          const current = await casesApi.get(targetCaseId)
          const stamp = new Date().toISOString().slice(0, 10)
          const author = me?.username || me?.email || '?'
          const entry = `[${stamp} ${author}] ${values.notes.trim()}`
          update.description = current.description
            ? `${current.description}\n\n${entry}`
            : entry
        } catch {
          // If we can't read the current desc, write the bare entry
          // rather than risk losing content by overwriting blindly.
          const stamp = new Date().toISOString().slice(0, 10)
          const author = me?.username || me?.email || '?'
          update.description = `[${stamp} ${author}] ${values.notes.trim()}`
        }
      }
      try {
        await casesApi.update(targetCaseId, update)
        qc.invalidateQueries({ queryKey: ['case', targetCaseId] })
        qc.invalidateQueries({ queryKey: ['cases'] })
      } catch {
        // Letting the search proceed is right; letting the note vanish in
        // silence is not. The investigator typed it and will assume it is in
        // the file. Tell them, then carry on.
        message.warning(t('search.note_not_saved'))
      }
    }

    const purpose = (values.purpose || '').trim()
    let res
    try {
      res = await searchApi.start({
      purpose: purpose || undefined,
      query: values.query,
      query_type: values.query_type || 'username',
      case_id: targetCaseId,
      modules: values.modules?.length ? values.modules : allowedModules,
      // Backend ignores facets for non-keyword types, but don't send noise.
      facets: isFacetable(values.query_type)
        ? (values.facets || []).slice(0, MAX_FACETS)
        : [],
      // Empty list = every tool, which is both the backend default and what
      // an analyst who never opened the tool panel expects. Only send an
      // explicit list when something was actually deselected.
      tools: chosenTools.length === allToolNames.length ? [] : chosenTools,
      })
    } catch (e: any) {
      // Used to leave the form on "running" with no word about why.
      setStatus('')
      const detail = e?.response?.data?.detail
      if (detail === 'purpose_required') message.error(t('search.purpose_required'))
      else if (detail === 'activity_log_unavailable') message.error(t('search.activity_log_unavailable'))
      else message.error(typeof detail === 'string' ? detail : t('search.start_failed'))
      return
    }
    if (purpose) rememberPurpose(targetCaseId, purpose)
    if (redirectAfterSubmit) {
      navigate(`/search/${res.job_id}`)
      return
    }
    setJobId(res.job_id)
    setPolling(true)
  }

  return (
    <Form
      form={form}
      layout="vertical"
      onFinish={onFinish}
      initialValues={{ query_type: 'username' }}
    >
      <Form.Item name="query" label={t('search.query_label')} rules={[{ required: true }]}
                 extra={guessUseful ? (
                   <Space size={6}>
                     <Text type="secondary" style={{ fontSize: 12 }}>
                       {t('search.detected', {
                         why: guess!.why,
                         type: t(`search.type_${guess!.type}`, { defaultValue: guess!.type }),
                       })}
                     </Text>
                     <Button size="small" type="link" style={{ padding: 0 }}
                             onClick={() => form.setFieldValue('query_type', guess!.type)}>
                       {t('search.detected_apply')}
                     </Button>
                   </Space>
                 ) : undefined}>
        <Input size="large" placeholder={t('search.query_placeholder')} />
      </Form.Item>

      <Form.Item name="query_type" label={t('search.type_label')}>
        <Select
          showSearch
          optionFilterProp="label"
          options={typeOptions}
        />
      </Form.Item>

      {/* Narrowing facets — free-text selectors only (keyword, company and
          person names). Appending "Zürich" to an e-mail address would just
          break the selector, so the field is hidden for every other type and
          the backend drops them there too. */}
      {isFacetable(queryType) && (
        <Form.Item
          name="facets"
          label={
            <Space size={4}>
              {t('search.facets_label')}
              <Tooltip title={t('search.facets_hint')}>
                <InfoCircleOutlined style={{ color: '#8c8c8c' }} />
              </Tooltip>
            </Space>
          }
          extra={
            facetCount > 0
              ? t('search.facets_runs', { count: facetCount + 1 })
              : t('search.facets_placeholder')
          }
        >
          <Select
            mode="tags"
            allowClear
            maxTagCount="responsive"
            maxCount={MAX_FACETS}
            placeholder={t('search.facets_placeholder')}
            options={facetOpts}
            optionFilterProp="label"
          />
        </Form.Item>
      )}

      {/* Optional context fields. Currently the
          backend search endpoint takes a single `query` only; these
          fields are collected for future multi-identifier search modules
          Tooltip flags this so users don't expect them to
          immediately fan out into separate searches. */}
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item
            name="extra_email"
            label={
              <Space size={4}>
                {t('search.email_label')}
                <Tooltip title={t('search.context_field_tooltip')}>
                  <InfoCircleOutlined style={{ color: '#999' }} />
                </Tooltip>
              </Space>
            }
            rules={[{ type: 'email', message: t('search.email_invalid') }]}
          >
            <Input placeholder="max@example.com" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item
            name="extra_phone"
            label={
              <Space size={4}>
                {t('search.phone_label')}
                <Tooltip title={t('search.context_field_tooltip')}>
                  <InfoCircleOutlined style={{ color: '#999' }} />
                </Tooltip>
              </Space>
            }
          >
            <Input placeholder="+41 …" />
          </Form.Item>
        </Col>
      </Row>

      {!caseId && (
        <Form.Item name="case_id" label={t('search.case_label')} rules={[{ required: true }]}>
          <Space.Compact style={{ width: '100%' }}>
            <Select
              style={{ flex: 1 }}
              placeholder={t('search.case_placeholder')}
              options={cases.map((c: any) => ({
                value: c.id,
                label: `${c.case_number} — ${c.title}`,
              }))}
              value={Form.useWatch('case_id', form)}
              onChange={(v) => form.setFieldValue('case_id', v)}
            />
            <Button icon={<PlusOutlined />} onClick={() => setNewCaseOpen(true)}>
              {t('search.new_case_button')}
            </Button>
          </Space.Compact>
        </Form.Item>
      )}

      <Form.Item
        name="purpose"
        label={t('search.purpose_label')}
        extra={t('search.purpose_hint')}
        rules={purposeRequired ? [{ required: true, whitespace: true, message: t('search.purpose_required') }] : []}
      >
        <Input maxLength={500} placeholder={t('search.purpose_placeholder')} />
      </Form.Item>

      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="priority" label={t('search.priority_label')}>
            <Select
              allowClear
              placeholder={t('search.priority_placeholder')}
              options={[
                { value: 'normal', label: t('cases.priority_normal') },
                { value: 'high',   label: t('cases.priority_high') },
                { value: 'urgent', label: t('cases.priority_urgent') },
              ]}
            />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="notes" label={t('search.notes_label')}>
            <Input.TextArea
              rows={1}
              placeholder={t('search.notes_placeholder')}
              autoSize={{ minRows: 1, maxRows: 4 }}
            />
          </Form.Item>
        </Col>
      </Row>

      {/* Playbooks: pick the offence type, get the module set that fits it.
          Choosing modules directly presumes the investigator already knows
          which sources contribute to which kind of case. */}
      {playbooks.length > 0 && (
        <Form.Item label={t('search.pb_title')} extra={t('search.pb_hint')}>
          <Space size={[6, 6]} wrap>
            {playbooks.map((pb) => {
              const disabled = !pb.applies
              const chip = (
                <Tag.CheckableTag
                  key={pb.key}
                  checked={activePlaybook === pb.key}
                  onChange={() => {
                    if (disabled) return
                    const next = activePlaybook === pb.key ? null : pb.key
                    setActivePlaybook(next)
                    form.setFieldValue(
                      'modules',
                      next ? pb.modules.filter((m) => allowedModules.includes(m))
                           : allowedModules,
                    )
                  }}
                  style={disabled
                    ? { opacity: 0.4, cursor: 'not-allowed' }
                    : { cursor: 'pointer' }}
                >
                  {t(`search.pb_${pb.key}`, { defaultValue: pb.key })}
                </Tag.CheckableTag>
              )
              const note = disabled
                ? t('search.pb_not_for_type')
                : pb.unavailable_modules.length
                  ? t('search.pb_partial', { n: pb.unavailable_modules.length })
                  : pb.modules.join(', ')
              return <Tooltip key={pb.key} title={note}>{chip}</Tooltip>
            })}
          </Space>
        </Form.Item>
      )}

      <Form.Item name="modules" label={t('search.modules_label')}>
        <Checkbox.Group>
          <Space direction="vertical">
            {visibleModules.length === 0 ? (
              <Alert
                type="info"
                showIcon
                message={t('search.no_modules_for_type', { type: queryType })}
              />
            ) : (
              visibleModules.map((m) => {
                const tools = m.tools
                  .filter((tool) => tool.query_types.includes(queryType))
                  .map((tool) => t(tool.label_key))
                  .join(', ')
                return (
                  <Checkbox key={m.name} value={m.name}>
                    <Tooltip title={tools}>{t(m.label_key)}</Tooltip>
                  </Checkbox>
                )
              })
            )}
          </Space>
        </Checkbox.Group>
      </Form.Item>

      {/* Tool-level selection. Collapsed by default and pre-ticked, so an
          analyst who ignores it gets exactly the previous behaviour. */}
      {toolGroups.length > 0 && (
        <Collapse
          ghost
          size="small"
          style={{ marginBottom: 16 }}
          items={[{
            key: 'tools',
            label: (
              <Space size={6}>
                <Text>{t('search.tools_label')}</Text>
                <Tag color={excluded.size ? 'orange' : 'default'} style={{ marginInlineEnd: 0 }}>
                  {chosenTools.length}/{allToolNames.length}
                </Tag>
              </Space>
            ),
            children: (
              <Space direction="vertical" size={10} style={{ width: '100%' }}>
                <Space size={8}>
                  <Button size="small" onClick={() => setExcluded(new Set())}
                          disabled={!excluded.size}>
                    {t('search.tools_all')}
                  </Button>
                  <Button
                    size="small"
                    onClick={() => setExcluded(new Set(
                      allTools.filter((tl) => tl.latency_class === 'slow')
                              .map((tl) => tl.tool),
                    ))}
                  >
                    {t('search.tools_skip_slow')}
                  </Button>
                </Space>
                {toolGroups.map((g) => (
                  <div key={g.module.name}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {t(g.module.label_key)}
                    </Text>
                    <div style={{ paddingLeft: 8, marginTop: 4 }}>
                      <Space direction="vertical" size={2}>
                        {g.tools.map((tl: any) => (
                          <Checkbox
                            key={tl.tool}
                            checked={!excluded.has(tl.tool)}
                            onChange={(e) => setExcluded((prev) => {
                              const n = new Set(prev)
                              e.target.checked ? n.delete(tl.tool) : n.add(tl.tool)
                              return n
                            })}
                          >
                            <Space size={4}>
                              {t(tl.label_key)}
                              {/* What the tool is worth and what it costs —
                                  the two things the choice is actually about. */}
                              {tl.reliability && tl.reliability !== 'F' && (
                                <Tag style={{ marginInlineEnd: 0, fontSize: 10 }}>
                                  {tl.reliability}
                                </Tag>
                              )}
                              {tl.latency_class === 'slow' && (
                                <Tag color="orange" style={{ marginInlineEnd: 0, fontSize: 10 }}>
                                  {t('search.tool_slow')}
                                </Tag>
                              )}
                              {tl.requires_key && (
                                <Tag color="blue" style={{ marginInlineEnd: 0, fontSize: 10 }}>
                                  {t('search.tool_needs_key')}
                                </Tag>
                              )}
                            </Space>
                          </Checkbox>
                        ))}
                      </Space>
                    </div>
                  </div>
                ))}
              </Space>
            ),
          }]}
        />
      )}
      {/* Sending an empty tool list would mean "all" to the backend, i.e. the
          opposite of what was clicked. Block the submit instead. */}
      {allToolNames.length > 0 && chosenTools.length === 0 && (
        <Alert type="warning" showIcon style={{ marginBottom: 16 }}
               message={t('search.tools_none_selected')} />
      )}

      <Form.Item>
        <Button
          type="primary"
          htmlType="submit"
          loading={polling}
          size="large"
          // A search with zero tools would be sent as "all" — see the alert above.
          disabled={visibleModules.length === 0 ||
                    (allToolNames.length > 0 && chosenTools.length === 0)}
        >
          {polling ? t('search.running') : t('search.start')}
        </Button>
      </Form.Item>

      {(status === 'running' || status === 'queued') && (
        <Progress
          percent={searchProgressPercent(toolProgress, status, false)}
          status="active"
        />
      )}

      {toolProgress.length > 0 && (
        <Table
          size="small"
          pagination={false}
          style={{ marginTop: 12 }}
          rowKey={(r: any) => `${r.module}:${r.tool}`}
          dataSource={toolProgress}
          columns={[
            { title: t('search_progress.tp_module'), dataIndex: 'module',
              render: (m: string) => <Tag color="blue">{m}</Tag> },
            { title: t('search_progress.tp_tool'), dataIndex: 'tool',
              render: (v: string) => <code>{v}</code> },
            { title: t('search_progress.tp_status'), dataIndex: 'status',
              render: (s: string) => {
                const m: Record<string, string> = {
                  pending: 'default', running: 'processing',
                  success: 'success', partial: 'warning', error: 'error',
                }
                return <Tag color={m[s] || 'default'}>{s}</Tag>
              } },
            { title: t('search_progress.tp_findings'), dataIndex: 'findings', align: 'right' as const },
            { title: t('search_progress.tp_edges'), dataIndex: 'edges', align: 'right' as const },
            { title: t('search_progress.tp_duration'), dataIndex: 'duration_seconds', align: 'right' as const,
              render: (s: number) => s ? `${s.toFixed(1)}s` : '—' },
            { title: t('search_progress.tp_errors'), dataIndex: 'errors',
              render: (errs: string[], record: any) => {
                if (errs?.length) return <span style={{ color: '#fa541c', fontSize: 12 }}>
                    {errs[0].length > 60 ? errs[0].slice(0, 60) + '…' : errs[0]}
                  </span>
                const notes = record?.notes as string[] | undefined
                if (notes?.length) return <span style={{ color: '#8c8c8c', fontSize: 12 }}>
                    ℹ {notes[0].length > 60 ? notes[0].slice(0, 60) + '…' : notes[0]}
                  </span>
                return <span style={{ color: '#999' }}>—</span>
              } },
          ]}
        />
      )}
      {status === 'completed' && <Alert type="success" message={t('search.completed')} />}
      {status === 'partial' && (
        <Alert type="warning" message={t('search.completed_partial')} />
      )}
      {status === 'failed' && <Alert type="error" message={t('search.failed')} />}

      <Modal
        title={t('cases.new')}
        open={newCaseOpen}
        onCancel={() => setNewCaseOpen(false)}
        onOk={() => newCaseForm.validateFields().then(createCaseMutation)}
        destroyOnClose
      >
        <Form form={newCaseForm} layout="vertical">
          <Form.Item name="title" label={t('cases.col_title')} rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="priority" label={t('cases.col_priority')} initialValue="normal">
            <Select
              options={[
                { value: 'normal', label: t('cases.priority_normal') },
                { value: 'high',   label: t('cases.priority_high') },
                { value: 'urgent', label: t('cases.priority_urgent') },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>
    </Form>
  )
}

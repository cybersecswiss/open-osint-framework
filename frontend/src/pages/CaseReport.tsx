import { useEffect, useState } from 'react'
import { useAllPlaybooks } from '../components/cases/CaseTemplateSelect'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Typography, Checkbox, Button, Space, Spin, Alert, Radio, message,
} from 'antd'
import { ArrowLeftOutlined, FilePdfOutlined, FileWordOutlined } from '@ant-design/icons'
import { useQuery, useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useStore } from '../store/useStore'
import { casesApi, reportApi } from '../api/client'
import LoadFailed from '../components/LoadFailed'
import { blobErrorDetail } from '../utils/blobError'

export default function CaseReport() {
  const { t, i18n } = useTranslation()
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { lang } = useStore()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [onlyRelevant, setOnlyRelevant] = useState(false)
  const [format, setFormat] = useState<'pdf' | 'docx'>('pdf')

  const { data: caseData } = useQuery({
    queryKey: ['case', id],
    queryFn: () => casesApi.get(id!),
    enabled: !!id,
  })
  const { data: sections, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['report-sections'],
    queryFn: reportApi.listSections,
  })

  // First time we see the section list, pre-select every default section —
  // or, for a case opened from a template, that template's outline.
  const playbooks = useAllPlaybooks()
  useEffect(() => {
    if (!sections || selected.size !== 0 || !caseData) return
    const outline = caseData.template
      ? playbooks.find((p) => p.key === caseData.template)?.report_sections
      : null
    if (caseData.template && !playbooks.length) return   // wait for the outline
    const names = new Set(sections.map((s) => s.name))
    setSelected(new Set(outline?.length
      ? outline.filter((n) => names.has(n))
      : sections.filter((s) => s.default).map((s) => s.name)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sections, caseData, playbooks])

  const generateMut = useMutation({
    mutationFn: () =>
      reportApi.generate(id!, Array.from(selected), lang || i18n.language || 'en',
                         { only_relevant: onlyRelevant, format }),
    onSuccess: (blob) => {
      // Trigger a browser download. Filename mirrors the backend's
      // Content-Disposition header but without parsing it (the
      // browser uses the URL slug instead).
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${caseData?.case_number || id}${onlyRelevant ? '-auszug' : ''}.${format}`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      message.success(t('report.msg_generated'))
    },
    // The response is a Blob, so the server's `detail` has to be read out of
    // it — see utils/blobError. Without this every failure reads the same.
    onError: async (e: any) =>
      message.error((await blobErrorDetail(e)) || t('report.msg_failed')),
  })

  const toggle = (name: string) => {
    const next = new Set(selected)
    next.has(name) ? next.delete(name) : next.add(name)
    setSelected(next)
  }

  if (isLoading) return <Spin />
  // Not `<Empty/>`: a section list that failed to load is not a report with
  // no sections. Rendering it as one left the investigator on a blank page
  // with no way to retry and no reason given.
  if (isError || !sections) {
    return <LoadFailed what={t('loadfail.what.sections')}
                       onRetry={() => refetch()} loading={isFetching} />
  }

  return (
    <div style={{ maxWidth: 720 }}>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/cases/${id}`)}>
          {t('report.back_to_case')}
        </Button>
      </Space>

      <Typography.Title level={3} style={{ marginTop: 0 }}>
        {t('report.title')}
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        {caseData?.case_number} — {caseData?.title}
      </Typography.Paragraph>

      <Card title={t('report.choose_sections')} style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }}>
          {sections.map((s) => (
            <Checkbox
              key={s.name}
              checked={selected.has(s.name)}
              onChange={() => toggle(s.name)}
            >
              {/*
                The translated name leads; the internal key follows in grey.
                It used to be the other way round, so the investigator picking
                sections for a court annex read `entities_table` first and the
                German label second. The key stays visible because it is what
                support asks for, but it is no longer the headline.
              */}
              <span>{t(`report.section_${s.name}`, s.name)}</span>
              <Typography.Text type="secondary"
                               style={{ fontSize: 11, marginLeft: 8, fontFamily: 'monospace' }}>
                {s.name}
              </Typography.Text>
            </Checkbox>
          ))}
        </Space>
      </Card>

      <Card title={t('report.options')} style={{ marginBottom: 16 }}>
        <Space direction="vertical">
          <Checkbox checked={onlyRelevant} onChange={(e) => setOnlyRelevant(e.target.checked)}>
            {t('report.only_relevant')}
          </Checkbox>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t('report.only_relevant_hint')}</Typography.Text>
          <Radio.Group value={format} onChange={(e) => setFormat(e.target.value)} optionType="button">
            <Radio.Button value="pdf"><FilePdfOutlined /> PDF</Radio.Button>
            <Radio.Button value="docx"><FileWordOutlined /> Word</Radio.Button>
          </Radio.Group>
          {format === 'docx' && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t('report.docx_hint')}</Typography.Text>
          )}
        </Space>
      </Card>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={t('report.lang_info', { lang: (lang || i18n.language || 'en').toUpperCase() })}
      />

      <Button
        type="primary"
        size="large"
        icon={format === 'docx' ? <FileWordOutlined /> : <FilePdfOutlined />}
        loading={generateMut.isPending}
        disabled={selected.size === 0}
        onClick={() => generateMut.mutate()}
      >
        {format === 'docx' ? t('report.generate_docx') : t('report.generate_pdf')}
      </Button>
    </div>
  )
}

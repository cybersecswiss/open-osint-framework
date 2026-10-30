import { useState } from 'react'
import { Alert, Button, Empty, Image, Input, Modal, Space, Spin, Table, Tag, Tooltip, Typography, message } from 'antd'
import { CameraOutlined, DownloadOutlined, EyeOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { evidenceApi, type EvidenceItem } from '../../api/client'
import { formatDateTime } from '../../utils/datetime'
import { blobErrorDetail } from '../../utils/blobError'

const { Text, Paragraph } = Typography

export function evidenceErrorText(t: (k: string) => string, e: any): string {
  const d = e?.response?.data?.detail
  const known: Record<string, string> = {
    evidence_no_url: 'evidence.err_no_url',
    evidence_blocked: 'evidence.err_blocked',
    evidence_store_unavailable: 'evidence.err_store',
    capture_unavailable: 'evidence.err_capture',
  }
  if (known[d]) return t(known[d])
  if (typeof d === 'string' && d.startsWith('capture_failed')) return t('evidence.err_load')
  if (e?.code === 'ECONNABORTED') return t('evidence.err_timeout')
  return t('evidence.err_generic')
}

function saveBlob(blob: Blob, name: string) {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 10000)
}

/**
 * Saved pages of a case: what a page showed, when, and the SHA-256 of each
 * file. The hashes are what makes a file usable later — anyone can recompute
 * them from the download and compare.
 */
export default function EvidencePanel({ caseId }: { caseId: string }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [url, setUrl] = useState('')
  const [preview, setPreview] = useState<string | null>(null)
  const q = useQuery({ queryKey: ['evidence', caseId], queryFn: () => evidenceApi.list(caseId), retry: false })

  const captureMut = useMutation({
    mutationFn: () => evidenceApi.capture(caseId, { url: url.trim() }),
    onSuccess: () => {
      message.success(t('evidence.saved'))
      setUrl('')
      qc.invalidateQueries({ queryKey: ['evidence', caseId] })
      qc.invalidateQueries({ queryKey: ['case-activity', caseId] })
    },
    onError: (e: any) => message.error(evidenceErrorText(t, e)),
  })

  const download = async (r: EvidenceItem, kind: 'screenshot' | 'archive') => {
    try {
      const blob = await evidenceApi.file(caseId, r.id, kind)
      const ext = kind === 'screenshot' ? 'png' : (r.archive_type === 'text/html' ? 'html' : 'mhtml')
      saveBlob(blob, `evidence-${r.captured_at.slice(0, 10)}-${r.id.slice(0, 8)}.${ext}`)
    } catch (e) {
      message.error(await blobErrorDetail(e) || t('evidence.err_generic'))
    }
  }
  const show = async (r: EvidenceItem) => {
    try {
      setPreview(URL.createObjectURL(await evidenceApi.file(caseId, r.id, 'screenshot')))
    } catch (e) {
      message.error(await blobErrorDetail(e) || t('evidence.err_generic'))
    }
  }

  return (
    <div>
      <Paragraph type="secondary" style={{ marginTop: 0 }}>{t('evidence.intro')}</Paragraph>
      <Space.Compact style={{ width: '100%', maxWidth: 720, marginBottom: 16 }}>
        <Input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder={t('evidence.url_placeholder')}
          onPressEnter={() => url.trim() && captureMut.mutate()}
          disabled={captureMut.isPending}
        />
        <Button type="primary" icon={<CameraOutlined />} loading={captureMut.isPending}
                disabled={!url.trim()} onClick={() => captureMut.mutate()}>
          {t('evidence.capture_url')}
        </Button>
      </Space.Compact>
      {captureMut.isPending && <Alert type="info" showIcon style={{ marginBottom: 12 }} message={t('evidence.capturing')} />}

      {q.isLoading ? <Spin /> : q.isError ? (
        <Alert type="warning" showIcon message={t('evidence.err_store')} />
      ) : !(q.data?.evidence || []).length ? (
        <Empty description={t('evidence.empty')} />
      ) : (
        <Table<EvidenceItem>
          size="small" rowKey="id" dataSource={q.data!.evidence}
          pagination={{ pageSize: 25, hideOnSinglePage: true }}
          columns={[
            { title: t('evidence.col_time'), dataIndex: 'captured_at', width: 150, render: (v) => formatDateTime(v) },
            {
              title: t('evidence.col_page'), key: 'page',
              render: (_, r) => (
                <Space direction="vertical" size={0}>
                  <Text strong>{r.title || '—'}</Text>
                  <Text type="secondary" copyable={{ text: r.final_url || r.url }} style={{ wordBreak: 'break-all' }}>
                    {r.final_url || r.url}
                  </Text>
                  <Space size={4} wrap>
                    {r.http_status != null && <Tag color={r.http_status < 400 ? 'green' : 'red'}>HTTP {r.http_status}</Tag>}
                    {r.via_tor && <Tag color="purple">Tor</Tag>}
                    {!!r.meta?.redirect_chain?.length && (
                      <Tooltip title={[r.url, ...r.meta.redirect_chain].join(' → ')}>
                        <Tag>{t('evidence.redirects', { count: r.meta.redirect_chain.length })}</Tag>
                      </Tooltip>
                    )}
                    {r.meta?.screenshot_truncated && <Tag color="orange">{t('evidence.truncated')}</Tag>}
                    {r.archive_type === 'text/html' && <Tag color="orange">{t('evidence.html_only')}</Tag>}
                  </Space>
                </Space>
              ),
            },
            { title: t('evidence.col_by'), dataIndex: 'captured_by', width: 130 },
            {
              title: 'SHA-256', key: 'sha', width: 220,
              render: (_, r) => (
                <Space direction="vertical" size={0}>
                  <Text code copyable={{ text: r.screenshot_sha256 }} title={r.screenshot_sha256}>PNG {r.screenshot_sha256.slice(0, 12)}…</Text>
                  <Text code copyable={{ text: r.archive_sha256 }} title={r.archive_sha256}>{r.archive_type === 'text/html' ? 'HTML' : 'MHTML'} {r.archive_sha256.slice(0, 12)}…</Text>
                </Space>
              ),
            },
            {
              title: '', key: 'act', width: 150,
              render: (_, r) => (
                <Space size={4} wrap>
                  <Button size="small" icon={<EyeOutlined />} onClick={() => show(r)} aria-label={t('evidence.show')} title={t('evidence.show')} />
                  <Button size="small" icon={<DownloadOutlined />} onClick={() => download(r, 'screenshot')}>PNG</Button>
                  <Button size="small" icon={<DownloadOutlined />} onClick={() => download(r, 'archive')}>
                    {r.archive_type === 'text/html' ? 'HTML' : 'MHTML'}
                  </Button>
                </Space>
              ),
            },
          ]}
        />
      )}
      <Modal open={!!preview} footer={null} width="90vw" onCancel={() => { if (preview) URL.revokeObjectURL(preview); setPreview(null) }}>
        {preview && <Image src={preview} preview={false} style={{ width: '100%' }} />}
      </Modal>
    </div>
  )
}

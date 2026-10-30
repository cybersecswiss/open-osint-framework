import { useState } from 'react'
import {
  Table, Button, Tag, Space, Modal, Form, Input, Drawer, Typography, message, Empty, Checkbox,
} from 'antd'
import { PlusOutlined, SendOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import dayjs from 'dayjs'
import { supportApi, SupportTicket } from '../../api/client'

const { Text } = Typography

// Message thread — shared bubble style. `mine` = messages authored by the
// viewer's side (right-aligned).
export function Thread({ messages, mineRole }: { messages: any[]; mineRole: 'tenant' | 'operator' }) {
  const { t } = useTranslation()
  if (!messages?.length) return <Empty description={t('support.no_messages')} />
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {messages.map((m) => {
        const mine = m.author_role === mineRole
        return (
          <div key={m.id} style={{ alignSelf: mine ? 'flex-end' : 'flex-start', maxWidth: '80%' }}>
            <div style={{
              background: mine ? '#1677ff' : '#f0f0f0', color: mine ? '#fff' : '#000',
              padding: '8px 12px', borderRadius: 10, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            }}>{m.body}</div>
            <div style={{ fontSize: 10, color: '#8c8c8c', textAlign: mine ? 'right' : 'left', marginTop: 2 }}>
              {m.author_role === 'operator' ? t('support.role_operator') : m.author_name} · {dayjs(m.created_at).format('DD.MM HH:mm')}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default function SupportTickets() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [newOpen, setNewOpen] = useState(false)
  const [openId, setOpenId] = useState<string | null>(null)
  const [showClosed, setShowClosed] = useState(false)
  const [form] = Form.useForm()
  const [reply, setReply] = useState('')

  const { data: tickets, isLoading } = useQuery({
    queryKey: ['support-tickets'], queryFn: supportApi.list,
    refetchInterval: 12000, refetchIntervalInBackground: true,
  })
  const { data: ticket } = useQuery({
    queryKey: ['support-ticket', openId], queryFn: () => supportApi.get(openId!),
    enabled: !!openId,
    // Live chat: poll every 3 s AND keep polling when the tab is in the
    // background — otherwise the other side's replies only show on focus.
    refetchInterval: 3000, refetchIntervalInBackground: true,
  })

  const createMut = useMutation({
    mutationFn: (v: { subject: string; body: string }) => supportApi.create(v),
    onSuccess: (tk) => { setNewOpen(false); form.resetFields(); qc.invalidateQueries({ queryKey: ['support-tickets'] }); setOpenId(tk.id) },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('support.failed')),
  })
  const replyMut = useMutation({
    mutationFn: (body: string) => supportApi.reply(openId!, body),
    onSuccess: () => { setReply(''); qc.invalidateQueries({ queryKey: ['support-ticket', openId] }); qc.invalidateQueries({ queryKey: ['support-tickets'] }) },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('support.failed')),
  })

  const columns = [
    { title: t('support.col_subject'), dataIndex: 'subject', key: 'subject',
      render: (v: string, r: SupportTicket) => <a onClick={() => setOpenId(r.id)}>{v}</a> },
    { title: t('support.col_status'), dataIndex: 'status', key: 'status',
      render: (s: string) => s === 'open' ? <Tag color="green">{t('support.status_open')}</Tag> : <Tag>{t('support.status_closed')}</Tag> },
    { title: t('support.col_messages'), dataIndex: 'message_count', key: 'mc' },
    { title: t('support.col_updated'), dataIndex: 'last_message_at', key: 'upd', render: (v: string) => dayjs(v).format('DD.MM.YYYY HH:mm') },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 12, justifyContent: 'space-between', width: '100%' }}>
        <Text type="secondary">{t('support.tenant_intro')}</Text>
        <Space>
          <Checkbox checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)}>{t('support.show_closed')}</Checkbox>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setNewOpen(true)}>{t('support.new_ticket')}</Button>
        </Space>
      </Space>

      <Table rowKey="id" loading={isLoading}
        dataSource={showClosed ? tickets : (tickets ?? []).filter((tk) => tk.status !== 'closed')}
        columns={columns as any} pagination={false} size="small" />

      <Modal title={t('support.new_ticket')} open={newOpen} onCancel={() => setNewOpen(false)}
        onOk={async () => createMut.mutate(await form.validateFields())} okText={t('support.send')} confirmLoading={createMut.isPending}>
        <Form form={form} layout="vertical">
          <Form.Item name="subject" label={t('support.f_subject')} rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="body" label={t('support.f_message')} rules={[{ required: true }]}><Input.TextArea rows={4} /></Form.Item>
        </Form>
      </Modal>

      <Drawer title={ticket?.subject || t('support.ticket')} open={!!openId} width={460} onClose={() => setOpenId(null)}
        extra={ticket && (ticket.status === 'open' ? <Tag color="green">{t('support.status_open')}</Tag> : <Tag>{t('support.status_closed')}</Tag>)}>
        {ticket && (
          <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            <div style={{ flex: 1, overflowY: 'auto', marginBottom: 12 }}>
              <Thread messages={ticket.messages} mineRole="tenant" />
            </div>
            <Space.Compact style={{ width: '100%' }}>
              <Input.TextArea value={reply} onChange={(e) => setReply(e.target.value)} rows={2}
                placeholder={t('support.reply_placeholder')} onPressEnter={(e) => { e.preventDefault(); if (reply.trim()) replyMut.mutate(reply) }} />
              <Button aria-label={t('a11y.send_reply')} type="primary" icon={<SendOutlined />} loading={replyMut.isPending}
                disabled={!reply.trim()} onClick={() => replyMut.mutate(reply)} />
            </Space.Compact>
          </div>
        )}
      </Drawer>
    </div>
  )
}

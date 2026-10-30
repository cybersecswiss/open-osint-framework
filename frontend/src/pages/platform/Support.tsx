import { useState } from 'react'
import {
  Typography, Table, Tag, Space, Drawer, Input, Button, Segmented, message, Popconfirm,
} from 'antd'
import { SendOutlined, CheckOutlined, RedoOutlined, DeleteOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import dayjs from 'dayjs'
import { platformSupportApi, SupportTicket } from '../../api/client'
import { Thread } from '../../components/admin/SupportTickets'

const { Title, Text } = Typography

export default function Support() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [filter, setFilter] = useState<'all' | 'open' | 'closed'>('open')
  const [openId, setOpenId] = useState<string | null>(null)
  const [reply, setReply] = useState('')

  const { data: tickets, isLoading } = useQuery({
    queryKey: ['pf-support', filter],
    queryFn: () => platformSupportApi.list(filter === 'all' ? {} : { status: filter }),
    refetchInterval: 10000, refetchIntervalInBackground: true,
  })
  const { data: ticket } = useQuery({
    queryKey: ['pf-support-ticket', openId], queryFn: () => platformSupportApi.get(openId!),
    enabled: !!openId,
    // Live chat: 3 s poll incl. background tabs (see SupportTickets.tsx).
    refetchInterval: 3000, refetchIntervalInBackground: true,
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['pf-support'] })
    qc.invalidateQueries({ queryKey: ['pf-support-ticket', openId] })
  }
  const replyMut = useMutation({
    mutationFn: (body: string) => platformSupportApi.reply(openId!, body),
    onSuccess: () => { setReply(''); invalidate() },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('support.failed')),
  })
  const statusMut = useMutation({
    mutationFn: (status: string) => platformSupportApi.setStatus(openId!, status),
    onSuccess: () => { message.success(t('support.saved')); invalidate() },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('support.failed')),
  })
  const deleteMut = useMutation({
    mutationFn: (id: string) => platformSupportApi.remove(id),
    onSuccess: () => { message.success(t('support.deleted')); setOpenId(null); qc.invalidateQueries({ queryKey: ['pf-support'] }) },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('support.failed')),
  })

  const columns = [
    { title: t('glbadmin.col_tenant'), dataIndex: 'tenant', key: 'tenant', render: (v: string) => <Tag color="blue">{v}</Tag> },
    { title: t('support.col_subject'), dataIndex: 'subject', key: 'subject', render: (v: string, r: SupportTicket) => <a onClick={() => setOpenId(r.id)}>{v}</a> },
    { title: t('support.col_status'), dataIndex: 'status', key: 'status',
      render: (s: string) => s === 'open' ? <Tag color="green">{t('support.status_open')}</Tag> : <Tag>{t('support.status_closed')}</Tag> },
    { title: t('support.col_from'), dataIndex: 'created_by', key: 'by' },
    { title: t('support.col_updated'), dataIndex: 'last_message_at', key: 'upd', render: (v: string) => dayjs(v).format('DD.MM.YYYY HH:mm') },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 12, justifyContent: 'space-between', width: '100%' }}>
        <Title level={3} style={{ margin: 0 }}>{t('support.console_title')}</Title>
        <Segmented aria-label={t('a11y.ticket_filter')} value={filter} onChange={(v) => setFilter(v as any)}
          options={[{ label: t('support.filter_open'), value: 'open' }, { label: t('support.filter_closed'), value: 'closed' }, { label: t('support.filter_all'), value: 'all' }]} />
      </Space>

      <Table rowKey="id" loading={isLoading} dataSource={tickets} columns={columns as any} pagination={false} size="small" />

      <Drawer open={!!openId} width={480} onClose={() => setOpenId(null)}
        title={ticket ? <Space><Tag color="blue">{ticket.tenant}</Tag><Text>{ticket.subject}</Text></Space> : ''}
        extra={ticket && (
          <Space>
            {ticket.status === 'open'
              ? <Button size="small" icon={<CheckOutlined />} onClick={() => statusMut.mutate('closed')}>{t('support.close')}</Button>
              : <Button size="small" icon={<RedoOutlined />} onClick={() => statusMut.mutate('open')}>{t('support.reopen')}</Button>}
            <Popconfirm title={t('support.delete_confirm')} okButtonProps={{ danger: true }} onConfirm={() => deleteMut.mutate(openId!)}>
              <Button size="small" danger icon={<DeleteOutlined />}>{t('support.delete')}</Button>
            </Popconfirm>
          </Space>
        )}>
        {ticket && (
          <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            <div style={{ flex: 1, overflowY: 'auto', marginBottom: 12 }}>
              <Thread messages={ticket.messages} mineRole="operator" />
            </div>
            <Space.Compact style={{ width: '100%' }}>
              <Input.TextArea value={reply} onChange={(e) => setReply(e.target.value)} rows={2}
                placeholder={t('support.reply_placeholder')} onPressEnter={(e) => { e.preventDefault(); if (reply.trim()) replyMut.mutate(reply) }} />
              <Button aria-label={t('a11y.send_reply')} type="primary" icon={<SendOutlined />} loading={replyMut.isPending} disabled={!reply.trim()} onClick={() => replyMut.mutate(reply)} />
            </Space.Compact>
          </div>
        )}
      </Drawer>
    </div>
  )
}

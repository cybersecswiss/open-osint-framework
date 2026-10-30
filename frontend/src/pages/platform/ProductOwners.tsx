import { useState } from 'react'
import {
  Typography, Table, Button, Space, Modal, Form, Input, Popconfirm, message, Alert, Tag,
} from 'antd'
import { PlusOutlined, KeyOutlined, DeleteOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { operatorsApi, ProductOwner } from '../../api/client'
import { useStore } from '../../store/useStore'

const { Title } = Typography

export default function ProductOwners() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const me = useStore((s) => s.user)
  const [createOpen, setCreateOpen] = useState(false)
  const [pwFor, setPwFor] = useState<ProductOwner | null>(null)
  const [createForm] = Form.useForm()
  const [pwForm] = Form.useForm()

  const { data: owners, isLoading } = useQuery({ queryKey: ['platform-operators'], queryFn: operatorsApi.list })
  const invalidate = () => qc.invalidateQueries({ queryKey: ['platform-operators'] })

  const createMut = useMutation({
    mutationFn: (v: { username: string; email?: string; password: string }) => operatorsApi.create(v),
    onSuccess: () => { message.success(t('glbadmin.po_created')); setCreateOpen(false); createForm.resetFields(); invalidate() },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('glbadmin.save_failed')),
  })
  const pwMut = useMutation({
    mutationFn: (v: { id: string; password: string }) => operatorsApi.resetPassword(v.id, v.password),
    onSuccess: () => { message.success(t('glbadmin.po_pw_reset')); setPwFor(null); pwForm.resetFields() },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('glbadmin.save_failed')),
  })
  const delMut = useMutation({
    mutationFn: (id: string) => operatorsApi.remove(id),
    onSuccess: () => { message.success(t('glbadmin.po_deleted')); invalidate() },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('glbadmin.save_failed')),
  })

  const columns = [
    { title: t('glbadmin.po_username'), dataIndex: 'username', key: 'username',
      render: (v: string, r: ProductOwner) => <Space>{v}{r.id === me?.user_id && <Tag color="blue">{t('glbadmin.po_you')}</Tag>}</Space> },
    { title: t('glbadmin.po_email'), dataIndex: 'email', key: 'email', render: (v: string) => v || '—' },
    { title: t('glbadmin.col_status'), dataIndex: 'enabled', key: 'enabled',
      render: (v: boolean) => v ? <Tag color="green">{t('glbadmin.status_active')}</Tag> : <Tag>{t('glbadmin.status_suspended')}</Tag> },
    {
      title: t('glbadmin.col_actions'), key: 'actions',
      render: (_: any, r: ProductOwner) => (
        <Space>
          <Button size="small" icon={<KeyOutlined />} onClick={() => setPwFor(r)}>{t('glbadmin.po_reset_pw')}</Button>
          <Popconfirm title={t('glbadmin.po_delete_confirm', { user: r.username })} okButtonProps={{ danger: true }}
            disabled={r.id === me?.user_id} onConfirm={() => delMut.mutate(r.id)}>
            <Button aria-label={t('a11y.delete_operator')} size="small" danger icon={<DeleteOutlined />} disabled={r.id === me?.user_id} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Space align="baseline" style={{ marginBottom: 4, justifyContent: 'space-between', width: '100%' }}>
        <Title level={3} style={{ margin: 0 }}>{t('glbadmin.nav_operators')}</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>{t('glbadmin.po_new')}</Button>
      </Space>
      <Alert type="info" showIcon style={{ margin: '8px 0 12px' }} message={t('glbadmin.po_note')} />

      <Table rowKey="id" loading={isLoading} dataSource={owners} columns={columns as any} pagination={false} size="small" />

      <Modal title={t('glbadmin.po_new')} open={createOpen} onCancel={() => setCreateOpen(false)}
        onOk={async () => createMut.mutate(await createForm.validateFields())}
        okText={t('glbadmin.create_ok')} confirmLoading={createMut.isPending}>
        <Form form={createForm} layout="vertical">
          <Form.Item name="username" label={t('glbadmin.po_username')} rules={[{ required: true }]}><Input placeholder="anna" /></Form.Item>
          <Form.Item name="email" label={t('glbadmin.po_email')} rules={[{ type: 'email' }]}><Input placeholder="anna@team.example" /></Form.Item>
          <Form.Item name="password" label={t('glbadmin.po_password')} rules={[{ required: true, min: 8 }]}><Input.Password /></Form.Item>
        </Form>
      </Modal>

      <Modal title={`${t('glbadmin.po_reset_pw')} — ${pwFor?.username ?? ''}`} open={!!pwFor} onCancel={() => setPwFor(null)}
        onOk={async () => { const v = await pwForm.validateFields(); pwMut.mutate({ id: pwFor!.id, password: v.password }) }}
        okText={t('common.save')} confirmLoading={pwMut.isPending}>
        <Form form={pwForm} layout="vertical">
          <Form.Item name="password" label={t('glbadmin.po_password')} rules={[{ required: true, min: 8 }]}><Input.Password /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

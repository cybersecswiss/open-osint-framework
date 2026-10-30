import { Table, Button, Modal, Form, Input, Select, Space, Tag, Typography, Popconfirm, message, Dropdown, MenuProps, Skeleton, Alert } from 'antd'
import { PlusOutlined, DeleteOutlined, EyeOutlined, CopyOutlined, ExclamationCircleOutlined, LockOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import LoadFailed from '../components/LoadFailed'
import { casesApi } from '../api/client'
import { useStore } from '../store/useStore'
import CaseAccessFields from '../components/cases/CaseAccessFields'
import CaseTemplateSelect from '../components/cases/CaseTemplateSelect'
import { useState } from 'react'
import { formatDate } from '../utils/datetime'

export default function Cases() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const user = useStore((s) => s.user)
  const isAdmin = user?.roles.includes('admin') ?? false
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()
  const [modal, modalContext] = Modal.useModal()
  // Right-click context menu state — mirror of the GraphView pattern.
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; row: any } | null>(null)

  // `isError` matters here more than anywhere: this list is where an
  // investigator checks whether their work is still there. Unpacked with
  // `= []` alone, a failed request rendered an empty table — the same picture
  // a tenant with no cases sees.
  const { data: cases = [], isLoading, isError, refetch } = useQuery({
    queryKey: ['cases'],
    queryFn: casesApi.list,
  })

  const create = useMutation({
    mutationFn: casesApi.create,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['cases'] })
      setOpen(false)
      form.resetFields()
    },
  })

  const remove = useMutation({
    mutationFn: (id: string) => casesApi.delete(id),
    onSuccess: () => {
      message.success(t('cases.msg_deleted'))
      qc.invalidateQueries({ queryKey: ['cases'] })
    },
    onError: (e: any) =>
      message.error(e?.response?.data?.detail || t('cases.msg_delete_failed')),
  })

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
      .then(() => message.success(t('cases.msg_copied')))
      .catch(() => message.error(t('cases.msg_copy_failed')))
  }

  // Confirm dialog used from the right-click menu (Modal.confirm, since
  // Popconfirm needs an anchor element which we don't have here).
  const confirmDeleteFromMenu = (row: any) => {
    modal.confirm({
      title: t('cases.confirm_delete_title'),
      content: t('cases.confirm_delete_desc', { number: row.case_number }),
      okText: t('cases.delete'),
      okButtonProps: { danger: true },
      cancelText: t('common.cancel'),
      icon: <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />,
      onOk: () => remove.mutateAsync(row.id),
    })
  }

  const ctxMenuItems: MenuProps['items'] = ctxMenu
    ? [
        {
          key: 'open',
          icon: <EyeOutlined />,
          label: t('cases.ctx_open'),
          onClick: () => { navigate(`/cases/${ctxMenu.row.id}`); setCtxMenu(null) },
        },
        { type: 'divider' as const },
        {
          key: 'copy_number',
          icon: <CopyOutlined />,
          label: t('cases.ctx_copy_number'),
          onClick: () => { copyToClipboard(ctxMenu.row.case_number); setCtxMenu(null) },
        },
        {
          key: 'copy_id',
          icon: <CopyOutlined />,
          label: t('cases.ctx_copy_id'),
          onClick: () => { copyToClipboard(ctxMenu.row.id); setCtxMenu(null) },
        },
        ...(isAdmin ? [
          { type: 'divider' as const },
          {
            key: 'delete',
            icon: <DeleteOutlined />,
            label: t('cases.delete'),
            danger: true,
            onClick: () => { confirmDeleteFromMenu(ctxMenu.row); setCtxMenu(null) },
          },
        ] : []),
      ]
    : []

  const columns: any[] = [
    { title: t('cases.case_number'), dataIndex: 'case_number', width: 120 },
    {
      title: t('cases.col_title'), dataIndex: 'title',
      render: (v: string, r: any) => r.restricted
        ? <span><LockOutlined title={t('case_access.tag')} aria-label={t('case_access.tag')} style={{ color: '#722ed1', marginRight: 6 }} />{v}</span>
        : v,
    },
    {
      title: t('cases.col_status'),
      dataIndex: 'status',
      width: 120,
      render: (s: string) => <Tag color={s === 'open' ? 'green' : 'default'}>{t(`cases.status_${s}`, s)}</Tag>,
    },
    {
      title: t('cases.col_priority'),
      dataIndex: 'priority',
      width: 100,
      render: (p: string) => t(`cases.priority_${p}`, p),
    },
    {
      title: t('cases.created_at'),
      dataIndex: 'created_at',
      width: 150,
      render: (v: string) => formatDate(v),
    },
  ]
  if (isAdmin) {
    columns.push({
      title: t('cases.col_actions'),
      key: 'actions',
      width: 100,
      align: 'right' as const,
      // Stop click propagation so the row-navigate doesn't fire when
      // the user opens the confirm popover or clicks the delete icon.
      onCell: () => ({ onClick: (e: any) => e.stopPropagation() }),
      render: (_: unknown, row: any) => (
        <Popconfirm
          title={t('cases.confirm_delete_title')}
          description={t('cases.confirm_delete_desc', { number: row.case_number })}
          okText={t('cases.delete')}
          okButtonProps={{ danger: true, loading: remove.isPending }}
          cancelText={t('common.cancel')}
          onConfirm={() => remove.mutate(row.id)}
        >
          <Button danger size="small" icon={<DeleteOutlined />}>
            {t('cases.delete')}
          </Button>
        </Popconfirm>
      ),
    })
  }

  return (
    <div>
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          {t('cases.title')}
        </Typography.Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
          {t('cases.new')}
        </Button>
      </Space>

      {isLoading ? (
        <Skeleton active paragraph={{ rows: 6 }} />
      ) : (
        <>
        {isError && (
          <LoadFailed compact what={t('loadfail.what.list')}
                      onRetry={() => refetch()} />
        )}
        <Table
          dataSource={cases}
          columns={columns}
          rowKey="id"
          onRow={(r: any) => ({
            onClick: () => navigate(`/cases/${r.id}`),
            // Right-click → open context menu anchored at cursor.
            // preventDefault suppresses the browser's native menu.
            onContextMenu: (e: any) => {
              e.preventDefault()
              setCtxMenu({ x: e.clientX, y: e.clientY, row: r })
            },
          })}
          rowClassName="clickable-row"
        />
        </>
      )}

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

      {modalContext}

      <Modal
        title={t('cases.new')}
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.validateFields().then((values) => create.mutate(values))}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="title" label={t('cases.col_title')} rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="priority" label={t('cases.col_priority')} initialValue="normal">
            <Select
              options={[
                { value: 'normal', label: t('cases.priority_normal') },
                { value: 'high', label: t('cases.priority_high') },
                { value: 'urgent', label: t('cases.priority_urgent') },
              ]}
            />
          </Form.Item>
          <Form.Item name="template" label={t('case_template.label')} extra={t('case_template.hint')}>
            <CaseTemplateSelect />
          </Form.Item>
          <CaseAccessFields />
        </Form>
      </Modal>
    </div>
  )
}

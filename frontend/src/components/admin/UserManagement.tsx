import { useState } from 'react'
import {
  Table, Button, Modal, Form, Input, Switch, Select, Space, Tag,
  Popconfirm, message, Tooltip, Skeleton,
} from 'antd'
import {
  PlusOutlined, EditOutlined, DeleteOutlined, KeyOutlined, SafetyOutlined,
  WarningOutlined, UnlockOutlined, LockOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { adminApi, AdminUser } from '../../api/client'
import { useStore } from '../../store/useStore'

export default function UserManagement() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const { user: me } = useStore()

  const [editing, setEditing]   = useState<AdminUser | null>(null)
  const [creating, setCreating] = useState(false)
  const [pwUser, setPwUser]     = useState<AdminUser | null>(null)
  const [form] = Form.useForm()
  const [pwForm] = Form.useForm()

  const { data: users = [], isLoading } = useQuery({
    queryKey: ['admin-users'], queryFn: adminApi.listUsers,
  })
  const { data: roles = [] } = useQuery({
    queryKey: ['admin-roles'], queryFn: adminApi.listRoles,
  })

  const invalidate = () => qc.invalidateQueries({ queryKey: ['admin-users'] })

  const createMut = useMutation({
    mutationFn: adminApi.createUser,
    onSuccess: () => { message.success(t('admin.msg_user_created')); setCreating(false); form.resetFields(); invalidate() },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('admin.msg_create_failed')),
  })
  const updateMut = useMutation({
    mutationFn: (vars: { id: string; data: any }) => adminApi.updateUser(vars.id, vars.data),
    onSuccess: () => { message.success(t('admin.msg_user_updated')); setEditing(null); form.resetFields(); invalidate() },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('admin.msg_update_failed')),
  })
  const deleteMut = useMutation({
    mutationFn: adminApi.deleteUser,
    onSuccess: () => { message.success(t('admin.msg_user_deleted')); invalidate() },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('admin.msg_delete_failed')),
  })
  const pwMut = useMutation({
    mutationFn: (vars: { id: string; password: string; temporary: boolean }) =>
      adminApi.resetPassword(vars.id, vars.password, vars.temporary),
    onSuccess: () => { message.success(t('admin.msg_password_reset')); setPwUser(null); pwForm.resetFields() },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('admin.msg_reset_failed')),
  })
  const reset2faMut = useMutation({
    mutationFn: (id: string) => adminApi.reset2fa(id),
    onSuccess: (data) => { message.success(
      data.removed > 0
        ? t('admin.msg_2fa_reset_done', { count: data.removed })
        : t('admin.msg_2fa_reset_none'),
    ); invalidate() },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('admin.msg_reset_failed')),
  })

  // Pass-5b: drop CONFIGURE_TOTP from required-actions so the user can
  // log in via password-grant / scripts without being forced through
  // the interactive 2FA-setup flow. Important for dev-side test
  // accounts; in prod, leave 2FA mandatory.
  const disable2faReqMut = useMutation({
    mutationFn: (id: string) => adminApi.disable2faRequirement(id),
    onSuccess: (data) => { message.success(
      data.removed_totp_requirement
        ? t('admin.msg_2fa_req_disabled')
        : t('admin.msg_2fa_req_already_off'),
    ); invalidate() },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('admin.msg_2fa_req_disable_failed')),
  })

  const clearReqActionsMut = useMutation({
    mutationFn: (id: string) => adminApi.setRequiredActions(id, []),
    onSuccess: () => { message.success(t('admin.msg_req_actions_cleared')); invalidate() },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('admin.msg_req_actions_clear_failed')),
  })
  const enable2faReqMut = useMutation({
    mutationFn: (id: string) => adminApi.enable2faRequirement(id),
    onSuccess: (data) => { message.success(
      data.added_totp_requirement
        ? t('admin.msg_2fa_req_enabled')
        : t('admin.msg_2fa_req_already_on'),
    ); invalidate() },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('admin.msg_2fa_req_enable_failed')),
  })

  const openEdit = (u: AdminUser) => {
    setEditing(u)
    form.setFieldsValue({
      email: u.email, first_name: u.first_name, last_name: u.last_name,
      enabled: u.enabled, roles: u.roles,
    })
  }
  const openCreate = () => { setCreating(true); form.resetFields() }

  const submit = () => form.validateFields().then((values) => {
    if (editing) updateMut.mutate({ id: editing.id, data: values })
    else createMut.mutate(values)
  })

  const submitPassword = () => pwForm.validateFields().then((values) =>
    pwMut.mutate({ id: pwUser!.id, password: values.password, temporary: values.temporary })
  )

  const columns = [
    { title: t('admin.col_username'), dataIndex: 'username' },
    { title: t('admin.col_email'),    dataIndex: 'email' },
    { title: t('admin.col_name'), render: (_: any, u: AdminUser) =>
        [u.first_name, u.last_name].filter(Boolean).join(' ') || '—' },
    { title: t('admin.col_enabled'), dataIndex: 'enabled', width: 90,
      render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? t('admin.enabled_yes') : t('admin.enabled_no')}</Tag> },
    { title: t('admin.col_roles'), dataIndex: 'roles',
      render: (rs: string[]) => rs.map((r) => <Tag key={r} color={r === 'admin' ? 'gold' : 'blue'}>{r}</Tag>) },
    {
      title: t('admin.col_pending'),
      dataIndex: 'required_actions',
      width: 200,
      render: (acts: string[] | undefined) => {
        if (!acts || acts.length === 0) return <Tag color="default">—</Tag>
        return (
          <Space size={2} wrap>
            {acts.map((a) => (
              <Tag
                key={a}
                color={a === 'CONFIGURE_TOTP' ? 'orange' : 'blue'}
                icon={a === 'CONFIGURE_TOTP' ? <SafetyOutlined /> : <WarningOutlined />}
              >
                {a}
              </Tag>
            ))}
          </Space>
        )
      },
    },
    {
      title: t('admin.col_actions'), width: 240, fixed: 'right' as const,
      render: (_: any, u: AdminUser) => {
        const has2faReq = (u.required_actions || []).includes('CONFIGURE_TOTP')
        const hasAnyReq = (u.required_actions || []).length > 0
        return (
          <Space>
            <Tooltip title={t('admin.action_edit')}><Button aria-label={t('admin.action_edit')} size="small" icon={<EditOutlined />} onClick={() => openEdit(u)} /></Tooltip>
            <Tooltip title={t('admin.action_reset_pw')}><Button aria-label={t('admin.action_reset_pw')} size="small" icon={<KeyOutlined />} onClick={() => setPwUser(u)} /></Tooltip>
            <Popconfirm
              title={t('admin.confirm_reset_2fa_title', { name: u.username })}
              description={t('admin.confirm_reset_2fa_desc')}
              okText={t('admin.action_reset_2fa')}
              okButtonProps={{ loading: reset2faMut.isPending }}
              cancelText={t('common.cancel')}
              onConfirm={() => reset2faMut.mutate(u.id)}
            >
              <Tooltip title={t('admin.action_reset_2fa')}>
                <Button aria-label={t('admin.action_reset_2fa')} size="small" icon={<SafetyOutlined />} />
              </Tooltip>
            </Popconfirm>
            {has2faReq ? (
              <Popconfirm
                title={t('admin.confirm_disable_2fa_req_title', { name: u.username })}
                description={t('admin.confirm_disable_2fa_req_desc')}
                okText={t('admin.action_disable_2fa_req')}
                okButtonProps={{ danger: true, loading: disable2faReqMut.isPending }}
                cancelText={t('common.cancel')}
                onConfirm={() => disable2faReqMut.mutate(u.id)}
              >
                <Tooltip title={t('admin.action_disable_2fa_req')}>
                  <Button aria-label={t('admin.action_disable_2fa_req')} size="small" icon={<UnlockOutlined />} />
                </Tooltip>
              </Popconfirm>
            ) : (
              <Popconfirm
                title={t('admin.confirm_enable_2fa_req_title', { name: u.username })}
                description={t('admin.confirm_enable_2fa_req_desc')}
                okText={t('admin.action_enable_2fa_req')}
                okButtonProps={{ loading: enable2faReqMut.isPending }}
                cancelText={t('common.cancel')}
                onConfirm={() => enable2faReqMut.mutate(u.id)}
              >
                <Tooltip title={t('admin.action_enable_2fa_req')}>
                  <Button aria-label={t('admin.action_enable_2fa_req')} size="small" icon={<LockOutlined />} />
                </Tooltip>
              </Popconfirm>
            )}
            {hasAnyReq && !has2faReq && (
              <Popconfirm
                title={t('admin.confirm_clear_req_title', { name: u.username })}
                description={t('admin.confirm_clear_req_desc')}
                okText={t('admin.action_clear_req')}
                okButtonProps={{ danger: true, loading: clearReqActionsMut.isPending }}
                cancelText={t('common.cancel')}
                onConfirm={() => clearReqActionsMut.mutate(u.id)}
              >
                <Tooltip title={t('admin.action_clear_req')}>
                  <Button aria-label={t('admin.action_clear_req')} size="small" icon={<UnlockOutlined />} />
                </Tooltip>
              </Popconfirm>
            )}
            <Popconfirm
              title={t('admin.confirm_delete', { name: u.username })}
              okText={t('common.delete')} okButtonProps={{ danger: true }}
              disabled={me?.user_id === u.id}
              onConfirm={() => deleteMut.mutate(u.id)}
            >
              <Tooltip title={me?.user_id === u.id ? t('admin.tooltip_self_delete') : t('admin.action_delete')}>
                <Button aria-label={me?.user_id === u.id ? t('admin.tooltip_self_delete') : t('admin.action_delete')} size="small" danger icon={<DeleteOutlined />} disabled={me?.user_id === u.id} />
              </Tooltip>
            </Popconfirm>
          </Space>
        )
      },
    },
  ]

  return (
    <>
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}>
        <span style={{ color: '#8c8c8c' }}>
          {t('admin.tenant_label')}: <Tag>{me?.tenant}</Tag>
          {t('admin.users_count', { count: users.length })}
        </span>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>{t('admin.new_user')}</Button>
      </Space>

      {isLoading ? (
        <Skeleton active paragraph={{ rows: 5 }} />
      ) : (
        <Table dataSource={users} columns={columns} rowKey="id" size="small" />
      )}

      <Modal
        title={editing ? t('admin.modal_edit_user', { name: editing.username }) : t('admin.modal_new_user')}
        open={creating || !!editing}
        onOk={submit}
        confirmLoading={createMut.isPending || updateMut.isPending}
        onCancel={() => { setCreating(false); setEditing(null); form.resetFields() }}
      >
        <Form form={form} layout="vertical">
          {!editing && (
            <Form.Item name="username" label={t('admin.field_username')} rules={[{ required: true, min: 3 }]}>
              <Input autoComplete="off" />
            </Form.Item>
          )}
          <Form.Item name="email" label={t('admin.field_email')} rules={[{ required: true, type: 'email' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="first_name" label={t('admin.field_first_name')}><Input /></Form.Item>
          <Form.Item name="last_name"  label={t('admin.field_last_name')}><Input /></Form.Item>
          {!editing && (
            <Form.Item name="password" label={t('admin.field_password')} rules={[{ required: true, min: 8 }]}>
              <Input.Password autoComplete="new-password" />
            </Form.Item>
          )}
          {!editing && (
            <Form.Item name="temporary_password" label={t('admin.field_temp_password')} valuePropName="checked" initialValue={true}>
              <Switch />
            </Form.Item>
          )}
          {editing && (
            <Form.Item name="enabled" label={t('admin.field_enabled')} valuePropName="checked"><Switch /></Form.Item>
          )}
          <Form.Item name="roles" label={t('admin.field_roles')} initialValue={[]}>
            <Select mode="multiple" options={roles.map((r) => ({ value: r.name, label: r.name }))} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={pwUser ? t('admin.modal_reset_pw', { name: pwUser.username }) : ''}
        open={!!pwUser}
        onOk={submitPassword}
        confirmLoading={pwMut.isPending}
        onCancel={() => { setPwUser(null); pwForm.resetFields() }}
      >
        <Form form={pwForm} layout="vertical" initialValues={{ temporary: true }}>
          <Form.Item name="password" label={t('admin.field_new_password')} rules={[{ required: true, min: 8 }]}>
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="temporary" label={t('admin.field_temporary')} valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

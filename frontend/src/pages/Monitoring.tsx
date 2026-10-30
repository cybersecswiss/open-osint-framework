import { useState } from 'react'
import { Table, Tag, Button, Typography, Popconfirm, message, Space, Modal, Form, Input, Select } from 'antd'
import { DeleteOutlined, SettingOutlined, PlusOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { monitoringApi, casesApi } from '../api/client'
import MonitoringQuickCreate from '../components/monitoring/MonitoringQuickCreate'
import { formatDateTime } from '../utils/datetime'

export default function Monitoring() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const qc = useQueryClient()
  // The free-form "new monitoring" flow: pick a case, paste an entity
  // ID (UUID), then the QuickCreate modal handles the rest. Mostly a
  // fallback — the natural entry point is the graph context-menu.
  const [picker, setPicker] = useState<{ caseId: string; entityId: string } | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [pickerForm] = Form.useForm()
  const { data: cases = [] } = useQuery({ queryKey: ['cases'], queryFn: casesApi.list })
  const { data: configs = [], isLoading } = useQuery({
    queryKey: ['monitoring'],
    queryFn: monitoringApi.list,
  })

  const remove = useMutation({
    mutationFn: monitoringApi.delete,
    onSuccess: () => {
      message.success(t('monitoring.msg_deleted'))
      qc.invalidateQueries({ queryKey: ['monitoring'] })
    },
    onError: (e: any) =>
      message.error(e?.response?.data?.detail || t('monitoring.msg_delete_failed')),
  })

  const columns = [
    { title: t('monitoring.col_entity'), dataIndex: 'entity_id', key: 'entity' },
    {
      title: t('monitoring.col_interval'),
      dataIndex: 'interval_hours',
      render: (h: number) => `${h}h`,
    },
    {
      title: t('monitoring.col_status'),
      dataIndex: 'is_active',
      render: (v: boolean) => (
        <Tag color={v ? 'green' : 'default'}>{v ? t('admin.enabled_yes') : t('admin.enabled_no')}</Tag>
      ),
    },
    {
      title: t('monitoring.next_scan'),
      dataIndex: 'next_scan',
      render: (v: string) => formatDateTime(v),
    },
    {
      title: t('monitoring.col_actions'),
      key: 'actions',
      width: 120,
      align: 'right' as const,
      onCell: () => ({ onClick: (e: any) => e.stopPropagation() }),
      render: (_: any, row: any) => (
        <span>
          <Button
            size="small"
            icon={<SettingOutlined />}
            style={{ marginRight: 6 }}
            onClick={() => navigate(`/monitoring/${row.id}`)}
          >
            {t('monitoring.action_configure')}
          </Button>
          <Popconfirm
            title={t('monitoring.confirm_delete_title')}
            description={t('monitoring.confirm_delete_desc')}
            okText={t('common.delete')}
            okButtonProps={{ danger: true, loading: remove.isPending }}
            cancelText={t('common.cancel')}
            onConfirm={() => remove.mutate(row.id)}
          >
            <Button aria-label={t('a11y.delete_monitor')} danger icon={<DeleteOutlined />} size="small" />
          </Popconfirm>
        </span>
      ),
    },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}>
        <Typography.Title level={3} style={{ margin: 0 }}>{t('monitoring.title')}</Typography.Title>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => { pickerForm.resetFields(); setPickerOpen(true) }}
        >
          {t('monitoring.action_new')}
        </Button>
      </Space>
      <Table
        dataSource={configs}
        columns={columns}
        rowKey="id"
        loading={isLoading}
        onRow={(row: any) => ({
          onClick: () => navigate(`/monitoring/${row.id}`),
          style: { cursor: 'pointer' },
        })}
      />

      {/* Step 1 of "New monitoring": pick which case + which entity. */}
      <Modal
        title={t('monitoring.new_picker_title')}
        open={pickerOpen}
        onCancel={() => setPickerOpen(false)}
        onOk={() => pickerForm.validateFields().then((v) => {
          setPicker({ caseId: v.case_id, entityId: v.entity_id })
          setPickerOpen(false)
        })}
        okText={t('common.ok')}
        cancelText={t('common.cancel')}
      >
        <p style={{ marginTop: 0 }} className="ant-typography ant-typography-secondary">
          {t('monitoring.new_picker_help')}
        </p>
        <Form form={pickerForm} layout="vertical">
          <Form.Item name="case_id" label={t('search.case_label')} rules={[{ required: true }]}>
            <Select
              placeholder={t('search.case_placeholder')}
              options={cases.map((c: any) => ({
                value: c.id, label: `${c.case_number} — ${c.title}`,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="entity_id"
            label={t('monitoring.new_picker_entity_id_label')}
            rules={[
              { required: true },
              { pattern: /^[0-9a-fA-F-]{36}$/, message: t('monitoring.new_picker_uuid_invalid') },
            ]}
          >
            <Input placeholder="00000000-0000-0000-0000-000000000000" />
          </Form.Item>
        </Form>
      </Modal>

      {/* Step 2: same modal as the graph context-menu uses. */}
      {picker && (
        <MonitoringQuickCreate
          open
          onCancel={() => setPicker(null)}
          caseId={picker.caseId}
          entityId={picker.entityId}
        />
      )}
    </div>
  )
}

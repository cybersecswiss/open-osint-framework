import { useEffect, useState } from 'react'
import {
  Card, Form, Input, InputNumber, Button, Upload, Avatar, Space, message,
  Spin, Alert, Typography, Select, Switch,
} from 'antd'
import { UploadOutlined, DeleteOutlined, SaveOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { searchApi, tenantApi, TenantSettings as TenantSettingsT } from '../../api/client'
import type { UploadFile, RcFile } from 'antd/es/upload/interface'

// Soft-cap on the client side too — no point sending a 5 MB image just
// to get a 413 back from the backend. Mirrors license-server's limit.
const MAX_LOGO_KB_RAW = 150

function fileToBase64(file: RcFile): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

export default function TenantSettings() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [form] = Form.useForm()
  const [logoB64, setLogoB64] = useState<string | null>(null)

  // Same cache key as AppLayout.tsx (header) and MonitoringDetail.tsx
  // — when the user saves here, invalidating this key refreshes the
  // header logo/name and any open monitoring forms in the same tab
  // without needing a browser reload.
  const { data: settings, isLoading } = useQuery({
    queryKey: ['tenant-settings'],
    queryFn: tenantApi.getSettings,
  })
  // Every playbook, independent of a selector type — the default applies to
  // whatever the investigator types, and the form greys it out where it
  // does not fit.
  const { data: playbookData } = useQuery({
    queryKey: ['playbooks', 'all'],
    queryFn: () => searchApi.playbooks(),
  })

  useEffect(() => {
    if (settings) {
      form.setFieldsValue({
        display_name: settings.display_name,
        default_alert_email: settings.default_alert_email,
        session_timeout_minutes: settings.session_timeout_minutes,
        auto_delete_months: settings.auto_delete_months,
        default_language: settings.default_language ?? null,
        require_search_purpose: !!settings.require_search_purpose,
        default_playbook: settings.default_playbook ?? null,
        report_classification: settings.report_classification ?? '',
        disabled_modules: settings.disabled_modules || [],
      })
      setLogoB64(settings.logo_b64 || null)
    }
  }, [settings, form])

  const updateMut = useMutation({
    mutationFn: (data: Partial<TenantSettingsT>) => tenantApi.updateSettings(data),
    onSuccess: (resp: any) => {
      // Honest message: if session-timeout was in the payload but the
      // KC sync failed (e.g. service-account missing manage-realm),
      // surface that warning instead of the cheerful "saved".
      if (resp?.realm_session_timeout_synced === false) {
        message.warning(t('admin.settings_saved_kc_sync_failed'))
      } else {
        message.success(t('admin.settings_saved'))
      }
      // One cache key shared with AppLayout.tsx (header) and
      // MonitoringDetail.tsx — invalidating it triggers an immediate
      // refetch in those components, so the header logo + display name
      // (and any open monitoring forms) update without a page reload.
      qc.invalidateQueries({ queryKey: ['tenant-settings'] })
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || t('admin.settings_save_failed')),
  })

  const onSave = async () => {
    const values = await form.validateFields()
    // A cleared Select yields undefined, which JSON drops — and a dropped
    // field means "leave as is" on the server. null means "follow the browser".
    updateMut.mutate({
      ...values,
      default_language: values.default_language ?? null,
      default_playbook: values.default_playbook ?? null,
      report_classification: (values.report_classification || '').trim() || null,
      disabled_modules: values.disabled_modules || [],
      logo_b64: logoB64,
    })
  }

  const beforeUpload = async (file: RcFile) => {
    if (file.size > MAX_LOGO_KB_RAW * 1024) {
      message.error(t('admin.settings_logo_too_large', { kb: MAX_LOGO_KB_RAW }))
      return Upload.LIST_IGNORE
    }
    if (!file.type.startsWith('image/')) {
      message.error(t('admin.settings_logo_not_image'))
      return Upload.LIST_IGNORE
    }
    const b64 = await fileToBase64(file)
    setLogoB64(b64)
    return Upload.LIST_IGNORE  // we don't actually upload — Save does that
  }

  if (isLoading) return <Spin />

  return (
    <Card style={{ maxWidth: 720 }}>
      <Form form={form} layout="vertical" onFinish={onSave}>
        <Form.Item label={t('admin.settings_logo_label')}>
          <Space size="large" align="start">
            {logoB64 ? (
              <Avatar src={logoB64} shape="square" size={80} />
            ) : (
              <Avatar shape="square" size={80} style={{ background: '#f0f0f0', color: '#999' }}>
                {t('admin.settings_logo_placeholder')}
              </Avatar>
            )}
            <Space direction="vertical">
              <Upload accept="image/*" beforeUpload={beforeUpload} showUploadList={false}>
                <Button icon={<UploadOutlined />}>{t('admin.settings_logo_upload')}</Button>
              </Upload>
              {logoB64 && (
                <Button icon={<DeleteOutlined />} size="small" danger onClick={() => setLogoB64(null)}>
                  {t('admin.settings_logo_remove')}
                </Button>
              )}
              <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                {t('admin.settings_logo_hint', { kb: MAX_LOGO_KB_RAW })}
              </Typography.Text>
            </Space>
          </Space>
        </Form.Item>

        <Form.Item
          name="display_name"
          label={t('admin.settings_display_name')}
          help={t('admin.settings_display_name_help')}
        >
          <Input placeholder="z.B. Muster-Behörde" allowClear />
        </Form.Item>

        <Form.Item
          name="default_alert_email"
          label={t('admin.settings_default_alert_email')}
          help={t('admin.settings_default_alert_email_help')}
          rules={[{ type: 'email', message: t('search.email_invalid') }]}
        >
          <Input placeholder="alerts@behoerde.example" allowClear />
        </Form.Item>

        <Form.Item
          name="session_timeout_minutes"
          label={t('admin.settings_session_timeout')}
          help={t('admin.settings_session_timeout_help')}
        >
          <InputNumber min={5} max={480} style={{ width: 160 }} addonAfter={t('admin.settings_unit_minutes')} />
        </Form.Item>

        <Form.Item
          name="auto_delete_months"
          label={t('admin.settings_auto_delete')}
          help={t('admin.settings_auto_delete_help')}
        >
          <InputNumber min={1} max={120} style={{ width: 160 }} addonAfter={t('admin.settings_unit_months')} />
        </Form.Item>

        <Form.Item
          name="default_language"
          label={t('admin.settings_default_language')}
          help={t('admin.settings_default_language_help')}
        >
          <Select
            style={{ width: 220 }}
            allowClear
            placeholder={t('admin.settings_default_language_browser')}
            options={[
              { value: 'de', label: 'Deutsch' },
              { value: 'fr', label: 'Français' },
              { value: 'it', label: 'Italiano' },
              { value: 'en', label: 'English' },
            ]}
          />
        </Form.Item>

        <Form.Item
          name="report_classification"
          label={t('admin.settings_classification')}
          help={t('admin.settings_classification_help')}
          rules={[{ pattern: /^[^"\\\r\n]*$/, message: t('admin.settings_classification_invalid') }]}
        >
          <Input maxLength={80} placeholder={t('admin.settings_classification_placeholder')} style={{ maxWidth: 420 }} />
        </Form.Item>

        <Form.Item
          name="default_playbook"
          label={t('admin.settings_default_playbook')}
          help={t('admin.settings_default_playbook_help')}
        >
          <Select
            allowClear
            style={{ maxWidth: 420 }}
            placeholder={t('admin.settings_default_playbook_none')}
            options={(playbookData?.playbooks || []).map((pb: any) => ({
              value: pb.key, label: t(`search.pb_${pb.key}`, { defaultValue: pb.key }),
            }))}
          />
        </Form.Item>

        <Form.Item
          name="disabled_modules"
          label={t('admin.settings_disabled_modules')}
          help={t('admin.settings_disabled_modules_help')}
        >
          <Select
            mode="multiple"
            allowClear
            style={{ maxWidth: 620 }}
            placeholder={t('admin.settings_disabled_modules_none')}
            options={(settings?.licensed_modules || []).map((m) => ({
              value: m, label: t(`search.module_${m}`, { defaultValue: m }),
            }))}
          />
        </Form.Item>

        <Form.Item
          name="require_search_purpose"
          label={t('admin.settings_require_purpose')}
          help={t('admin.settings_require_purpose_help')}
          valuePropName="checked"
        >
          <Switch />
        </Form.Item>

        <Form.Item style={{ marginBottom: 0 }}>
          <Button type="primary" icon={<SaveOutlined />} htmlType="submit" loading={updateMut.isPending}>
            {t('common.save')}
          </Button>
        </Form.Item>
      </Form>
    </Card>
  )
}

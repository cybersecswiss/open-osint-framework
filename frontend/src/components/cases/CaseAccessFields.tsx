import { AutoComplete, Form, Select, Switch } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { casesApi } from '../../api/client'

/**
 * Who works on a case, and who may see it (need-to-know).
 *
 * The name list comes from the tenant's IdP where this framework can read it,
 * and otherwise from names already used here. Names can always be typed: a
 * colleague who has never logged in must be addable before their first case.
 *
 * `canManage` is false for anyone but the creator or an admin — the server
 * refuses the change anyway (403); disabling the fields says so up front.
 */
export function useAssignableUsers() {
  const q = useQuery({
    queryKey: ['assignable-users'],
    queryFn: casesApi.assignableUsers,
    staleTime: 5 * 60 * 1000,
  })
  return (q.data?.users || []).map((u) => ({ value: u, label: u }))
}

export default function CaseAccessFields({ canManage = true, withAssignee = false }: {
  canManage?: boolean
  withAssignee?: boolean
}) {
  const { t } = useTranslation()
  const options = useAssignableUsers()
  const restricted = Form.useWatch('restricted')

  return (
    <>
      {withAssignee && (
        <Form.Item name="assigned_to" label={t('case_detail.field_assigned_to')}>
          <AutoComplete
            options={options}
            allowClear
            placeholder={t('case_detail.field_assigned_placeholder')}
            filterOption={(input, opt) => (opt?.value as string).toLowerCase().includes(input.toLowerCase())}
          />
        </Form.Item>
      )}
      <Form.Item
        name="restricted"
        label={t('case_access.restricted_label')}
        valuePropName="checked"
        extra={restricted ? t('case_access.restricted_on_hint') : t('case_access.restricted_off_hint')}
      >
        <Switch disabled={!canManage} />
      </Form.Item>
      {restricted && (
        <Form.Item
          name="members"
          label={t('case_access.members_label')}
          extra={canManage ? t('case_access.members_hint') : t('case_access.members_locked')}
        >
          <Select
            mode="tags"
            disabled={!canManage}
            options={options}
            placeholder={t('case_access.members_placeholder')}
            tokenSeparators={[',', ' ']}
          />
        </Form.Item>
      )}
    </>
  )
}

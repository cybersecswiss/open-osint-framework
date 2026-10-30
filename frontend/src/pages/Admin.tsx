import { Card, Descriptions, Tabs, Typography, Alert, Tag, Space } from 'antd'
import { useTranslation } from 'react-i18next'
import { useStore } from '../store/useStore'
import UserManagement from '../components/admin/UserManagement'
import LicenseInfo from '../components/admin/LicenseInfo'
import TenantSettings from '../components/admin/TenantSettings'
import NotificationSettings from '../components/admin/NotificationSettings'
import SupportTickets from '../components/admin/SupportTickets'
import AuditLog from '../components/admin/AuditLog'
import SelfTest from '../components/admin/SelfTest'
import UpdateBanner from '../components/admin/UpdateBanner'
import ChangelogView from '../components/changelog/ChangelogView'

export default function Admin() {
  const { t } = useTranslation()
  const { user } = useStore()
  const isAdmin = user?.roles.includes('admin')

  return (
    <div>
      <Space align="baseline" style={{ marginBottom: 4 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>{t('admin.title')}</Typography.Title>
        <Tag color="blue">{user?.tenant}</Tag>
      </Space>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
        {t('admin.subtitle')}
      </Typography.Paragraph>
      {isAdmin && <UpdateBanner />}

      <Tabs
        items={[
          {
            key: 'users',
            label: t('admin.tab_users'),
            children: isAdmin ? (
              <>
                <Alert
                  type="info"
                  showIcon
                  message={t('admin.banner_message')}
                  description={t('admin.banner_description')}
                  style={{ marginBottom: 16 }}
                />
                <UserManagement />
              </>
            ) : (
              <Alert
                type="warning"
                showIcon
                message={t('admin.no_admin_message')}
                description={t('admin.no_admin_description')}
              />
            ),
          },
          ...(isAdmin ? [
            {
              key: 'selftest',
              label: t('selftest.tab'),
              children: <SelfTest />,
            },
            {
              key: 'changelog',
              label: t('changelog.tab'),
              children: <ChangelogView compact />,
            },
            {
              key: 'license',
              label: t('admin.tab_license'),
              children: <LicenseInfo />,
            },
            {
              key: 'settings',
              label: t('admin.tab_settings'),
              children: <TenantSettings />,
            },
            {
              // Its own tab rather than a block inside Settings: this is
              // where a mail server password is entered, and burying that
              // under branding and retention makes it hard to find and
              // easy to change by accident.
              key: 'notifications',
              label: t('admin.tab_notifications'),
              children: <NotificationSettings />,
            },
            {
              key: 'audit',
              label: t('audit.tab'),
              children: <AuditLog />,
            },
          ] : []),
          {
            key: 'support',
            label: t('support.tab'),
            children: <SupportTickets />,
          },
          {
            key: 'session',
            label: t('admin.tab_session'),
            children: (
              <Card style={{ maxWidth: 600 }}>
                <Descriptions column={1} bordered size="small">
                  <Descriptions.Item label={t('admin.session_user')}>{user?.username}</Descriptions.Item>
                  <Descriptions.Item label={t('admin.session_email')}>{user?.email || '—'}</Descriptions.Item>
                  <Descriptions.Item label={t('admin.session_tenant')}><Tag color="blue">{user?.tenant}</Tag></Descriptions.Item>
                  <Descriptions.Item label={t('admin.session_roles')}>
                    {user?.roles.map((r) => (
                      <Tag key={r} color={r === 'admin' ? 'gold' : 'blue'}>{r}</Tag>
                    ))}
                  </Descriptions.Item>
                  <Descriptions.Item label={t('admin.session_user_id')}>
                    <Typography.Text code copyable>{user?.user_id}</Typography.Text>
                  </Descriptions.Item>
                </Descriptions>
              </Card>
            ),
          },
        ]}
      />
    </div>
  )
}

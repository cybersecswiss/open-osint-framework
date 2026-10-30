import { Layout, Menu, Button, Space, Typography, Tag, Select, Spin, theme } from 'antd'
import {
  DashboardOutlined, BankOutlined, TeamOutlined, LogoutOutlined, SafetyCertificateOutlined, MessageOutlined, SettingOutlined,
} from '@ant-design/icons'
import { Suspense } from 'react'
import ThemeToggle from '../components/layout/ThemeToggle'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useStore } from '../store/useStore'
import { platformLogout } from '../auth/platformKeycloak'
import i18n from '../i18n'
import ErrorBoundary from '../components/ErrorBoundary'

const { Sider, Header, Content } = Layout

const LANGS = [
  { value: 'en', label: 'EN' }, { value: 'de', label: 'DE' },
  { value: 'fr', label: 'FR' }, { value: 'it', label: 'IT' },
]

// Standalone Product-Owner console shell — deliberately distinct from the
// tenant AppLayout (dark rail, operator header) so operators never
// mistake it for the authority-facing app.
export default function GlobalAdminLayout() {
  const { t } = useTranslation()
  const { token } = theme.useToken()
  const navigate = useNavigate()
  const location = useLocation()
  const { user, lang, setLang } = useStore()

  const items = [
    { key: '/glbadmin', icon: <DashboardOutlined />, label: t('glbadmin.nav_overview') },
    { key: '/glbadmin/authorities', icon: <BankOutlined />, label: t('glbadmin.nav_authorities') },
    { key: '/glbadmin/support', icon: <MessageOutlined />, label: t('support.console_title') },
    { key: '/glbadmin/operators', icon: <TeamOutlined />, label: t('glbadmin.nav_operators') },
    { key: '/glbadmin/settings', icon: <SettingOutlined />, label: t('glbadmin.settings.nav') },
    { key: '/glbadmin/audit', icon: <SafetyCertificateOutlined />, label: t('glbadmin.audit.nav') },
  ]
  // exact-match the index route, prefix-match the others
  const selected = location.pathname === '/glbadmin'
    ? '/glbadmin'
    : items.slice(1).find((i) => location.pathname.startsWith(i.key))?.key || '/glbadmin'

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider width={230} theme="dark" breakpoint="lg" collapsedWidth={0}
        style={{ background: '#0b1f3a' }}>
        <div style={{
          padding: '18px 16px', color: '#fff', display: 'flex', alignItems: 'center',
          gap: 10, borderBottom: '1px solid rgba(255,255,255,.12)', minHeight: 64,
        }}>
          <SafetyCertificateOutlined style={{ fontSize: 24, color: '#4c9aff' }} />
          <div style={{ lineHeight: 1.15 }}>
            <div style={{ fontWeight: 700, fontSize: 14 }}>{t('glbadmin.console_title')}</div>
            <div style={{ fontSize: 10, opacity: 0.7 }}>OOF</div>
          </div>
        </div>
        <Menu theme="dark" mode="inline" selectedKeys={[selected]} items={items}
          onClick={({ key }) => navigate(key)}
          style={{ background: 'transparent', borderRight: 0, marginTop: 8 }} />
      </Sider>
      <Layout>
        <Header style={{
          background: '#11294d', display: 'flex', alignItems: 'center',
          justifyContent: 'space-between', padding: '0 24px',
        }}>
          <Space>
            <Typography.Text style={{ color: '#fff', fontWeight: 600 }}>{user?.username}</Typography.Text>
            <Tag color="gold" style={{ margin: 0 }}>product owner</Tag>
          </Space>
          <Space>
            <Select aria-label={t('a11y.language')} value={lang} options={LANGS} size="small" style={{ width: 70 }}
              onChange={(v) => { setLang(v); i18n.changeLanguage(v) }} />
            <ThemeToggle dark />
            <Button icon={<LogoutOutlined />} type="text" style={{ color: '#fff' }}
                    aria-label={t('nav.logout')} title={t('nav.logout')}
              onClick={platformLogout} />
          </Space>
        </Header>
        <Content id="main-content" tabIndex={-1} style={{ margin: 24, background: token.colorBgContainer, padding: 24, borderRadius: 8 }}>
          {/* One broken page must not take the navigation with it. */}
          <ErrorBoundary resetKey={location.pathname}>
            {/* Pages are lazy chunks (see router.tsx). The layout stays on
                screen while one downloads, so navigation never looks frozen. */}
            <Suspense fallback={
              <div style={{ textAlign: 'center', padding: 64 }} role="status" aria-live="polite">
                <Spin size="large" />
              </div>
            }>
              <Outlet />
            </Suspense>
          </ErrorBoundary>
        </Content>
      </Layout>
    </Layout>
  )
}

import { Layout, Menu, Select, Button, Space, Typography, Tag, Tooltip, Avatar, Spin, theme } from 'antd'
import {
  DashboardOutlined,
  FolderOutlined,
  SearchOutlined,
  BellOutlined,
  EyeOutlined,
  SettingOutlined,
  LogoutOutlined,
  MenuOutlined,
  ReadOutlined,
  GlobalOutlined, CompassOutlined } from '@ant-design/icons'
import { useState, useEffect, Suspense } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { useStore } from '../../store/useStore'
import { logout } from '../../auth/keycloak'
import { tenantApi } from '../../api/client'
import i18n from '../../i18n'
import ErrorBoundary from '../ErrorBoundary'
import ThemeToggle from './ThemeToggle'
import { tenantLangOverride } from '../../utils/language'
import { useUpdateStatus } from '../admin/UpdateBanner'
import KeyboardShortcuts from './KeyboardShortcuts'

const { Sider, Header, Content } = Layout

const LANGS = [
  { value: 'de', label: 'DE' },
  { value: 'fr', label: 'FR' },
  { value: 'it', label: 'IT' },
  { value: 'en', label: 'EN' },
]

export default function AppLayout() {
  const { t } = useTranslation()
  const { token } = theme.useToken()
  const navigate = useNavigate()
  const location = useLocation()
  const { user, lang, setLang, applyLang } = useStore()
  // Sider auto-collapses below the `lg` breakpoint; the header hamburger
  // lets the user toggle it back so the nav is never stranded off-screen.
  const [collapsed, setCollapsed] = useState(false)
  // Framework operator: no tenant, no tenant data. Gets a
  // separate single-item nav and is kept on /glbadmin.
  const isPlatform = !!user?.roles.includes('platform_admin')

  // Tenant branding (logo + display name) — loaded once when the user
  // is authenticated, cached for the whole session. Falls back to the
  // raw tenant slug if nothing is configured yet. Skipped for platform
  // admins (they have no tenant; the call would 403).
  const { data: tenantSettings } = useQuery({
    queryKey: ['tenant-settings'],
    queryFn: tenantApi.getSettings,
    enabled: !!user && !isPlatform,
    staleTime: 5 * 60 * 1000,  // 5 min — settings don't change often
  })
  // Admins only: the one person who can run update.sh on the agent server.
  const { data: updateStatus } = useUpdateStatus(!!user?.roles.includes('admin') && !isPlatform)
  const displayName = isPlatform
    ? 'Global Admin'
    : (tenantSettings?.display_name || user?.tenant || '')
  const logoB64 = isPlatform ? null : (tenantSettings?.logo_b64 || null)

  // Tenant default language — applies to users who have not picked one
  // themselves (see utils/language.ts for the full precedence).
  useEffect(() => {
    const next = tenantLangOverride(tenantSettings?.default_language, lang)
    if (next) {
      applyLang(next)
      i18n.changeLanguage(next)
    }
  }, [tenantSettings?.default_language, lang, applyLang])

  // Operators only ever see /glbadmin — bounce them off any tenant route
  // (defence-in-depth; the backend already 403s tenant endpoints).
  useEffect(() => {
    if (isPlatform && location.pathname !== '/glbadmin') {
      navigate('/glbadmin', { replace: true })
    }
  }, [isPlatform, location.pathname, navigate])

  const menuItems = isPlatform
    ? [
        { key: '/glbadmin', icon: <GlobalOutlined />, label: t('nav.glbadmin') },
      ]
    : [
        { key: '/', icon: <DashboardOutlined />, label: t('nav.dashboard') },
        { key: '/cases', icon: <FolderOutlined />, label: t('nav.cases') },
        { key: '/lagebild', icon: <CompassOutlined />, label: t('nav.lagebild') },
        { key: '/news', icon: <ReadOutlined />, label: t('nav.news') },
        { key: '/search', icon: <SearchOutlined />, label: t('nav.search') },
        { key: '/alerts', icon: <BellOutlined />, label: t('nav.alerts') },
        { key: '/monitoring', icon: <EyeOutlined />, label: t('nav.monitoring') },
        { key: '/admin', icon: <SettingOutlined />, label: t('nav.admin') },
        { key: '/handbook', icon: <ReadOutlined />, label: t('nav.handbook') },
      ]

  return (
    <Layout style={{ minHeight: '100vh', background: token.colorBgLayout }}>
      {/* Skip link: without it, keyboard users traverse the whole navigation
          on every page change before reaching the content. WCAG 2.1 2.4.1.
          Visually hidden until focused. */}
      <a href="#main-content" className="skip-link">{t('nav.skip_to_content')}</a>
      {/* `?` shows the list; nothing fires while a field has focus. */}
      <KeyboardShortcuts />
      <Sider
        width={220}
        theme="light"
        breakpoint="lg"
        collapsedWidth={0}
        collapsed={collapsed}
        trigger={null}
        onBreakpoint={(broken) => setCollapsed(broken)}
        style={{ borderRight: '1px solid #f0f0f0' }}
      >
        <div style={{
          padding: '16px', borderBottom: '1px solid #f0f0f0',
          display: 'flex', alignItems: 'center', gap: 10, minHeight: 60,
        }}>
          {logoB64 && (
            <Avatar src={logoB64} shape="square" size={36} />
          )}
          <div style={{ lineHeight: 1.2 }}>
            <div style={{ fontWeight: 600, fontSize: 14, color: token.colorPrimary }}>
              {displayName ? displayName : 'OOF'}
            </div>
            {displayName && (
              <div style={{ fontSize: 10, color: token.colorTextTertiary }}>OOF</div>
            )}
          </div>
        </div>
        <Menu
          theme="light"
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ borderRight: 0 }}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: token.colorBgContainer,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0 24px',
            borderBottom: '1px solid #f0f0f0',
          }}
        >
          <Space size="small">
            <Button
              icon={<MenuOutlined />}
              type="text"
              onClick={() => setCollapsed((c) => !c)}
              aria-label="toggle navigation"
            />
            <Typography.Text strong>{user?.username}</Typography.Text>
            {isPlatform ? (
              <Tag color="gold" style={{ margin: 0 }}>platform_admin</Tag>
            ) : (
              <>
                <Tooltip
                  title={
                    tenantSettings?.display_name
                      ? `${t('header.tenant_tooltip')} — ${user?.tenant}`
                      : t('header.tenant_tooltip')
                  }
                >
                  <Tag color="blue" style={{ margin: 0 }}>
                    {tenantSettings?.display_name || user?.tenant}
                  </Tag>
                </Tooltip>
                {user?.roles.includes('admin') && <Tag color="gold" style={{ margin: 0 }}>admin</Tag>}
                {updateStatus?.state === 'outdated' && (
                  <Tooltip title={t('update.header_tooltip', { latest: updateStatus.latest || '' })}>
                    <Tag color="blue" style={{ margin: 0, cursor: 'pointer' }} onClick={() => navigate('/admin')}>
                      {t('update.header_tag')}
                    </Tag>
                  </Tooltip>
                )}
              </>
            )}
          </Space>
          <Space>
            <Select aria-label={t('a11y.language')}
              value={lang}
              options={LANGS}
              onChange={(v) => {
                setLang(v)
                i18n.changeLanguage(v)
              }}
              style={{ width: 70 }}
              size="small"
            />
            <ThemeToggle />
            <Button icon={<LogoutOutlined />} type="text" onClick={logout}
                    aria-label={t('nav.logout')} title={t('nav.logout')} />
          </Space>
        </Header>
        <Content
          id="main-content"
          tabIndex={-1}
          style={{
            margin: '24px',
            background: token.colorBgContainer,
            padding: '24px',
            borderRadius: 8,
            border: `1px solid ${token.colorBorderSecondary}`,
          }}
        >
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

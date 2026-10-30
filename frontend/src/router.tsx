import { lazy } from 'react'
import { createBrowserRouter } from 'react-router-dom'
import AppLayout from './components/layout/AppLayout'
import GlobalAdminLayout from './layouts/GlobalAdminLayout'

/**
 * Every page is a separate chunk.
 *
 * ## Why
 *
 * Without code splitting the build was **one `index.js` of 3.1 MB**,
 * because every page was a static import. That meant an investigator opening
 * the dashboard downloaded, before seeing anything:
 *
 *   * the whole Product-Owner console (`/glbadmin`) — which they are not
 *     even permitted to open,
 *   * Cytoscape + fcose, used only inside a case's graph tab,
 *   * Leaflet, used only by the map tab,
 *   * the report view and the in-app handbook.
 *
 * On a locked-down workstation over a VPN that is the single most noticeable
 * property of the frontend, and none of it was needed to render the first
 * screen.
 *
 * ## The shape chosen, and why not the other one
 *
 * React Router 6.4+ also offers a per-route `lazy` property. It is tidier to
 * write, but it delays the *navigation* while the chunk downloads: the user
 * clicks and nothing happens, with no way to say "loading". `React.lazy`
 * plus a `<Suspense>` boundary inside each layout keeps the navigation
 * instant and puts a spinner in the content area — the layout, menu and
 * header stay on screen, so the app never looks like it froze.
 *
 * Both layouts are imported eagerly on purpose: they ARE the first screen,
 * and lazy-loading them would trade the problem for a blank flash.
 */
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Cases = lazy(() => import('./pages/Cases'))
const Alerts = lazy(() => import('./pages/Alerts'))
const CaseDetail = lazy(() => import('./pages/CaseDetail'))
const CaseReport = lazy(() => import('./pages/CaseReport'))
const Search = lazy(() => import('./pages/Search'))
const SearchProgress = lazy(() => import('./pages/SearchProgress'))
const Lagebild = lazy(() => import('./pages/Lagebild'))
const News = lazy(() => import('./pages/News'))
const Monitoring = lazy(() => import('./pages/Monitoring'))
const MonitoringDetail = lazy(() => import('./pages/MonitoringDetail'))
const Admin = lazy(() => import('./pages/Admin'))
const Handbook = lazy(() => import('./pages/Handbook'))

// Standalone Product-Owner console (separate layout + auth).
const Overview = lazy(() => import('./pages/platform/Overview'))
const Authorities = lazy(() => import('./pages/platform/Authorities'))
const ProductOwners = lazy(() => import('./pages/platform/ProductOwners'))
const Support = lazy(() => import('./pages/platform/Support'))
const Settings = lazy(() => import('./pages/platform/Settings'))
const PlatformAudit = lazy(() => import('./pages/platform/Audit'))

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'cases', element: <Cases /> },
      { path: 'cases/:id', element: <CaseDetail /> },
      { path: 'cases/:id/report', element: <CaseReport /> },
      { path: 'lagebild', element: <Lagebild /> },
      { path: 'news', element: <News /> },
      { path: 'search', element: <Search /> },
      { path: 'search/:job_id', element: <SearchProgress /> },
      { path: 'alerts', element: <Alerts /> },
      { path: 'monitoring', element: <Monitoring /> },
      { path: 'monitoring/:id', element: <MonitoringDetail /> },
      { path: 'admin', element: <Admin /> },
      { path: 'handbook', element: <Handbook /> },
    ],
  },
  {
    path: '/glbadmin',
    element: <GlobalAdminLayout />,
    children: [
      { index: true, element: <Overview /> },
      { path: 'authorities', element: <Authorities /> },
      { path: 'support', element: <Support /> },
      { path: 'operators', element: <ProductOwners /> },
      { path: 'settings', element: <Settings /> },
      { path: 'audit', element: <PlatformAudit /> },
    ],
  },
])

import React, { useState } from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  initAuth, getUser, getStoredTenant, getStoredEmail, storeTenant,
  clearStoredTenant, watchSession,
} from './auth/keycloak'
import { initPlatformAuth, getPlatformUser } from './auth/platformKeycloak'
import { useStore } from './store/useStore'
import App from './App'
import EmailEntry from './auth/EmailEntry'
import LoginError, { type LoginErrorReason } from './auth/LoginError'
import './i18n'
import 'antd/dist/reset.css'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30000 } },
})

// The Product-Owner console (/glbadmin) is a standalone area
// with its OWN login against the separate `platform` Keycloak realm. No
// email→tenant routing. Everything else uses the tenant flow below.
const IS_CONSOLE = window.location.pathname.startsWith('/glbadmin')

function PlatformBootstrap() {
  const [ready, setReady] = React.useState(false)
  // Same blank-page defect as the tenant flow had, in the operator console:
  // no catch meant a Keycloak outage rendered nothing at all. There is no
  // e-mail step here, so the only action offered is a retry.
  const [failure, setFailure] = React.useState<string | null>(null)
  const [attempt, setAttempt] = React.useState(0)
  React.useEffect(() => {
    let cancelled = false
    initPlatformAuth()
      .then((ok) => {
        if (cancelled) return
        if (!ok) { setFailure('not authenticated'); return }
        useStore.getState().setUser(getPlatformUser() as any)
        setReady(true)
      })
      .catch((e: any) => {
        if (!cancelled) setFailure(e?.message || String(e))
      })
    return () => { cancelled = true }
  }, [attempt])
  if (failure) {
    return (
      <LoginError
        reason="idp"
        detail={failure}
        onRetry={() => { setFailure(null); setAttempt((n) => n + 1) }}
        onChangeEmail={() => window.location.reload()}
      />
    )
  }
  if (!ready) return null
  return (
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  )
}

/**
 * Boot flow:
 *  1. If there's a tenant in sessionStorage (from a prior EmailEntry
 *     in this session), bootstrap auth for that tenant directly.
 *  2. Otherwise, render <EmailEntry> first; on submit, store the tenant
 *     and trigger the auth bootstrap.
 *
 * The framework operator never sees passwords — keycloak-js redirects
 * directly to the customer-side IdP for the actual login.
 */
function Bootstrap() {
  const [tenant, setTenantState] = useState<string | null>(getStoredTenant())
  const [email, setEmailState] = useState<string | null>(getStoredEmail())
  const [authReady, setAuthReady] = useState(false)
  // Why this state exists: without it a failed bootstrap left `authReady`
  // false forever and the component below rendered `null` — a blank white
  // page with no message and no way out. See auth/LoginError.tsx.
  const [failure, setFailure] = useState<
    { reason: LoginErrorReason; detail?: string } | null>(null)
  const [attempt, setAttempt] = useState(0)

  // Once we have a tenant, run keycloak-js. This causes a redirect to
  // the customer IdP; on return, we land here authenticated.
  React.useEffect(() => {
    if (!tenant) return
    let cancelled = false
    initAuth(tenant, email || undefined)
      .then((ok) => {
        if (cancelled) return
        if (!ok) {
          // `login-required` normally redirects rather than returning false,
          // so this is the odd path — but "odd" is not "impossible", and it
          // used to render the blank page too.
          setFailure({ reason: 'unauthenticated' })
          return
        }
        useStore.getState().setUser(getUser() as any)
        watchSession()
        setAuthReady(true)
      })
      .catch((e: any) => {
        if (cancelled) return
        setFailure({
          reason: e?.name === 'AuthBootstrapError' ? e.reason : 'idp',
          detail: e?.message || String(e),
        })
      })
    return () => { cancelled = true }
  }, [tenant, email, attempt])

  if (!tenant) {
    return (
      <EmailEntry
        onResolve={(t, e) => {
          storeTenant(t, e)
          setTenantState(t)
          setEmailState(e)
        }}
      />
    )
  }
  if (failure) {
    return (
      <LoginError
        reason={failure.reason}
        detail={failure.detail}
        tenant={tenant}
        onRetry={() => { setFailure(null); setAttempt((n) => n + 1) }}
        onChangeEmail={() => {
          // The only escape from a wrong stored tenant — a typo that hits
          // another authority's domain otherwise loops the browser forever.
          clearStoredTenant()
          setFailure(null)
          setTenantState(null)
          setEmailState(null)
        }}
      />
    )
  }
  if (!authReady) {
    return null  // Keycloak is doing its redirect dance; nothing to render.
  }
  return (
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {IS_CONSOLE ? <PlatformBootstrap /> : <Bootstrap />}
  </React.StrictMode>
)

import Keycloak from 'keycloak-js'

import { tenantFromGroups } from './tenantFromGroups'

const TENANT_KEY = 'osint.tenant'
const EMAIL_KEY = 'osint.email'

let keycloak: Keycloak | null = null

export function getStoredTenant(): string | null {
  return sessionStorage.getItem(TENANT_KEY)
}

export function getStoredEmail(): string | null {
  return sessionStorage.getItem(EMAIL_KEY)
}

export function storeTenant(tenant: string, email: string): void {
  sessionStorage.setItem(TENANT_KEY, tenant)
  sessionStorage.setItem(EMAIL_KEY, email)
}

export function clearStoredTenant(): void {
  sessionStorage.removeItem(TENANT_KEY)
  sessionStorage.removeItem(EMAIL_KEY)
}

/** Which half of the login chain failed — decides what the user is told. */
export class AuthBootstrapError extends Error {
  constructor(public reason: 'config' | 'idp', message: string) {
    super(message)
    this.name = 'AuthBootstrapError'
  }
}

/**
 * OIDC bootstrap: ask the framework which Keycloak this
 * tenant authenticates against.
 *
 * ⚠️ **A failed lookup is NOT the same as "this tenant uses the framework
 * Keycloak", and conflating the two is a real defect.** If every error —
 * network, 5xx, malformed body — fell through to the
 * build-time defaults, i.e. the OPERATOR's Keycloak, then for a tenant with
 * its own IdP the investigator would be redirected to a login server where
 * they have no account, with no indication why. It would also cross, silently,
 * the boundary the whole sovereignty design rests on.
 *
 * The two cases are now distinct:
 *   * HTTP 200 with `url: null` → the tenant genuinely uses the framework
 *     Keycloak (the documented legacy/dev path). Fall back, as designed.
 *   * anything else → throw. The caller shows an error page with a retry.
 *
 * One retry with a short backoff first, because the common cause is a
 * transient hiccup and an error page for a 300 ms blip would be its own kind
 * of wrong.
 */
async function fetchOidcConfig(tenant: string): Promise<{ url: string; realm: string }> {
  const apiBase = (import.meta as any).env.VITE_API_URL || ''
  const url = `${apiBase}/api/v1/oidc-config/${encodeURIComponent(tenant)}`
  let lastError = 'unknown error'

  for (let attempt = 0; attempt < 2; attempt++) {
    if (attempt) await new Promise((r) => setTimeout(r, 700))
    try {
      const r = await fetch(url)
      if (!r.ok) {
        lastError = `HTTP ${r.status} from /oidc-config/${tenant}`
        continue
      }
      const body = await r.json()
      if (body.url && body.realm) return { url: body.url, realm: body.realm }
      // Explicit "use the framework Keycloak" — the designed fallback.
      return {
        url: (import.meta as any).env.VITE_KEYCLOAK_URL,
        realm: (import.meta as any).env.VITE_KEYCLOAK_REALM,
      }
    } catch (e: any) {
      lastError = e?.message || String(e)
    }
  }
  throw new AuthBootstrapError('config', lastError)
}

/**
 * Initialize Keycloak for a given tenant. Caller must have the tenant
 * already (from EmailEntry resolution or sessionStorage). Returns true
 * if the user ended up authenticated.
 */
export async function initAuth(tenant: string, loginHint?: string): Promise<boolean> {
  // Throws AuthBootstrapError('config', …) — propagated on purpose so the
  // caller can name the right side of the chain in the error page.
  const cfg = await fetchOidcConfig(tenant)

  keycloak = new Keycloak({
    url: cfg.url,
    realm: cfg.realm,
    clientId: (import.meta as any).env.VITE_KEYCLOAK_CLIENT_ID,
  })

  let authenticated: boolean
  try {
    authenticated = await keycloak.init({
      onLoad: 'login-required',
      pkceMethod: 'S256',
      checkLoginIframe: false,
      loginHint,
    } as any)
  } catch (e: any) {
    // The tenant's Keycloak is a separate system on a separate server —
    // unreachable, wrong realm, bad certificate. Distinguished from a config
    // failure so the investigator is pointed at the right helpdesk.
    throw new AuthBootstrapError('idp', e?.message || String(e))
  }

  if (authenticated) {
    keycloak.onTokenExpired = () => {
      keycloak!.updateToken(60).catch(() => keycloak!.login())
    }
  }
  return authenticated
}

export function getToken(): string {
  return keycloak?.token || ''
}

// Refresh the access token if it's about to expire, then return it. The
// api client awaits this before every request so an expired token never
// causes a spurious 401 (which the response interceptor would turn into
// a logout). If the refresh itself fails (session truly gone), we return
// the stale token and let the 401 path log the user out.
export async function ensureFreshToken(): Promise<string> {
  try {
    if (keycloak) await keycloak.updateToken(30)
  } catch {
    /* refresh failed — fall through, the 401 handler will log out */
  }
  return keycloak?.token || ''
}

export function logout(): void {
  clearStoredTenant()
  keycloak?.logout()
}

/**
 * Notice a session that was ended or revoked at the identity provider.
 *
 * `checkLoginIframe` is off (third-party-cookie breakage), so the SPA is not
 * told when a session ends at the IdP. In practice the next API call catches
 * it — the client refreshes before every request and a 401 logs the user out.
 * The gap is an IDLE tab: an investigator who leaves the case open, is
 * disabled in their authority's directory, and comes back to a UI that still
 * shows the case.
 *
 * Revalidating when the tab regains focus closes that without an iframe and
 * without polling. Deliberately silent on success and deliberately NOT
 * wired to a timer: an unattended tab that logs itself out mid-investigation
 * would be its own kind of damage.
 */
export function watchSession(): () => void {
  const onVisible = async () => {
    if (document.visibilityState !== 'visible' || !keycloak) return
    try {
      // -1 forces a refresh regardless of remaining lifetime, which is the
      // only way to learn that the SESSION (not the token) is gone.
      await keycloak.updateToken(-1)
    } catch {
      console.warn('[auth] session no longer valid at the IdP — signing out')
      logout()
    }
  }
  document.addEventListener('visibilitychange', onVisible)
  return () => document.removeEventListener('visibilitychange', onVisible)
}

export function getUser() {
  const token = keycloak?.tokenParsed as Record<string, any> | undefined
  if (!token) return null
  // Tenant comes from the JWT groups claim (set by the realm's group mapper).
  const groupTenant = tenantFromGroups(token.groups as string[])
  return {
    user_id: token.sub as string,
    username: token.preferred_username as string,
    email: token.email as string,
    roles: ((token.realm_access?.roles as string[]) || []),
    tenant: groupTenant || getStoredTenant() || 'unknown',
  }
}

export default keycloak

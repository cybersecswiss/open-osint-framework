import Keycloak from 'keycloak-js'

// SEPARATE auth for the Product-Owner console. Authenticates
// against the dedicated `platform` realm (client `platform-console`),
// fully independent of the tenant/email login flow. Only ever used under
// the /glbadmin route.
const PLATFORM_REALM = 'platform'
const PLATFORM_CLIENT = 'platform-console'

let kc: Keycloak | null = null

export async function initPlatformAuth(): Promise<boolean> {
  kc = new Keycloak({
    url: (import.meta as any).env.VITE_KEYCLOAK_URL,
    realm: PLATFORM_REALM,
    clientId: PLATFORM_CLIENT,
  })
  const authenticated = await kc.init({
    onLoad: 'login-required',
    pkceMethod: 'S256',
    checkLoginIframe: false,
  } as any)
  if (authenticated) {
    kc.onTokenExpired = () => {
      kc!.updateToken(60).catch(() => kc!.login())
    }
  }
  return authenticated
}

export function getPlatformToken(): string {
  return kc?.token || ''
}

// See ensureFreshToken in keycloak.ts — proactively refresh before use so
// the console's short-lived token doesn't 401 mid-session ("save failed").
export async function ensureFreshPlatformToken(): Promise<string> {
  try {
    if (kc) await kc.updateToken(30)
  } catch {
    /* refresh failed — 401 handler logs out */
  }
  return kc?.token || ''
}

export function platformLogout(): void {
  kc?.logout()
}

export function getPlatformUser() {
  const t = kc?.tokenParsed as Record<string, any> | undefined
  if (!t) return null
  return {
    user_id: t.sub as string,
    username: t.preferred_username as string,
    email: t.email as string,
    roles: ((t.realm_access?.roles as string[]) || []),
    tenant: null,
  }
}

/**
 * Which authority a Keycloak `groups` claim denotes.
 *
 * ⚠️ **Must stay identical to `_NON_TENANT_GROUPS` and the selection in
 * `backend/app/auth.py`.** An earlier version of the browser used
 * `!g.startsWith('admin')` and took whichever group came first. That differs
 * from the server in three ways, each of which produces a wrong answer:
 * `/investigator` and `/reader` counted as authorities, `/Admin` with a
 * capital letter counted as one, and claim order decided the result. A user
 * in `/agency-a` and `/investigator` could see "investigator" as their
 * authority in the header (`AppLayout.tsx`).
 *
 * Not a privilege issue — the backend derives the tenant from the token
 * itself and never trusts the client — but a wrong label in an evidentiary
 * product, and a trap for the first piece of UI logic that branches on it.
 *
 * **It lives in its own module for a reason.** The rule drifted from the
 * server's unnoticed because it sat inside `getUser()`, where no test could
 * reach it without dragging keycloak-js (and its dynamic `require('crypto')`)
 * into the bundle. Kept dependency-free, it is testable — see
 * `frontend/tests/auth-tenant.mjs`.
 */

/** Group names that are ROLES, not authorities. */
const NON_TENANT_GROUPS = new Set([
  'admin', 'investigator', 'reader', 'platform_admin',
])

export function tenantFromGroups(groups: string[] | undefined): string | undefined {
  const tenants = (groups || [])
    .map((g) => String(g || '').replace(/^\//, '').trim())
    .filter((g) => g && !NON_TENANT_GROUPS.has(g.toLowerCase()))
    .sort()   // sorted, like the backend: at least both sides agree
  if (tenants.length > 1) {
    console.warn('[auth] user is in several tenant groups, using the first '
      + `of ${JSON.stringify(tenants)} — the backend does the same`)
  }
  return tenants[0]
}

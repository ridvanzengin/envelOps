import { useEffect, useState } from "react";

import { apiGet } from "../api/client";

export interface DevTenantOption {
  user_id: string;
  tenant_id: string;
  tenant_name: string;
  email: string;
}

// GET /auth/dev-tenants 404s unless the backend has
// ENVELOPS_DEV_AUTH_BYPASS_ENABLED or ENVELOPS_DEMO_MODE_ENABLED set, so in
// a real deployment with both off this silently fetches nothing and every
// consumer below just renders as if there were no dev tenants. Shared by
// Login.tsx's own dev-switcher dropdown, App.tsx's demo-mode auto-login,
// and Dashboard.tsx's demo-mode tenant dropdown -- previously local to
// Login.tsx only, before the other two needed the same list.
export function useDevTenants(): DevTenantOption[] {
  const [tenants, setTenants] = useState<DevTenantOption[]>([]);
  useEffect(() => {
    apiGet<DevTenantOption[]>("/auth/dev-tenants", null)
      .then(setTenants)
      .catch(() => setTenants([]));
  }, []);
  return tenants;
}

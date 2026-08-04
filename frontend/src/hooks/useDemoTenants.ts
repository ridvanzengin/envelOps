import { useEffect, useState } from "react";

import { apiGet } from "../api/client";

export interface DemoTenantOption {
  user_id: string;
  tenant_id: string;
  tenant_name: string;
  email: string;
}

// GET /auth/demo-tenants 404s unless the backend has
// ENVELOPS_DEMO_MODE_ENABLED set, so outside a demo deployment this
// silently fetches nothing and every consumer below just renders as if
// there were no demo tenants. Shared by App.tsx's demo-mode auto-login
// and Dashboard.tsx's demo-mode tenant dropdown -- the only two
// consumers now that Login.tsx's own dev-only tenant switcher has been
// removed entirely (decided 2026-08-04, demo mode covers the same need).
export function useDemoTenants(): DemoTenantOption[] {
  const [tenants, setTenants] = useState<DemoTenantOption[]>([]);
  useEffect(() => {
    apiGet<DemoTenantOption[]>("/auth/demo-tenants", null)
      .then(setTenants)
      .catch(() => setTenants([]));
  }, []);
  return tenants;
}

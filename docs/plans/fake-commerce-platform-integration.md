# Plan: a real-HTTP fake commerce platform, backed by a bounded catalog

**Status: planned, not built.** This is a design doc for future work, not a
description of current behavior — see `docs/ROADMAP.md`'s open items for
the live status pointer back to this file.

## Why this exists

Found live (2026-08-04, Test Console, direct instruction to investigate):
asking a tenant's AI "do you have ak47 in stock?" got a confident, ordinary
answer ("out of stock, back in ~14 days") with no escalation and no
hesitation, regardless of which tenant or business type. Root cause, fully
traced:

- `escalation/safety_gate.py`'s Layer 1 floor only covers three categories
  (contraindication language, symptom/complaint language, outcome-guarantee
  requests) — all health-adjacent. Nothing in it recognizes weapons or
  regulated goods. Tracked as its own, separate open item — a pattern-list
  fix, unrelated to this plan.
- `app/commerce/connectors.py`'s `check_inventory(product_name, size)` is
  hash-seeded and **unbounded**: `_seeded_random("inventory", product_name,
  size)` will happily hash literally any string and return a plausible
  in-stock/out-of-stock answer with a fabricated restock ETA
  (`rng.randint(3, 21)` days — where the "14 days" came from). It has no
  concept of what a tenant actually sells, so it answers a weapons query
  exactly as confidently as a real product query.

This plan addresses the **second** cause: ground `check_inventory` (and,
for consistency, `get_order_status`) in a real, bounded, per-tenant catalog
instead of "any string produces a plausible answer" — so an off-catalog
query genuinely comes back "not found," the way a real commerce platform's
API would respond. It does not fix the safety-floor gap; that's
complementary, separately tracked, and should still happen regardless of
whether this plan gets built.

## Goal / non-goals

**Goal:** make the simulated commerce integration's plumbing look like what
a real one would look like — the connector makes a real HTTP call, against
a real (if fake) bounded catalog — while staying **fully inside this
project's existing simulation boundary**.

**Non-goals, explicitly:**
- **Not** a real Shopify/WooCommerce/etc. integration. No real credentials,
  no real external network call, no OAuth. `REQUIREMENTS.md` §5/§10 and
  `ARCHITECTURE.md` §12 already settled this as cancelled, not deferred —
  this plan does not reopen that decision. The new endpoint this plan adds
  is called *by our own backend, from our own backend* — never reachable
  from outside, never a real platform.
- **Not** a fix for the safety-floor weapons/regulated-goods gap (separate
  open item).
- **Not** a new pipeline node, new intent, or new tenant-facing config
  surface. `ToolCallingConfig`'s existing two flags
  (`order_status_lookup_enabled`, `inventory_check_enabled`) keep meaning
  exactly what they mean today.

## Current architecture (for context — nothing here changes)

`app/pipeline/graph.py`'s `call_tools` node (sync today, see below) calls
`app/commerce/tools.py`'s `execute(name, args) -> BaseModel | None`, which
dispatches by tool name straight into `connectors.get_order_status`/
`check_inventory` — plain in-process Python function calls, no I/O. The
model's own decision to call a tool at all is already real
(`app/core/llm.py`'s `generate_with_tools`, AUTO tool-config, genuinely
model-driven) — only the connector functions' *internals* are fake. This
plan only touches those internals and the one node that calls them; the
tool declarations, the model's decision-making, and how results get folded
into `PipelineState.tool_call_results` (`app/pipeline/graph.py`'s
`call_tools`, near `format_result`) are all unaffected.

## Proposed architecture

### 1. Bounded per-tenant catalog — new data model

A new table, `FakeCommerceProduct`, following this codebase's existing
per-module convention (`app/commerce/models.py`, tenant-scoped per
`CLAUDE.md`'s "every table gets tenant_id" rule):

```
FakeCommerceProduct
  id: UUID (pk)
  tenant_id: UUID (fk, indexed)
  name: str
  size: str | None          # matches check_inventory's existing optional size param
  in_stock: bool
  quantity_available: int | None   # None when not in_stock, same as today's InventoryResult
  restock_eta_days: int | None     # None when in_stock
```

A product not present in a tenant's rows is, correctly, **not carried** —
this is the actual fix for the AK-47 case, and it's a property of the data
model, not a special-cased check.

Open question to resolve when building, not now: does `size` need real
variant modeling (e.g. a separate `FakeCommerceProductVariant` table), or
is a flat optional string field (matching `check_inventory`'s current
signature exactly) good enough? Lean toward the flat field — nothing today
demands more, and it's trivially extendable later.

Orders are different: there's no existing "Order" concept in this app's
data model (Leads/Conversations exist, Orders don't), and unlike products,
an arbitrary-looking order number is a *normal*, expected thing for a real
customer to type — a real platform's API would just return "not found" for
a made-up one too. Recommendation: **don't** build a bounded fake-orders
table; keep `get_order_status`'s existing hash-seeded logic, just move it
server-side behind the new endpoint (below) for consistency of plumbing,
not because it has the same unbounded-fabrication problem `check_inventory`
has.

### 2. Fake platform HTTP API — new internal-only router

A new `app/commerce/fake_platform_api.py`, mounted at its own prefix (e.g.
`/internal/fake-commerce`), shaped loosely like a real commerce platform's
admin API (a search-style product lookup, an order-status lookup) —
enough to be recognizably platform-shaped, same "not full fidelity"
philosophy `app/channels/simulated_client.py` already uses for the
simulated channel webhooks:

- `GET /internal/fake-commerce/products?tenant_id=...&query=<name>&size=<size>`
  → matches from `FakeCommerceProduct`, or an empty/not-found response.
- `GET /internal/fake-commerce/orders/{order_number}?tenant_id=...` →
  today's existing hash-seeded `OrderStatusResult` shape, computed
  server-side instead of in-process.

**Auth, an open decision:** this endpoint is never reachable except from
our own backend calling itself, so real security hardening isn't the
point — but for the plan to actually demonstrate "what real
platform-integration code looks like," the connector should still have to
do real header-based auth, the way it would against a real platform.
Recommendation: a static internal bearer token (e.g.
`ENVELOPS_FAKE_COMMERCE_INTERNAL_TOKEN`), checked the same fail-closed way
`app/channels/api.py`'s webhook secret header already is. Not real
security — just enough that the connector code has to build a real
`Authorization` header and handle a real 401, the way it would for a real
integration.

### 3. Connector changes — real HTTP, real async

`check_inventory`/`get_order_status` become `async def`, using
`httpx.AsyncClient` (already a backend dependency, `httpx>=0.27`) to call
the new endpoint instead of computing a result in-process. This requires
`call_tools` (`app/pipeline/graph.py`, currently a **sync** node — confirmed
directly, not assumed) to become `async def call_tools`, and
`app/commerce/tools.py`'s `execute()` to become async too. This is a
well-established pattern already in this same graph — `search_knowledge`,
`decide_next_step`, `keep_chatting`, `book_or_checkout`,
`log_lead_and_notify` are all already async nodes in the same
`StateGraph`, so mixing sync/async nodes isn't new territory here.

Error handling matters for realism: a timeout or non-2xx from the fake
endpoint should map to the same "gracefully absent" contract `execute()`
already guarantees (`-> BaseModel | None`, never raises) — this is exactly
the kind of failure-handling code a real integration would need too, and
is worth writing for real rather than assuming the fake endpoint never
fails.

### 4. Seeding

Extend `scripts/seed_calibration_tenant.py` / `scripts/seed_showcase_tenants.py`
(or add a small dedicated seed step) to populate a handful of
`FakeCommerceProduct` rows per tenant, matching each tenant's actual
business (Wildroot Apparel Co gets clothing items, Voltage Gadgets gets
electronics) — same "deterministic and reproducible, not random"
philosophy `connectors.py`'s own docstring already commits to for
calibration review.

## Testing plan

- New tests for the fake platform API router itself: a real catalog hit,
  an off-catalog miss (the actual regression test for the AK-47 case —
  assert a genuinely not-carried product comes back not-found through the
  full pipeline, not just at the endpoint), and the order-status endpoint.
- Updated `connectors.py` tests: now need HTTP-layer mocking (`respx` or
  manual `httpx.AsyncClient` mocking) instead of pure function calls.
- `call_tools`/`execute()` tests updated for the new async signatures.
- One end-to-end-style test through Test Console confirming a
  known-off-catalog product produces a "we don't carry that" style reply
  instead of a fabricated stock answer.

## Migration / rollout

- One Alembic migration for `FakeCommerceProduct` (remember the
  `pgvector`/checkpoint-table autogenerate gotchas `CLAUDE.md` already
  documents, if this migration is generated alongside other pending
  schema changes).
- Existing calibration tenants (Wildroot Apparel Co, Voltage Gadgets) need
  catalog rows seeded before this is useful against them — not automatic
  from the migration alone.

## Open decisions to make when this is actually built (not now)

1. Flat `size` string vs. a real variant table (lean flat, see above).
2. Exact internal-auth mechanism for the fake endpoint (lean static
   bearer token, see above).
3. Whether to also route `get_order_status` through a bounded fake-orders
   table, or keep it hash-seeded-but-server-side (lean the latter, see
   above — the fabrication problem this plan exists to fix is specific to
   unbounded product lookups, not order numbers).
4. Whether `call_tools`'s conversion to async should happen as part of
   this change or be split out as its own smaller, separately-landable
   PR first (probably worth doing first, in isolation, since it's a
   mechanical change with its own blast radius across the graph).

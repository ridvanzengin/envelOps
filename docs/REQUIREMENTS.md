# EnvelOps — Requirements Document (Pre-Architecture)

> Working name: **EnvelOps**. This document captures *what* the product
> needs to do and *why*, before any technical/architecture decisions are made.
> No tech stack, no database choices, no framework picks — those come next, once
> this is settled. This supersedes the earlier CLAUDE.md draft, which leaned too
> far toward a research showcase; this version is scoped for what an actual
> small/mid-size business could use.

---

## 1. Vision

Small and mid-size businesses selling via social media DMs (health tourism
clinics, e-commerce sellers, service businesses, etc.) can't staff 24/7 replies,
lose leads to slow response times, and can't easily give an AI assistant
consistent, correct answers about their own business without hallucination risk.

EnvelOps turns inbound DMs across channels into a managed, AI-assisted conversation
pipeline — grounded in the business's own knowledge, scored for lead quality,
and gated by human review before anything is sent — with enough configurability
that different business models (appointment-based, product-based,
booking-based) can each shape the same underlying flow to their needs.

**Explicitly not the goal:** competing with Chatwoot/Botpress/Respond.io as a
full-featured omnichannel/CRM product, or building an AI-research showcase.
Practicality for a real small-business owner is the standard everything gets
measured against.

## 2. Business model coverage

The pipeline (§3) is fixed; what varies by business model is *what's configured
inside a few of its steps*:

| Business model | Knowledge grounding | Lead scoring signal | Closing action |
|---|---|---|---|
| Service/appointment (clinics, real estate, legal, coaching) | Eligibility, pricing, service FAQs | Budget mentioned, urgency, decision-maker language | Usually human-closed — collect info, hand to a coordinator |
| Product/e-commerce (honey, apparel, handmade goods) | Catalog, sizing, shipping, returns | Cart intent, price sensitivity | Near-instant — real checkout/payment link |
| Local/booking-based (salons, repair, restaurants) | Hours, availability, service menu | Thin — mostly "do they want a slot" | A calendar slot, not a payment |
| B2B/high-ticket (agencies, consulting) | Case studies, pricing tiers, capabilities | Company size, stated budget, stakeholder signals | Almost always human-closed — "book a call" |

The requirement this implies: **"what counts as a hot lead" and "what closing
looks like" must be configurable per business**, not hardcoded per vertical.

**The Product/e-commerce row above is the concrete Phase 1 pilot**, not just
an example: a real small honey seller, selling via Instagram DMs and a
webstore. See §12 for the validation plan that leads up to using it as a
live tenant.

## 3. Core conversation pipeline

Every inbound message follows the same sequence, regardless of business model:

1. **Incoming message** — normalized from any connected channel
2. **Understand intent** — what is the person asking/trying to do
3. **Search knowledge base** — grounded answer, if it's a knowledge question
4. **Score the lead** — hot / warm / cold
5. **Decide next step** — based on intent + score
6. Branches into: **keep chatting** / **escalate to human** / **book or checkout**
7. **Log lead & notify team** — recorded, tagged with source
8. **Follow up after delay** — re-engages if the lead goes quiet, loops back to step 2 if they reply

The escalate branch (step 6) and the follow-up loop (step 8) are universal
requirements, not vertical-specific features — every business model has some
version of "don't auto-answer this" and most DM-based businesses lose more
revenue to silent drop-off than to bad AI answers.

## 4. Draft-and-approve workflow (core requirement, not optional)

**AI drafts a reply; a human approves before it sends.** This is the default
mode, not a configurable extra — it's the trust mechanism that makes an AI
handling real customer conversations acceptable to a small-business owner who
has no reason yet to trust it unsupervised.

Implications to design for, even if not built immediately:
- A **graduation path**: after enough approved-without-edits drafts in a
  low-risk category (e.g. simple FAQ answers), that category could eventually
  move to auto-send, while anything higher-stakes (health questions, price
  negotiation, complaints) always stays human-gated. The hook for this should
  exist in the data model from the start (track approved-as-is vs. edited vs.
  rejected per category) even though the "graduate to auto-send" feature itself
  is not being built now.
- Draft-approval timeout/notification mechanics are a real open question — see
  §9 (Roadmap — undecided, non-blocking).

## 5. Knowledge sources

Two fundamentally different kinds of "knowledge," requiring different handling:

**Static knowledge** (policies, service descriptions, general FAQs) — safe to
embed and retrieve via RAG, since it barely changes. Supported input methods:
- Paste a URL (crawled; FAQPage-structured pages parsed as clean Q&A pairs
  where available, otherwise chunked as text)
- Upload documents (PDF, plain text)
- Manual entry (owner types FAQ pairs directly)
- **Re-sync is required, not optional** — a manual "refresh this source" action
  at minimum, since a business will update its FAQ page and forget to tell the
  system, and a stale embedded answer is a real failure mode.

**Live data** (current stock, exact price, shipping quotes) — must **not** be
embedded at ingestion time; must be looked up at question-time via a real
connection, because embedding it once guarantees it goes stale.
- For businesses with a connectable platform (Shopify, WooCommerce, etc.): a
  "connect your store" step, real-time lookup with a short cache window to
  avoid hammering the platform's API on every DM.
- For businesses without one (e.g. a solo honey seller): a manually-updated
  spreadsheet/CSV is an acceptable static-ish fallback with manual refresh —
  this path must be supported, since assuming every business has an e-commerce
  backend would exclude exactly the smallest businesses this is meant to serve.
- **Connecting live data is optional at onboarding** — a business must be able
  to have a fully working assistant grounded only in static knowledge.

## 6. Escalation & safety

Two layers:

- **Layer 1 — platform-enforced floor**, non-negotiable for regulated-adjacent
  business types (health-related businesses specifically): mandatory escalation
  on contraindication-type language, symptom/complaint language, or any request
  for an outcome guarantee.
- **Layer 2 — business-owned, configurable**: ordinary rules the owner sets
  (budget thresholds, business-hours routing, competitor mentions).

**Layer 1 is platform defaults plus tenant additions.** The business owner
can see the full default phrase/pattern list in the UI (shown disabled/
locked, not hidden — transparency about what's being checked matters) and
can add their own domain-specific trigger phrases on top, but can't edit
or remove a default — that half stays completely immutable, which is what
keeps the platform floor itself non-negotiable.

Tenant-added phrases, unlike defaults, **can be removed** — decided
2026-07-29, reversing this section's original "additive only, tenant
customization only ever gets stricter" framing. The original reasoning
still stands as a real trade-off, not a mistake: a business optimizing
for fewer escalations now *can* remove a phrase it added and later found
inconvenient, weakening its own floor. Accepted deliberately anyway — a
permanently-stuck typo'd or mistakenly-added phrase, with no way to
correct it, was judged the worse failure mode of the two. Adding a phrase
is still the whole interaction otherwise — no regex, no categories to
choose, since business owners think in phrases ("mad honey" / *deli
bal*), not pattern syntax. Layer 2 stays fully tenant-controlled
(add/edit/remove) since it's ordinary business rules, not safety.

**The safety check must not be the same model self-assessing its own answer.**
It should be a separate, narrower check, and its result is a hard gate, not a
soft suggestion the generation step can talk itself out of.

Every escalation is logged with *what* triggered it, not just "escalated" —
this is both the audit trail and the artifact that proves the safety layer is
doing real work.

**Liability**: handled at the Terms of Service level (the business owner bears
responsibility for what they configure and how they use AI-assisted replies),
not solved by engineering alone. The platform-enforced safety floor stays in
place regardless of where liability sits — that's a product-quality decision
independent of the legal one.

## 7. Multi-tenancy

**Decided now, at the data-model level** — not deferred, because retrofitting
tenant isolation after data already exists is a rewrite, not a feature add.
Every table, every vector collection, every graph database scope is isolated
per tenant (`tenant_id` on every table; per-tenant vector namespaces; scoped or
separate graph databases per tenant) from the very first version, even while
only one tenant is running in practice.

**Explicitly deferred**: self-serve signup, billing, a tenant-admin UI,
subdomain-per-business routing. These are product-surface work that can be
added later without touching the underlying data model, as long as the
isolation itself was built in from day one.

## 8. Multi-user roles

**Deferred, safely** — unlike tenancy, this doesn't have a retrofit trap, since
auth already exists from day one. Ship with a single "owner" role (full
access, including draft approval). Adding a narrower "staff/approver" role
later is a normal incremental change (a `role` column plus permission checks),
not a foundational rework.

## 9. Roadmap — undecided design details (non-blocking)

These are real, acknowledged gaps — not silently dropped, not required before
starting the build:

- **Channel failure behavior**: what happens when a channel (e.g. Beeper's
  WhatsApp/Instagram bridge) disconnects — silent stop vs. detected fallback to
  a "queue for human" mode. Flagged as needing a proper fix, not yet designed.
- **Observability dashboard, for two distinct audiences**: the builder's view
  (execution traces — why the AI answered this way) and the business owner's
  view (response time, draft-approval rate, leads gone cold). Likely two
  different views, not one dashboard serving both — not yet designed.
- **Draft-approval timeout/notification mechanics**: what happens if nobody
  approves a draft in time — does the lead go cold, does it escalate itself
  after N minutes, how is the approver notified. Not yet designed.
- **Data retention/deletion policy specifics**: how long conversations are kept,
  how a business owner deletes a customer's data on request. A stated policy
  is needed even before it's a built feature.

## 10. Cut vs. deferred to later phases

Named here so nothing disappears silently — these are two different things.
**Cut** means removed by decision and not planned to come back. **Deferred**
means a real, intended part of the product that's just sequenced after
Phase 1 — see §11 for where each one lands.

**Cut:**

- **ROI / ad-spend attribution** — cut. Was a differentiator in an earlier
  draft; removed by deliberate decision, not lost track of.
- **Multi-model prompt playground** — cut, was scope creep.

**Deferred — will be built, just not in Phase 1:**

- **Starter template gallery** (pre-built configurations for common business
  types, chosen at onboarding) — a real, important requirement. Ship with one
  minimal default configuration for Phase 1; see §11 for sequencing.
- **AI-assisted configuration** (an assistant that helps a business owner set
  up their own flow) — a later version, not cut.
- **Graph-augmented retrieval** — still a real, intended capability for domains
  where facts are relationally connected (e.g. medication × procedure
  interactions in health-related businesses), decided automatically by the
  platform per §3 step 3, never exposed as a manual choice. Sequenced after the
  core pipeline (§3) and draft/approve workflow (§4) are working end to end.
- **Fine-tuning** (embedding model, lead-scoring classifier) — a later-phase
  credibility/quality improvement, not required for the pipeline to function.
  A plain LLM call is an acceptable starting point for scoring and retrieval.

## 11. Language support (Turkish + English)

**Phase 1 requirement, not deferred** — the first real pilot (§12) is a
Turkish business, so this has to work from the start, not get bolted on
later.

- **LLM generation**: detect the language of the incoming message and reply
  in the same language (Turkish in, Turkish out; English in, English out).
  Applies to both intent understanding (§3 step 2) and reply generation — a
  modern general-purpose LLM handles Turkish well enough for this without a
  separate translation step.
- **Knowledge base**: sources are entered in whichever language the business
  owner uses (realistically Turkish, for this pilot) and must still be
  retrievable when a customer asks in the other language. This needs an
  embedding model with real cross-lingual performance, not just "supports
  Turkish" — matching a Turkish query against Turkish-embedded chunks is the
  easy case; matching an English query against Turkish chunks (or vice
  versa) is the one that actually needs checking when picking the embedding
  provider.
- **UI**: the dashboard/inbox/etc. (ARCHITECTURE.md §10) needs its own i18n,
  independent of the LLM's language handling — a Turkish business owner
  using the dashboard and a customer DMing in English are two separate
  language surfaces, not one.
- **Not required for Phase 1**: languages beyond these two, or a language
  picker exposed to end customers — the pipeline detects and matches, it
  doesn't ask.

## 12. Pilot & validation plan

Before this touches a real customer conversation, two stages, in order:

1. **Synthetic messages** — exercise the full pipeline (§3) end to end,
   including the safety gate (§6), against fabricated DM conversations
   covering the Product/e-commerce row of §2 (order questions, shipping,
   returns, price sensitivity) and the safety-floor edge cases (outcome-
   guarantee and symptom-language triggers) even though honey isn't a
   health-related business — the floor should still hold for anyone who
   phrases a question that way.
2. **Real pilot** — once synthetic testing holds up, connect to the actual
   honey business's real Instagram DMs and webstore as the first real
   tenant. Not a second round of synthetic testing with different data —
   real customers, real orders, real consequences if a reply is wrong.

This ordering isn't optional: auto-send is the Phase 1 default (ARCHITECTURE
§5), so a real business's real customers see whatever the pipeline produces
with no human checkpoint except the safety gate. Synthetic testing is what
earns the right to point it at real DMs, not a formality to skip once the
demo looks good.

## 13. Rough build sequencing (not architecture — just what depends on what)

1. Core pipeline (§3) + draft/approve (§4) + tenant-isolated data model (§7) +
   single owner role (§8) + static knowledge sources (§5) + one channel +
   Turkish/English language support (§11)
2. Safety escalation floor (§6) + live data connection (§5) for platforms that
   support it
3. Hybrid (graph-augmented) retrieval for relationally-complex business types
4. Fine-tuning for retrieval and lead-scoring, if time allows
5. Deferred items from §10, roughly in the order: dashboard/observability
   design (§9) → channel-failure fix (§9) → template gallery → multi-user
   roles → AI-assisted configuration

Validation gate on step 1 (before calling it done): the synthetic-then-real
pilot sequence in §12.

---

*Next step: see [`ARCHITECTURE.md`](ARCHITECTURE.md) for the technical
decisions, using this document as the fixed reference for what's being built
and why.*

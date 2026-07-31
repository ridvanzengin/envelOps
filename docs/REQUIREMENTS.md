# EnvelOps — Requirements Document (Pre-Architecture)

> Working name: **EnvelOps**. This document captures *what* the product
> needs to do and *why*, before any technical/architecture decisions are made.
> No tech stack, no database choices, no framework picks — those come next, once
> this is settled. This supersedes the earlier CLAUDE.md draft, which leaned too
> far toward a research showcase; this version is scoped for what an actual
> small/mid-size business could use.

> **STATUS UPDATE (2026-07-31):** the real pilot this document was written
> around (§1, §2, §12 — a friend's honey business) has been deprioritized.
> EnvelOps is now a solo portfolio project demonstrating AI behavior
> orchestration/safety/configuration, not a product being shipped to a real
> business — see `docs/ROADMAP.md` for the full decision and reasoning. This
> document's original vision/requirements text below is kept as-is, not
> rewritten, since it's still an accurate record of what was actually
> designed and why — but §11 (language support) is now **cut**, not a live
> requirement, and §12's validation plan has been superseded by a different
> methodology (a one-tenant-at-a-time calibration loop against real sampled
> customer-support DMs — see ROADMAP.md). Read affected sections with that
> in mind rather than assuming everything below is still current.

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

**The Product/e-commerce row above was the concrete Phase 1 pilot** (a real
small honey seller, selling via Instagram DMs and a webstore) **— that
pilot is now deprioritized (2026-07-31, see `docs/ROADMAP.md`).** The
row's validation role is now served by a one-tenant-at-a-time calibration
process instead: seed a fake business, run it against ~28 real sampled
customer-support DMs, review live, lock in, move to the next tenant. Two
calibration tenants exist so far (both product/e-commerce: Wildroot
Apparel Co, Voltage Gadgets), deliberately capped rather than expanded
across all four rows above — see ROADMAP.md for why. §12 below describes
the original two-stage synthetic-then-real plan, superseded by this.

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

**Status (2026-07-31): superseded, not just "not built immediately."**
ARCHITECTURE §5 cut general draft-and-approve from Phase 1 in favor of
auto-send gated only by the safety-floor escalation — a real-business-ops
trust mechanism this portfolio project has no real customers to need.
Whether it comes back, along with the graduation path and timeout/
notification mechanics below, is cancelled rather than open — see
`docs/ROADMAP.md`. Original implications kept for the record:
- A **graduation path**: after enough approved-without-edits drafts in a
  low-risk category (e.g. simple FAQ answers), that category could eventually
  move to auto-send, while anything higher-stakes (health questions, price
  negotiation, complaints) always stays human-gated. The hook for this would
  need to exist in the data model from the start (track approved-as-is vs.
  edited vs. rejected per category).
- Draft-approval timeout/notification mechanics — what happens if nobody
  approves a draft in time.

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

**Update (2026-07-31): a *simulated* version of this now exists, a real
platform connector still doesn't.** Order-status and inventory lookups use
real Gemini tool-calling (the model genuinely decides whether to call a
tool) backed by fake, deterministic connectors (`app/commerce/`) — not a
real Shopify/WooCommerce/etc. integration, and not planned to become one;
building real third-party commerce integrations was explicitly decided
against (see ROADMAP.md) as out of scope for what this project
demonstrates. The "connect your store" real-platform path described above
is still exactly as undesigned/unbuilt as before this update.

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

**Observability dashboard — built (2026-08-01), see `docs/ROADMAP.md`.**
Shipped as one unified view, not the two distinct audiences (builder's
trace view vs. business owner's operational view) originally envisioned
below — real conversation/message/lead/escalation/pipeline-trace data
(stat tiles, a daily trend chart, an intent breakdown, a per-channel
resolution-rate table) turned out to serve both readings well enough in
a single page for a portfolio project's data volumes; revisit the split
if that stops holding. Original framing, for the record: "the builder's
view (execution traces — why the AI answered this way) and the business
owner's view (response time, draft-approval rate, leads gone cold)."

**Cut from this list (2026-07-31), not just deferred** — see §10 and
`docs/ROADMAP.md`: channel failure behavior beyond the health-check stub,
draft-approval timeout/notification mechanics, and data retention/
deletion policy specifics. All three were "matters for a real business
with real customers" gaps that don't add to what this portfolio project
demonstrates.

## 10. Cut vs. deferred to later phases

Named here so nothing disappears silently — these are two different things.
**Cut** means removed by decision and not planned to come back. **Deferred**
means a real, intended part of the product that's just sequenced after
Phase 1 — see §11 for where each one lands.

**Cut:**

- **ROI / ad-spend attribution** — cut. Was a differentiator in an earlier
  draft; removed by deliberate decision, not lost track of.
- **Multi-model prompt playground** — cut, was scope creep.
- **Turkish/bilingual pipeline support** (2026-07-31) — cut, not deferred;
  see §11 (now marked cut below) for the full reasoning. Frontend UI i18n
  (English/Turkish dashboard chrome) is unaffected, only the pipeline's
  own reply-language-detection/matching is cut.
- **Real commerce-platform connectors** (Shopify/WooCommerce/etc., 2026-07-31)
  — cut in favor of a simulated version (§5's update above); building real
  third-party integrations was judged out of scope for what this project
  demonstrates, not just not-yet-built.
- **Real channel integrations beyond Telegram** (Instagram/WhatsApp/
  Facebook/Email, 2026-07-31) — cut in favor of simulated webhook-shaped
  entry points (same real pipeline, no real platform contacted); see
  ARCHITECTURE §8.
- **Human-paused conversations**, **channel failure behavior** beyond the
  health-check stub, **data retention/deletion policy specifics**, and
  **draft-and-approve's return** (including its timeout/notification
  mechanics, §4/§9) — all cut 2026-07-31, same pivot as the row below:
  real-business-ops concerns judged out of scope for what this portfolio
  project demonstrates, see `docs/ROADMAP.md`.
- **Starter template gallery** and **AI-assisted configuration**
  (2026-07-31, see `docs/ROADMAP.md`) — both were "deferred, will be
  built later" as originally written below; cut instead once the
  portfolio-scope pivot capped tenant/vertical breadth at ~2 calibration
  tenants — both were predicated on exactly the multi-vertical breadth
  that pivot walked back from, so there's no longer a battle-tested
  scenario set to build either on top of.

**Deferred — will be built, just not in Phase 1:**

- **Graph-augmented retrieval** — still a real, intended capability for domains
  where facts are relationally connected (e.g. medication × procedure
  interactions in health-related businesses), decided automatically by the
  platform per §3 step 3, never exposed as a manual choice. Sequenced after the
  core pipeline (§3) and draft/approve workflow (§4) are working end to end.
- **Fine-tuning** (embedding model, lead-scoring classifier) — a later-phase
  credibility/quality improvement, not required for the pipeline to function.
  A plain LLM call is an acceptable starting point for scoring and retrieval.

## 11. Language support (Turkish + English) — **CUT (2026-07-31)**

**No longer a requirement.** This was written as "Phase 1 requirement, not
deferred" specifically because the real pilot (§12) was a Turkish
business — now that the pilot is deprioritized, the entire premise behind
this section no longer holds. The pipeline no longer detects or matches
reply language; replies are effectively always whatever language the
model defaults to (English), regardless of input language. This also
resolves what had been an open, recurring bug category (language-
consistency issues found live more than once) by removing the mechanism
that caused them, not by fixing them in place.

**Follow-up, same day: `escalation/safety_gate.py`'s own Turkish
safety-term detection patterns were also removed**, reversing this
section's original "not cut" call. That call was made on the reasoning
that pattern-matching dangerous phrases is a different concern from
reply-language-matching — still true in principle, but on direct
instruction the project is now English-only end to end, not "English-only
except one still-bilingual safety module." System defaults are
English-only patterns now (`_CONTRAINDICATION_PATTERNS`/`_SYMPTOM_PATTERNS`/
`_CERTAINTY_CUES`/`_EFFICACY_CUES`); tenant-added trigger phrases
(plain substring match, any language) are unaffected — a business owner
can still add a non-English phrase, that mechanism was never
language-specific. The frontend's `react-i18next` UI chrome (English/
Turkish dashboard switcher, inert and isolated, not the source of any
problem) is still untouched.

Original requirement (summary, not in effect): detect the incoming
message's language and reply in kind (LLM generation), retrieve knowledge
across languages (needs real cross-lingual embedding performance, never
verified before the cut), and give the dashboard its own independent i18n
(UI-only, unaffected by the cut — still in place, see ARCHITECTURE §10).

## 12. Pilot & validation plan — **superseded (2026-07-31)**

**The pilot this plan was written for is deprioritized** — EnvelOps is now
a solo portfolio project, not a product being shipped to a real business
(see the status update at the top of this document and `docs/ROADMAP.md`).
Stage 1 below (synthetic messages) is still real, still used, and still
useful; stage 2 (a real pilot business) is not happening. In its place: a
one-tenant-at-a-time calibration loop (`scripts/seed_calibration_tenant.py`)
— seed a fake business, run it against ~28 real Bitext-sampled customer-
support DMs through the real pipeline, review live, lock in, move to the
next tenant, deliberately capped at a small number of tenants rather than
covering every §2 vertical. This validates the same things (pipeline
correctness, grounding quality, safety-floor behavior) without the
step-2-specific "real customers, real consequences" framing below, since
there's no real pilot to protect.

Original two-stage plan (summary, not in effect): stage 1 was synthetic
DM conversations exercising the full pipeline and safety gate end to end;
stage 2 was connecting the real honey business's Instagram DMs and
webstore as the first real tenant, gated on stage 1 holding up first
since auto-send (ARCHITECTURE §5) means a real business's customers see
whatever the pipeline produces with no checkpoint but the safety gate.
Stage 2 is what's superseded — stage 1's synthetic-testing discipline
carries over directly into the calibration loop above.

## 13. Rough build sequencing (not architecture — just what depends on what)

1. Core pipeline (§3) + draft/approve (§4) + tenant-isolated data model (§7) +
   single owner role (§8) + static knowledge sources (§5) + one channel +
   ~~Turkish/English language support (§11)~~ (cut 2026-07-31, see §11)
2. Safety escalation floor (§6) + ~~live data connection (§5) for platforms
   that support it~~ (a simulated version shipped 2026-07-31 instead — §5)
3. Hybrid (graph-augmented) retrieval for relationally-complex business types
4. Fine-tuning for retrieval and lead-scoring, if time allows
5. Deferred items from §10, roughly in the order: dashboard/observability
   design (§9) → channel-failure fix (§9) → multi-user roles
   (~~template gallery~~/~~AI-assisted configuration~~ cut 2026-07-31, §10)

Validation gate on step 1 (before calling it done): originally the
synthetic-then-real pilot sequence in §12; now just the synthetic stage
plus the calibration-tenant loop described in §12's update, since there's
no real pilot to gate.

---

*Next step: see [`ARCHITECTURE.md`](ARCHITECTURE.md) for the technical
decisions, using this document as the fixed reference for what's being built
and why.*

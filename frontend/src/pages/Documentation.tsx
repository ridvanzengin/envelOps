import type { ComponentType, ReactNode, SVGProps } from "react";
import { useTranslation } from "react-i18next";

import {
  ChannelsIcon,
  DashboardIcon,
  FlaskIcon,
  KnowledgeIcon,
  PlugIcon,
  SettingsIcon,
  ShieldIcon,
  StoreIcon,
} from "../components/icons";
import "./Documentation.css";

// Body content (features, stats, tech table) is deliberately English-only,
// same choice the sibling reference project (iotops-workspace/IoTOps) made
// for its own in-app docs page -- only the nav label/page header route
// through i18n like every other page, matching CLAUDE.md's framing of the
// frontend's react-i18next setup as UI chrome, not a commitment to
// translate every page's full body copy.
interface Feature {
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  title: string;
  route: string;
  body: ReactNode;
}

const FEATURES: Feature[] = [
  {
    icon: DashboardIcon,
    title: "Dashboard",
    route: "/",
    body: (
      <p className="docs-p">
        Live tenant stats — conversation/message counts, hot leads, escalations, average
        response time — plus a conversation-volume trend chart, an intent breakdown, a
        per-channel table, and knowledge-base status. All real data, no placeholder numbers.
      </p>
    ),
  },
  {
    icon: ChannelsIcon,
    title: "Channels",
    route: "/channels",
    body: (
      <p className="docs-p">
        Lists a tenant's connected channels with a working per-channel AI auto-reply toggle.
        Telegram is the one real platform integration; Instagram, WhatsApp, Facebook, and Email
        are simulated — the same real pipeline runs end to end, just with no real platform ever
        contacted.
      </p>
    ),
  },
  {
    icon: KnowledgeIcon,
    title: "Knowledge Sources",
    route: "/knowledge",
    body: (
      <p className="docs-p">
        Add business facts as manual text, a URL, or a PDF. Each source is chunked and embedded
        (pgvector) so replies can be grounded in the tenant's own knowledge instead of the
        model's general training data.
      </p>
    ),
  },
  {
    icon: FlaskIcon,
    title: "Test Console",
    route: "/test-console",
    body: (
      <p className="docs-p">
        Send a message through the real pipeline on any channel type and see the full
        diagnostics behind the reply — detected intent, lead score, and routing decision —
        without touching a real customer conversation.
      </p>
    ),
  },
  {
    icon: SettingsIcon,
    title: "Settings",
    route: "/settings",
    body: (
      <p className="docs-p">
        Typed, bounded per-tenant behavior configuration — tone, greeting/off-topic handling,
        closing behavior, safety trigger phrases, tool-calling — organized by tab. Deliberately
        not free-text AI instructions: every knob is a real, validated field.
      </p>
    ),
  },
  {
    icon: ShieldIcon,
    title: "Safety Gate",
    route: "every pipeline run",
    body: (
      <p className="docs-p">
        A pattern-based floor (contraindication/symptom/outcome-guarantee language) plus
        tenant-added trigger phrases sit ahead of auto-send. A match pauses the pipeline for a
        real human to resolve before anything reaches the customer — not a soft warning.
      </p>
    ),
  },
  {
    icon: StoreIcon,
    title: "Tool-Calling & Fake Commerce",
    route: "opt-in per tenant",
    body: (
      <p className="docs-p">
        Real Gemini tool-calling — the model genuinely decides whether an order-status or
        inventory question needs a lookup — backed by a real internal HTTP call to a bounded
        per-tenant product catalog. An off-catalog question comes back honestly "not carried,"
        not a fabricated answer.
      </p>
    ),
  },
  {
    icon: PlugIcon,
    title: "Integrations",
    route: "/integrations",
    body: (
      <p className="docs-p">
        A static preview of e-commerce platform connectors (Shopify, WooCommerce, and others) —
        not built in this phase. Simulated commerce via Tool-Calling above is the real
        capability today.
      </p>
    ),
  },
];

export default function Documentation() {
  const { t } = useTranslation();

  return (
    <section className="page">
      <div className="page__header">
        <h1>{t("nav.documentation")}</h1>
      </div>
      <p className="page__description">{t("pages.documentation")}</p>

      <div className="docs-page">
        <section className="docs-section">
          <h2 className="docs-section-title">About the Project</h2>
          <p className="docs-p">
            EnvelOps demonstrates AI behavior orchestration, safety gating, and per-tenant
            configuration for small-business DM handling. Inbound messages across channels go
            through one fixed pipeline — understand intent, ground in the business's own
            knowledge (plus real tool-calling for order-status/inventory questions), score the
            lead, decide the next step — then either auto-send or pause for a human at a hard
            safety gate.
          </p>
          <p className="docs-p">
            Originally scoped for a real pilot business; now a solo portfolio project focused on
            demonstrating the architecture end to end. Two demo tenants ship today (a clothing
            brand on Telegram, an electronics retailer on Instagram), each with its own bounded
            product catalog, knowledge base, and behavior configuration — proving the same
            pipeline adapts per business without hardcoded per-vertical logic.
          </p>

          <div className="docs-stat-grid">
            <div className="docs-stat">
              <span className="docs-stat-value">5</span>
              <span className="docs-stat-label">
                Channel types
                <br />
                1 real · 4 simulated
              </span>
            </div>
            <div className="docs-stat">
              <span className="docs-stat-value">8</span>
              <span className="docs-stat-label">
                Pipeline steps
                <br />
                intent → ground → score → close
              </span>
            </div>
            <div className="docs-stat">
              <span className="docs-stat-value">372</span>
              <span className="docs-stat-label">
                Backend tests
                <br />
                pytest, Python
              </span>
            </div>
            <div className="docs-stat">
              <span className="docs-stat-value">12</span>
              <span className="docs-stat-label">
                DB migrations
                <br />
                Alembic
              </span>
            </div>
          </div>
        </section>

        <section className="docs-section">
          <h2 className="docs-section-title">Features</h2>
          <div className="docs-features-grid">
            {FEATURES.map((feature) => {
              const Icon = feature.icon;
              return (
                <div className="docs-feature-card" key={feature.title}>
                  <div className="docs-feature-header">
                    <Icon className="docs-feature-icon" />
                    <h3 className="docs-feature-title">{feature.title}</h3>
                    <span className="docs-feature-route">{feature.route}</span>
                  </div>
                  {feature.body}
                </div>
              );
            })}
          </div>
        </section>

        <section className="docs-section">
          <h2 className="docs-section-title">Technical Overview</h2>
          <table className="docs-table">
            <thead>
              <tr>
                <th>Layer</th>
                <th>Technology</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Backend API</td>
                <td>
                  FastAPI (Python), Pydantic models as the single canonical schema across
                  API/DB/pipeline
                </td>
              </tr>
              <tr>
                <td>Frontend</td>
                <td>React + TypeScript + Vite</td>
              </tr>
              <tr>
                <td>Database</td>
                <td>PostgreSQL + pgvector (knowledge-chunk embeddings)</td>
              </tr>
              <tr>
                <td>Pipeline orchestration</td>
                <td>
                  LangGraph state machine, Postgres-backed checkpointer for the safety gate's
                  pause/resume
                </td>
              </tr>
              <tr>
                <td>Async tasks</td>
                <td>Celery + Redis — webhook processing, scheduled follow-ups via Celery Beat</td>
              </tr>
              <tr>
                <td>AI</td>
                <td>
                  Google Gemini (free tier) — generation, embeddings, and real function-calling
                  for order-status/inventory
                </td>
              </tr>
              <tr>
                <td>Auth</td>
                <td>JWT access tokens, PBKDF2 password hashing</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section className="docs-section">
          <h2 className="docs-section-title">Getting Started</h2>
          <p className="docs-p">Clone the repo, copy the env template, and bring the stack up:</p>
          <pre className="docs-block">{"cp .env.example .env\ndocker compose up"}</pre>
          <ul className="docs-list">
            <li>
              Backend health: <code className="docs-code">http://localhost:8000/healthz</code>
            </li>
            <li>
              Frontend: <code className="docs-code">http://localhost:5173</code>
            </li>
          </ul>
          <p className="docs-p">
            For architecture, data model, and pipeline detail, see the{" "}
            <a
              href="https://github.com/ridvanzengin/envelOps/tree/main/docs"
              target="_blank"
              rel="noopener noreferrer"
            >
              docs/
            </a>{" "}
            folder in the repo — <code className="docs-code">REQUIREMENTS.md</code>,{" "}
            <code className="docs-code">ARCHITECTURE.md</code>, and{" "}
            <code className="docs-code">ROADMAP.md</code> for current status and what's next.
          </p>
        </section>
      </div>
    </section>
  );
}

import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { StoreIcon } from "../components/icons";
import "./Integrations.css";

// Deliberately abstract (StoreIcon, not brand logos) and deliberately
// "Not connected" for every row -- this is a static preview of a future
// phase, not a real integration surface. See docs/ARCHITECTURE.md §10/§12
// and the plan behind this page for why: real e-commerce connectors are
// on record as cancelled (docs/ROADMAP.md), and this page doesn't reverse
// that -- app/commerce/'s existing fake tool-calling is the one real
// (if simulated) thing in this space today, cross-referenced below.
const PLATFORM_KEYS = ["shopify", "woocommerce", "bigcommerce", "magento", "prestashop"] as const;

export default function Integrations() {
  const { t } = useTranslation();

  return (
    <section className="page">
      <div className="page__header">
        <h1>{t("nav.integrations")}</h1>
      </div>
      <p className="page__description">{t("pages.integrations")}</p>

      <p className="integrations__tool-calling-note">
        {t("integrations.toolCallingNote")}{" "}
        <Link to="/settings">{t("integrations.toolCallingLinkLabel")}</Link>
      </p>

      <div className="card">
        <h2 className="integrations__section-title">{t("integrations.ecommercePlatforms")}</h2>
        <ul className="integrations__list">
          {PLATFORM_KEYS.map((key) => (
            <li key={key} className="integrations__row">
              <span className="integrations__row-icon">
                <StoreIcon />
              </span>
              <span className="integrations__row-name">{t(`integrations.platforms.${key}`)}</span>
              <span className="integrations__status">{t("integrations.notConnected")}</span>
              <button
                type="button"
                className="button"
                disabled
                title={t("integrations.comingSoon")}
              >
                {t("integrations.connect")}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

import { useTranslation } from "react-i18next";

export default function EscalationQueue() {
  const { t } = useTranslation();
  return (
    <section>
      <h1>{t("nav.escalations")}</h1>
      <p>{t("pages.escalations")}</p>
    </section>
  );
}

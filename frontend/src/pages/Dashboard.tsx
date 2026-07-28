import { useTranslation } from "react-i18next";

export default function Dashboard() {
  const { t } = useTranslation();
  return (
    <section className="page">
      <div className="page__header">
        <h1>{t("nav.dashboard")}</h1>
      </div>
      <p className="page__description">{t("pages.dashboard")}</p>
    </section>
  );
}

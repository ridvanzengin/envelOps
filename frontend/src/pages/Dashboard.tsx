import { useTranslation } from "react-i18next";

export default function Dashboard() {
  const { t } = useTranslation();
  return (
    <section>
      <h1>{t("nav.dashboard")}</h1>
      <p>{t("pages.dashboard")}</p>
    </section>
  );
}

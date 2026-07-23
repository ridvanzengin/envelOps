import { useTranslation } from "react-i18next";

export default function KnowledgeSources() {
  const { t } = useTranslation();
  return (
    <section>
      <h1>{t("nav.knowledge")}</h1>
      <p>{t("pages.knowledge")}</p>
    </section>
  );
}

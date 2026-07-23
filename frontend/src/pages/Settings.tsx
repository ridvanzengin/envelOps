import { useTranslation } from "react-i18next";

export default function Settings() {
  const { t } = useTranslation();
  return (
    <section>
      <h1>{t("nav.settings")}</h1>
      <p>{t("pages.settings")}</p>
    </section>
  );
}

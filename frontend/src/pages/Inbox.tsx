import { useTranslation } from "react-i18next";

export default function Inbox() {
  const { t } = useTranslation();
  return (
    <section>
      <h1>{t("nav.inbox")}</h1>
      <p>{t("pages.inbox")}</p>
    </section>
  );
}

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useConversationPanel } from "../context/conversationPanel/useConversationPanel";
import { BellIcon } from "./icons";
import "./ActivityBar.css";

// docs/ROADMAP.md §3.5 -- a live notification when a conversation gets
// escalated, on top of ChannelRail's existing (refetch-on-open) per-channel
// badges. Self-contained click-outside handling (own class name, not
// ChannelRail's .dropdown-menu) so this and ChannelRail's own account menu
// don't interfere with each other's open/close state.
export function ActivityBar() {
  const { t } = useTranslation();
  const { liveEscalationNotifications, dismissNotification, openPanel, selectConversation } =
    useConversationPanel();
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (!(event.target instanceof Element) || !event.target.closest(".activity-bar")) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  function openConversation(conversationId: string, channelType: string) {
    openPanel(channelType);
    selectConversation(conversationId);
    dismissNotification(conversationId);
    setIsOpen(false);
  }

  return (
    <div className="activity-bar">
      <button
        type="button"
        className="activity-bar__button"
        aria-label={t("activityBar.label")}
        aria-expanded={isOpen}
        onClick={() => setIsOpen((value) => !value)}
      >
        <BellIcon className="activity-bar__icon" />
        {liveEscalationNotifications.length > 0 && (
          <span className="activity-bar__badge">{liveEscalationNotifications.length}</span>
        )}
      </button>
      {isOpen && (
        <div className="activity-bar__list">
          {liveEscalationNotifications.length === 0 ? (
            <div className="activity-bar__empty">{t("activityBar.empty")}</div>
          ) : (
            liveEscalationNotifications.map((notification) => (
              <button
                key={`${notification.conversationId}-${notification.receivedAt}`}
                type="button"
                className="activity-bar__item"
                onClick={() =>
                  openConversation(notification.conversationId, notification.channelType)
                }
              >
                <span className="activity-bar__item-channel">{notification.channelType}</span>
                <span className="activity-bar__item-reason">{notification.reason}</span>
                <span className="activity-bar__item-time">{t("activityBar.justNow")}</span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

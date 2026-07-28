import { useContext } from "react";

import { ConversationPanelContext } from "./context";
import type { ConversationPanelContextValue } from "./context";

export function useConversationPanel(): ConversationPanelContextValue {
  const context = useContext(ConversationPanelContext);
  if (context === null) {
    throw new Error(
      "useConversationPanel must be used within a ConversationPanelProvider",
    );
  }
  return context;
}

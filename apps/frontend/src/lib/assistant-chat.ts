import { AssistantChatMessage } from "@/lib/types";

export const ASSISTANT_HISTORY_MAX_MESSAGES = 8;
export const ASSISTANT_HISTORY_MESSAGE_MAX_LENGTH = 4000;

export function truncateAssistantHistoryContent(content: string): string {
  const normalized = content.trim();
  return normalized.slice(0, ASSISTANT_HISTORY_MESSAGE_MAX_LENGTH);
}

export function normalizeAssistantHistory(
  history: AssistantChatMessage[],
): AssistantChatMessage[] {
  return history
    .slice(-ASSISTANT_HISTORY_MAX_MESSAGES)
    .reduce<AssistantChatMessage[]>((normalized, item) => {
      const content = truncateAssistantHistoryContent(item.content);
      if (!content) {
        return normalized;
      }
      normalized.push({
        role: item.role,
        content,
      });
      return normalized;
    }, []);
}

// Escalation.status and Conversation.status are plain `str` columns, no DB
// enum (backend/app/escalation/models.py, backend/app/conversations/models.py)
// -- this must handle an unrecognized string gracefully, not just the known
// values below.
const KNOWN_LABELS: Record<string, string> = {
  pending: "Pending",
  resolved: "Resolved",
  open: "Open",
};

function titleCase(value: string): string {
  return value.length === 0 ? value : value[0].toUpperCase() + value.slice(1);
}

export function StatusBadge({ status }: { status: string }) {
  const label = KNOWN_LABELS[status] ?? titleCase(status);
  const known = status in KNOWN_LABELS;
  return (
    <span
      className={`status-badge${known ? ` status-badge--${status}` : ""}`}
    >
      {label}
    </span>
  );
}

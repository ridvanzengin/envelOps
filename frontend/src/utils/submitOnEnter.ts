import type { KeyboardEvent } from "react";

// Shared by every multi-line <textarea> that sits inside a <form> and
// wants Enter to submit (matching the single-line <input> behavior it
// replaced), with Cmd/Ctrl+Enter OR Shift+Enter reserved for a real
// newline instead -- Cmd/Ctrl+Enter by direct instruction, Shift+Enter
// added alongside it since it's the far more common "newline in a chat
// box" convention (Slack, Discord, WhatsApp) and doesn't conflict with
// anything.
//
// The newline is inserted manually, not left to the browser's own
// default textarea behavior -- confirmed empirically (a real browser via
// Playwright) that a *modified* Enter keypress does not reliably trigger
// a textarea's native newline insertion the way a bare Enter does; the
// value came back with no separator at all.
export function handleTextareaEnterKey(
  event: KeyboardEvent<HTMLTextAreaElement>,
  setValue: (value: string) => void,
): void {
  if (event.key !== "Enter") return;
  const textarea = event.currentTarget;

  if (event.metaKey || event.ctrlKey || event.shiftKey) {
    event.preventDefault();
    const { selectionStart, selectionEnd, value } = textarea;
    const nextValue = `${value.slice(0, selectionStart)}\n${value.slice(selectionEnd)}`;
    const nextCursor = selectionStart + 1;
    // Mutate the DOM node directly and synchronously, then let React's
    // own re-render (triggered by setValue below) catch up -- confirmed
    // necessary empirically: restoring the cursor a frame later
    // (requestAnimationFrame) left a real race window where fast-
    // following keystrokes landed at the stale pre-newline cursor
    // position instead of after it. React's reconciliation is a no-op
    // for `.value` once the DOM already matches the incoming prop, so
    // this doesn't fight the re-render, it just gets there first.
    textarea.value = nextValue;
    textarea.setSelectionRange(nextCursor, nextCursor);
    setValue(nextValue);
    return;
  }

  event.preventDefault();
  textarea.form?.requestSubmit();
}

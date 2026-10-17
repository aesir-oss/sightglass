import { Fragment } from "react";

/** Render a signal message, showing `backtick` spans as code. Text only: nothing in it is parsed as HTML. */
export function MessageText({ text }: { text: string }) {
  const parts = text.split("`");
  return (
    <>
      {parts.map((part, i) =>
        // Odd parts were between backticks; an unclosed backtick leaves the last part as text.
        i % 2 === 1 && i < parts.length - 1 ? <code key={i}>{part}</code> : <Fragment key={i}>{part}</Fragment>,
      )}
    </>
  );
}

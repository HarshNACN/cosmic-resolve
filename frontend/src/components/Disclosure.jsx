import { useId, useState } from "react";

// Collapsed by default. The body is not mounted until opened, so large prompts and responses
// are not placed in the page until someone asks for them.
export default function Disclosure({ title, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  const panelId = useId();
  return (
    <div className="disclosure">
      <button
        type="button"
        className="disclosure-toggle"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
      >
        <span aria-hidden="true">{open ? "▾" : "▸"}</span> {title}
      </button>
      <div id={panelId} hidden={!open}>
        {open ? children : null}
      </div>
    </div>
  );
}

import { useEffect, useId, useRef, useState } from "react";
import "../styles/FilterDropdown.css";

/** The Map's custom combobox design, shared with the operational report. */
export default function FilterDropdown({ label, value, options, onChange, disabled = false }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const root = useRef(null);
  const trigger = useRef(null);
  const activeOption = useRef(null);
  const selected = Math.max(0, options.findIndex(option => option.value === value));

  useEffect(() => {
    if (!open) return undefined;
    const outside = event => {
      if (!root.current?.contains(event.target)) setOpen(false);
    };
    // Run before a containing dialog's Escape handler, and only for this menu.
    const escape = event => {
      if (event.key !== "Escape" || !root.current?.contains(document.activeElement)) return;
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
      trigger.current?.focus();
    };
    document.addEventListener("pointerdown", outside);
    window.addEventListener("keydown", escape, true);
    return () => {
      document.removeEventListener("pointerdown", outside);
      window.removeEventListener("keydown", escape, true);
    };
  }, [open]);

  useEffect(() => {
    if (open) activeOption.current?.scrollIntoView({ block: "nearest" });
  }, [open, active]);

  const choose = index => {
    onChange(options[index].value);
    setOpen(false);
    trigger.current?.focus();
  };
  const onKeyDown = event => {
    if (event.key === "Tab") { setOpen(false); return; }
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      if (event.key === "Home") setActive(0);
      else if (event.key === "End") setActive(options.length - 1);
      else setActive(open ? (active + (event.key === "ArrowDown" ? 1 : -1) + options.length) % options.length : selected);
      setOpen(true);
    } else if (open && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      choose(active);
    } else if (event.key.length === 1 && /\S/.test(event.key)) {
      const index = options.findIndex((option, index) => index > active && option.label.toLowerCase().startsWith(event.key.toLowerCase()));
      const wrapped = index < 0 ? options.findIndex(option => option.label.toLowerCase().startsWith(event.key.toLowerCase())) : index;
      if (wrapped >= 0) { event.preventDefault(); setActive(wrapped); setOpen(true); }
    }
  };

  return (
    <div className={`filter-dropdown${open ? " is-open" : ""}`} ref={root}
      onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }}>
      <span id={`${id}-label`}>{label}</span>
      <button ref={trigger} type="button" role="combobox" className="filter-dropdown-trigger"
        aria-labelledby={`${id}-label ${id}-value`} aria-haspopup="listbox" aria-expanded={open}
        aria-controls={open ? `${id}-options` : undefined}
        aria-activedescendant={open ? `${id}-option-${active}` : undefined}
        disabled={disabled} onKeyDown={onKeyDown}
        onClick={() => { setActive(selected); setOpen(current => !current); }}>
        <span id={`${id}-value`}>{options[selected].label}</span>
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4" /></svg>
      </button>
      {open && <div id={`${id}-options`} role="listbox" aria-labelledby={`${id}-label`} className="filter-dropdown-menu">
        {options.map((option, index) => (
          <div key={option.value} id={`${id}-option-${index}`} role="option"
            ref={index === active ? activeOption : undefined}
            aria-selected={option.value === value}
            className={`filter-dropdown-option${index === active ? " active" : ""}`}
            onPointerDown={event => event.preventDefault()}
            onMouseEnter={() => setActive(index)} onClick={() => choose(index)}>
            <span>{option.label}</span><span aria-hidden="true">{option.value === value ? "✓" : ""}</span>
          </div>
        ))}
      </div>}
    </div>
  );
}

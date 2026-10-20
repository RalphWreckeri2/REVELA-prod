import { useId, useLayoutEffect, useRef } from "react";
import { createPortal } from "react-dom";
import "../styles/InspectionDialog.css";

// Dispatch-only stack: leave the shared modal/animation components untouched.
const dialogs = [];
let background = null;
const activeDialog = () => dialogs.filter(dialog => !dialog.closing).at(-1);
const externalDialogOpen = () => Boolean(document.querySelector(".swal2-container"))
  || [...document.querySelectorAll('[role="dialog"][aria-modal="true"], [role="alertdialog"][aria-modal="true"]')]
    .some(node => !node.closest(".dispatch-modal") && node.getClientRects().length);

function syncLayers() {
  const active = activeDialog();
  for (const dialog of dialogs) {
    const inactive = dialog !== active;
    dialog.backdrop.inert = inactive;
    dialog.panel.setAttribute("aria-hidden", String(inactive));
    if (inactive) dialog.panel.removeAttribute("aria-modal");
    else dialog.panel.setAttribute("aria-modal", "true");
  }
  if (active) {
    const root = document.querySelector(".inspection-dispatch-page");
    if (background?.node !== root) {
      if (background) background.node.inert = background.inert;
      background = root ? { node: root, inert: root.inert } : null;
    }
    if (background) background.node.inert = true;
  } else if (background) {
    background.node.inert = background.inert;
    background = null;
  }
}

function restoreFocus(dialog) {
  const restore = () => {
    const active = activeDialog();
    if (active?.panel.contains(document.activeElement)) return;
    const usable = node => node?.isConnected && node.getClientRects().length
      && !node.closest('[inert], [hidden], [aria-hidden="true"]');
    let target = usable(dialog.returnTarget) ? dialog.returnTarget : dialog.fallback;
    if (active && !active.panel.contains(target)) target = active.heading;
    if (usable(target)) target.focus();
  };
  if (!externalDialogOpen()) {
    restore();
    return;
  }
  // SweetAlert confirmations keep their own focus; restore after they finish.
  const observer = new MutationObserver(() => {
    if (!externalDialogOpen()) {
      observer.disconnect();
      restore();
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
}

function focusableNodes(panel) {
  return [...panel.querySelectorAll('button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])')]
    .filter(node => !node.disabled && node.tabIndex >= 0 && node.getClientRects().length
      && getComputedStyle(node).visibility !== "hidden"
      && !node.closest('[inert], [hidden], [aria-hidden="true"]'));
}

export default function InspectionDialog({
  title, description, children, onClose, busy = false, isClosing = false,
  className = "", panelStyle, layer = 10000, returnFocusRef, fallbackFocusRef,
}) {
  const titleID = useId();
  const descriptionID = useId();
  const panelRef = useRef(null);
  const backdropRef = useRef(null);
  const headingRef = useRef(null);
  const entryRef = useRef(null);
  const closeRef = useRef(onClose);

  useLayoutEffect(() => {
    const entry = {
      panel: panelRef.current, backdrop: backdropRef.current, heading: headingRef.current,
      returnTarget: returnFocusRef?.current || document.activeElement,
      fallback: fallbackFocusRef?.current, closing: false, busy: false,
    };
    entryRef.current = entry;
    dialogs.push(entry);
    syncLayers();
    entry.heading.focus({ preventScroll: true });

    const onKeyDown = event => {
      if (activeDialog() !== entry || externalDialogOpen()) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        if (!entry.busy) closeRef.current();
      } else if (event.key === "Tab") {
        const nodes = focusableNodes(entry.panel);
        const first = nodes[0];
        const last = nodes.at(-1);
        if (!first) {
          event.preventDefault();
          entry.heading.focus();
        } else if (event.shiftKey && (document.activeElement === first || !nodes.includes(document.activeElement))) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && (document.activeElement === last || !entry.panel.contains(document.activeElement))) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    const onFocusIn = event => {
      if (activeDialog() === entry && !externalDialogOpen() && !entry.panel.contains(event.target)) {
        entry.heading.focus({ preventScroll: true });
      }
    };
    document.addEventListener("keydown", onKeyDown, true);
    document.addEventListener("focusin", onFocusIn);
    const observer = new MutationObserver(() => {
      if (activeDialog() === entry && !externalDialogOpen() && !entry.panel.contains(document.activeElement)) {
        entry.heading.focus({ preventScroll: true });
      }
    });
    observer.observe(entry.panel, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
      document.removeEventListener("keydown", onKeyDown, true);
      document.removeEventListener("focusin", onFocusIn);
      dialogs.splice(dialogs.indexOf(entry), 1);
      syncLayers();
      restoreFocus(entry);
      entryRef.current = null;
    };
  }, [returnFocusRef, fallbackFocusRef]);

  useLayoutEffect(() => {
    closeRef.current = onClose;
    const entry = entryRef.current;
    const reopening = entry.closing && !isClosing;
    entry.busy = busy;
    entry.closing = isClosing;
    if (reopening) {
      entry.returnTarget = returnFocusRef?.current || document.activeElement;
      entry.fallback = fallbackFocusRef?.current;
    }
    syncLayers();
    if (isClosing) restoreFocus(entry);
    else if (reopening) entry.heading.focus({ preventScroll: true });
  }, [onClose, busy, isClosing, returnFocusRef, fallbackFocusRef]);

  return createPortal(
    <div
      ref={backdropRef}
      className={`modal-backdrop dispatch-modal${isClosing ? " closing" : ""}`}
      style={{ zIndex: layer }}
      onClick={!busy && !isClosing ? onClose : undefined}
    >
      <section
        ref={panelRef}
        className={`modal-panel dispatch-dialog${className ? ` ${className}` : ""}${isClosing ? " closing" : ""}`}
        style={panelStyle}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleID}
        aria-describedby={description ? descriptionID : undefined}
        aria-busy={busy}
        tabIndex={-1}
        onClick={event => event.stopPropagation()}
      >
        <header className="dispatch-dialog-header">
          <h2 id={titleID} ref={headingRef} tabIndex={-1}>{title}</h2>
          <button className="modal-close-btn" type="button" aria-label="Close dialog" onClick={onClose} disabled={busy}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="m6 6 12 12M18 6 6 18" />
            </svg>
          </button>
        </header>
        {description && <p id={descriptionID} className="dispatch-dialog-description">{description}</p>}
        {children}
      </section>
    </div>,
    document.body,
  );
}

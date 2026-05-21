import { ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Close } from "@/components/icons";

interface Props {
  /** Controlled open/close. */
  open: boolean;
  /** Closes the drawer (Esc, overlay click, X button). */
  onClose: () => void;
  /** Drawer header — typically the entity being acted on. */
  title: ReactNode;
  /** Optional sub-line below the title (e.g. the filename in monospace). */
  subtitle?: ReactNode;
  /** Body content — forms, lists, descriptions. */
  children: ReactNode;
  /** Optional footer — typically a row of buttons. */
  footer?: ReactNode;
}

/**
 * Right-side drawer.
 *
 * Built on `@radix-ui/react-dialog` so we get focus trap + scroll lock +
 * escape handling + ARIA attributes for free. Styling lives in app.css
 * (`.drawer`, `.drawer-header`, `.drawer-body`, `.drawer-footer`).
 *
 * Used by the bigger forms (Share, Tags, Versions, Override). Centered
 * modals (Preview, confirmation prompts) stay as the old `<div>` pattern
 * or use the `.modal` class.
 */
export default function Drawer({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
}: Props) {
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="drawer-overlay" />
        <Dialog.Content className="drawer" aria-describedby={undefined}>
          <header className="drawer-header">
            <div>
              <Dialog.Title asChild>
                <div className="drawer-title">{title}</div>
              </Dialog.Title>
              {subtitle && <div className="drawer-subtitle">{subtitle}</div>}
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className="btn btn-ghost btn-icon btn-sm"
                aria-label="Close"
              >
                <Close size={16} />
              </button>
            </Dialog.Close>
          </header>
          <div className="drawer-body">{children}</div>
          {footer && <footer className="drawer-footer">{footer}</footer>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

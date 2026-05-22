import { useToastList } from "@/state/toast";
import { AlertTriangle, CheckCircle2, Close, Info, XCircle } from "@/components/icons";

const KIND_CLASS = {
  info: "toast",
  success: "toast toast-success",
  warning: "toast toast-warning",
  error: "toast toast-error",
} as const;

/**
 * Bottom-right toast surface. Reads the active toasts from the
 * ToastProvider context and renders them. One host instance lives in
 * `main.tsx` so toasts work across the whole app.
 */
export default function ToastHost() {
  const { toasts, dismiss } = useToastList();

  if (toasts.length === 0) return null;

  return (
    <div className="toast-host" role="status" aria-live="polite">
      {toasts.map((t) => {
        const Icon =
          t.kind === "success"
            ? CheckCircle2
            : t.kind === "warning"
              ? AlertTriangle
              : t.kind === "error"
                ? XCircle
                : Info;
        const color =
          t.kind === "success"
            ? "var(--color-success)"
            : t.kind === "warning"
              ? "var(--color-warning)"
              : t.kind === "error"
                ? "var(--color-danger)"
                : "var(--color-accent)";
        return (
          <div key={t.id} className={KIND_CLASS[t.kind]}>
            <Icon size={16} style={{ color, flexShrink: 0, marginTop: 2 }} />
            <div className="toast-body">
              <div className="toast-title">{t.title}</div>
              {t.detail && <div className="toast-detail">{t.detail}</div>}
            </div>
            <button
              type="button"
              className="btn btn-ghost btn-icon btn-sm"
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss"
            >
              <Close size={14} />
            </button>
          </div>
        );
      })}
    </div>
  );
}

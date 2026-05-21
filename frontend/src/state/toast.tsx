import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react";

export type ToastKind = "info" | "success" | "warning" | "error";

export interface ToastEntry {
  id: number;
  kind: ToastKind;
  title: string;
  detail?: string;
}

interface ToastContextValue {
  toasts: ToastEntry[];
  show: (kind: ToastKind, title: string, detail?: string) => void;
  dismiss: (id: number) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const AUTO_DISMISS_MS = 4_000;

/**
 * Toast notification provider.
 *
 * Replaces the scattered `alert()` calls + inline error banners. Caller
 * obtains the hooks via `useToast()` and fires:
 *   toast.success("Uploaded report.txt")
 *   toast.error("Upload failed", "Quota exceeded")
 *
 * Toasts auto-dismiss after 4 s, or sooner via the close button on the
 * ToastHost component. Rendered through ToastHost, which lives at the
 * bottom of the React tree.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastEntry[]>([]);
  const idRef = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const show = useCallback(
    (kind: ToastKind, title: string, detail?: string) => {
      const id = ++idRef.current;
      setToasts((prev) => [...prev, { id, kind, title, detail }]);
      window.setTimeout(() => dismiss(id), AUTO_DISMISS_MS);
    },
    [dismiss],
  );

  const value = useMemo(
    () => ({ toasts, show, dismiss }),
    [toasts, show, dismiss],
  );

  return (
    <ToastContext.Provider value={value}>{children}</ToastContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return {
    info: (title: string, detail?: string) => ctx.show("info", title, detail),
    success: (title: string, detail?: string) =>
      ctx.show("success", title, detail),
    warning: (title: string, detail?: string) =>
      ctx.show("warning", title, detail),
    error: (title: string, detail?: string) => ctx.show("error", title, detail),
  };
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToastList() {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToastList must be used within a ToastProvider");
  }
  return ctx;
}

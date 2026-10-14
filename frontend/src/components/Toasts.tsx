import React, { createContext, useCallback, useContext, useMemo, useState } from "react";
import { AlertTriangle, Check, Info, Undo2, X } from "lucide-react";

export type ToastTone = "info" | "success" | "danger";

export interface Toast {
  id: number;
  tone: ToastTone;
  message: string;
  /** Optional single action, used for "undo the decision I just made". */
  action?: { label: string; run: () => void };
}

interface ToastApi {
  push: (toast: Omit<Toast, "id">) => void;
  dismiss: (id: number) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

let nextId = 1;

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback(
    (toast: Omit<Toast, "id">) => {
      const id = nextId++;
      setToasts((prev) => [...prev.slice(-3), { ...toast, id }]);
      window.setTimeout(() => dismiss(id), toast.action ? 9000 : 4500);
    },
    [dismiss],
  );

  const api = useMemo(() => ({ push, dismiss }), [push, dismiss]);

  const icons: Record<ToastTone, React.ReactNode> = {
    info: <Info className="h-3.5 w-3.5 text-accent" />,
    success: <Check className="h-3.5 w-3.5 text-fresh" />,
    danger: <AlertTriangle className="h-3.5 w-3.5 text-dead" />,
  };

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        className="pointer-events-none fixed bottom-4 left-1/2 z-[70] flex w-[min(92vw,26rem)] -translate-x-1/2 flex-col gap-2"
        role="status"
        aria-live="polite"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className="pointer-events-auto flex items-center gap-2.5 rounded-card border border-line bg-raised px-3.5 py-2.5 shadow-pop animate-drawer-up"
          >
            {icons[toast.tone]}
            <span className="min-w-0 flex-1 text-sm text-ink">{toast.message}</span>
            {toast.action && (
              <button
                type="button"
                onClick={() => {
                  toast.action?.run();
                  dismiss(toast.id);
                }}
                className="btn btn-sm btn-outline shrink-0"
              >
                <Undo2 className="h-3 w-3" />
                {toast.action.label}
              </button>
            )}
            <button
              type="button"
              onClick={() => dismiss(toast.id)}
              className="btn btn-sm btn-quiet shrink-0 px-1.5"
              aria-label="Dismiss"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
};

export function useToast(): ToastApi {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside <ToastProvider>");
  return context;
}

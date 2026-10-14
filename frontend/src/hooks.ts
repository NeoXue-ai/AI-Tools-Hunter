import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { Language, Theme } from "./i18n";

/** localStorage that never throws (private mode, disabled storage). */
function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStored(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* storage is a nicety, not a requirement */
  }
}

export function usePersistentState<T extends string>(
  key: string,
  fallback: T,
  isValid: (value: string) => value is T,
): [T, (next: T) => void] {
  const [value, setValue] = useState<T>(() => {
    const stored = readStored(key);
    return stored !== null && isValid(stored) ? stored : fallback;
  });

  const update = useCallback(
    (next: T) => {
      setValue(next);
      writeStored(key, next);
    },
    [key],
  );

  return [value, update];
}

const isTheme = (value: string): value is Theme => value === "light" || value === "dark";
const isLanguage = (value: string): value is Language => value === "zh" || value === "en";

/**
 * The palette lives in CSS variables; the hook only owns the `.dark` class and
 * the OS-level preference for first-time visitors.
 */
export function useTheme() {
  const [theme, setTheme] = usePersistentState<Theme>(
    "dh.theme",
    prefersDark() ? "dark" : "light",
    isTheme,
  );

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.style.colorScheme = theme;
  }, [theme]);

  const toggle = useCallback(
    () => setTheme(theme === "dark" ? "light" : "dark"),
    [theme, setTheme],
  );

  return { theme, setTheme, toggle };
}

function prefersDark(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function useLanguage() {
  const [lang, setLang] = usePersistentState<Language>("dh.lang", "zh", isLanguage);
  const toggle = useCallback(() => setLang(lang === "zh" ? "en" : "zh"), [lang, setLang]);
  return { lang, setLang, toggle };
}

export function useActorId() {
  const [actorId, setActorId] = usePersistentState<string>("dh.actor", "", (v): v is string => true);
  return { actorId, setActorId };
}

// ── Routing ─────────────────────────────────────────────────────────────────

export interface Route {
  name: "queue" | "candidate";
  candidateId?: string;
}

const QUEUE_ROUTE: Route = { name: "queue" };

/**
 * Path routing, not hash routing: the FastAPI shell already serves
 * `/review/{id}`, so a deep link survives a refresh and stays shareable.
 */
export function useRoute(): { route: Route; push: (next: Route) => void } {
  const [route, setRoute] = useState<Route>(() => parsePath(window.location.pathname));

  useEffect(() => {
    const onPop = () => setRoute(parsePath(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const push = useCallback((next: Route) => {
    const path = next.name === "candidate" && next.candidateId
      ? `/review/${encodeURIComponent(next.candidateId)}`
      : "/";
    if (path !== window.location.pathname) {
      window.history.pushState({}, "", path);
    }
    setRoute(next);
  }, []);

  return { route, push };
}

function parsePath(pathname: string): Route {
  const match = pathname.match(/^\/review\/([^/]+)\/?$/);
  if (match) {
    try {
      return { name: "candidate", candidateId: decodeURIComponent(match[1]) };
    } catch {
      return QUEUE_ROUTE;
    }
  }
  return QUEUE_ROUTE;
}

// ── Clock ───────────────────────────────────────────────────────────────────

/**
 * Relative timestamps would go stale on a long-lived review session, so the
 * console re-renders on a slow tick instead of trusting the load time.
 */
export function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);
  return now;
}

// ── Keyboard ────────────────────────────────────────────────────────────────

const TYPING_TAGS = new Set(["INPUT", "TEXTAREA", "SELECT"]);

export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return TYPING_TAGS.has(target.tagName) || target.isContentEditable;
}

export interface HotkeyHandlers {
  [combo: string]: (event: KeyboardEvent) => void;
}

/**
 * Global hotkeys. `combo` is either a single key (`"j"`) or a modifier form
 * (`"mod+k"`, `"shift+/"`). Keys are matched case-insensitively and skipped
 * while the user is typing.
 */
export function useHotkeys(handlers: HotkeyHandlers, enabled = true) {
  const ref = useRef(handlers);
  ref.current = handlers;

  useEffect(() => {
    if (!enabled) return;
    const onKeyDown = (event: KeyboardEvent) => {
      const typing = isTypingTarget(event.target);
      const key = event.key.toLowerCase();
      const mod = event.metaKey || event.ctrlKey;

      const candidates = mod ? [`mod+${key}`, key] : [key];
      for (const combo of candidates) {
        const handler = ref.current[combo];
        if (!handler) continue;
        // Plain single-key shortcuts must not fire while typing; modifier
        // combos (mod+k) are allowed everywhere.
        if (typing && !mod) continue;
        if (event.repeat && !mod) continue;
        handler(event);
        return;
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [enabled]);
}

/** Escape-to-dismiss plus body scroll lock, shared by every overlay. */
export function useDismissable(open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown, true);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKeyDown, true);
      document.body.style.overflow = previous;
    };
  }, [open, onClose]);
}

// ── Async ───────────────────────────────────────────────────────────────────

export interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

/** A minimal fetch-on-mount hook with an explicit reload for manual retries. */
export function useAsync<T>(
  loader: () => Promise<T>,
  deps: readonly unknown[],
): AsyncState<T> & { reload: () => void } {
  const [state, setState] = useState<AsyncState<T>>({
    data: null,
    error: null,
    loading: true,
  });
  const [nonce, setNonce] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    let alive = true;
    setState((prev) => ({ ...prev, loading: true, error: null }));
    loaderRef
      .current()
      .then((data) => {
        if (alive) setState({ data, error: null, loading: false });
      })
      .catch((error: unknown) => {
        if (alive) {
          setState({
            data: null,
            error: error instanceof Error ? error.message : String(error),
            loading: false,
          });
        }
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return useMemo(() => ({ ...state, reload }), [state, reload]);
}

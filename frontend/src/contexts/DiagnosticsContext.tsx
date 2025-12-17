/* eslint-disable react-refresh/only-export-components */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { DIAGNOSTIC_ERROR_EVENT, diagnostics, type DiagnosticErrorPayload, type DiagnosticsEntry } from '../utils/diagnostics';

export type DiagnosticsContextValue = {
  isOpen: boolean;
  open: (payload?: DiagnosticErrorPayload) => void;
  close: () => void;
  clear: () => void;
  getEntries: () => DiagnosticsEntry[];
  currentError: DiagnosticErrorPayload | null;
};

const DiagnosticsContext = createContext<DiagnosticsContextValue | null>(null);

const signatureFor = (payload: DiagnosticErrorPayload): string => {
  const base = {
    title: payload.title,
    message: payload.message,
    kind: payload.kind,
  };
  try {
    return JSON.stringify(base);
  } catch {
    return `${payload.title}:${payload.message}`;
  }
};

export function DiagnosticsProvider({ children }: { children: ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const [currentError, setCurrentError] = useState<DiagnosticErrorPayload | null>(null);
  const lastShownRef = useRef<{ sig: string; ts: number } | null>(null);

  const open = useCallback((payload?: DiagnosticErrorPayload) => {
    if (payload) {
      setCurrentError(payload);
    } else {
      setCurrentError(null);
    }
    setIsOpen(true);
  }, []);

  const close = useCallback(() => {
    setIsOpen(false);
  }, []);

  const clear = useCallback(() => {
    diagnostics.clear();
  }, []);

  const getEntries = useCallback(() => diagnostics.getEntries(), []);

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent).detail as DiagnosticErrorPayload | undefined;
      if (!detail) return;

      // Deduplicate noisy errors (same signature within 5s)
      const sig = signatureFor(detail);
      const now = Date.now();
      const last = lastShownRef.current;
      if (last && last.sig === sig && now - last.ts < 5000) {
        return;
      }
      lastShownRef.current = { sig, ts: now };

      setCurrentError(detail);
      setIsOpen(true);
    };

    window.addEventListener(DIAGNOSTIC_ERROR_EVENT, handler as EventListener);
    return () => window.removeEventListener(DIAGNOSTIC_ERROR_EVENT, handler as EventListener);
  }, []);

  const value = useMemo<DiagnosticsContextValue>(
    () => ({
      isOpen,
      open,
      close,
      clear,
      getEntries,
      currentError,
    }),
    [close, clear, currentError, getEntries, isOpen, open]
  );

  return <DiagnosticsContext.Provider value={value}>{children}</DiagnosticsContext.Provider>;
}

export const useDiagnostics = (): DiagnosticsContextValue => {
  const ctx = useContext(DiagnosticsContext);
  if (!ctx) {
    throw new Error('useDiagnostics must be used within DiagnosticsProvider');
  }
  return ctx;
};

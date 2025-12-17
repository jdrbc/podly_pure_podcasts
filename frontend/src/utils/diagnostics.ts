export type DiagnosticsLevel = 'debug' | 'info' | 'warn' | 'error';

export type DiagnosticsEntry = {
  ts: number;
  level: DiagnosticsLevel;
  message: string;
  data?: unknown;
};

export type DiagnosticsState = {
  v: 1;
  entries: DiagnosticsEntry[];
};

export type DiagnosticErrorPayload = {
  title: string;
  message: string;
  kind?: 'network' | 'http' | 'app' | 'unknown';
  details?: unknown;
};

const STORAGE_KEY = 'podly.diagnostics.v1';
const MAX_ENTRIES = 200;
const MAX_ENTRY_MESSAGE_CHARS = 500;
const MAX_JSON_CHARS = 120_000;

const SENSITIVE_KEY_RE = /(authorization|cookie|set-cookie|token|access[_-]?token|refresh[_-]?token|id[_-]?token|api[_-]?key|secret|password|session)/i;
const SENSITIVE_VALUE_REPLACEMENT = '[REDACTED]';

const redactString = (value: string): string => {
  let v = value;
  // Authorization headers / bearer tokens
  v = v.replace(/\bBearer\s+([A-Za-z0-9\-._~+/]+=*)/gi, 'Bearer [REDACTED]');
  v = v.replace(/\bBasic\s+([A-Za-z0-9+/=]+)\b/gi, 'Basic [REDACTED]');

  // Common query params
  v = v.replace(/([?&](?:token|access_token|refresh_token|id_token|api_key|key|password)=)([^&#]+)/gi, '$1[REDACTED]');

  // JSON-ish fields in strings
  v = v.replace(/("(?:access_token|refresh_token|id_token|token|api_key|password)"\s*:\s*")([^"]+)(")/gi, '$1[REDACTED]$3');

  return v;
};

const sanitize = (input: unknown, depth = 0): unknown => {
  if (depth > 6) return '[Truncated]';
  if (input == null) return input;

  if (typeof input === 'string') return redactString(input);
  if (typeof input === 'number' || typeof input === 'boolean') return input;

  if (Array.isArray(input)) {
    return input.slice(0, 50).map((v) => sanitize(v, depth + 1));
  }

  if (typeof input === 'object') {
    const obj = input as Record<string, unknown>;
    const out: Record<string, unknown> = {};
    const keys = Object.keys(obj).slice(0, 50);
    for (const key of keys) {
      const value = obj[key];
      if (SENSITIVE_KEY_RE.test(key)) {
        out[key] = SENSITIVE_VALUE_REPLACEMENT;
      } else {
        out[key] = sanitize(value, depth + 1);
      }
    }
    return out;
  }

  return String(input);
};

const safeJsonStringify = (value: unknown): string => {
  try {
    const json = JSON.stringify(value);
    if (json.length <= MAX_JSON_CHARS) return json;
    return json.slice(0, MAX_JSON_CHARS) + '\n...[truncated]';
  } catch {
    return '[Unserializable]';
  }
};

const loadState = (): DiagnosticsState => {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return { v: 1, entries: [] };
    const parsed = JSON.parse(raw) as DiagnosticsState;
    if (parsed?.v !== 1 || !Array.isArray(parsed.entries)) {
      return { v: 1, entries: [] };
    }
    return parsed;
  } catch {
    return { v: 1, entries: [] };
  }
};

const saveState = (state: DiagnosticsState) => {
  try {
    const raw = safeJsonStringify(state);
    // Prevent sessionStorage bloat
    if (raw.length > MAX_JSON_CHARS) {
      const trimmed = { v: 1 as const, entries: state.entries.slice(-Math.floor(MAX_ENTRIES / 2)) };
      sessionStorage.setItem(STORAGE_KEY, safeJsonStringify(trimmed));
      return;
    }
    sessionStorage.setItem(STORAGE_KEY, raw);
  } catch {
    // ignore
  }
};

export const DIAGNOSTIC_UPDATED_EVENT = 'podly:diagnostic-updated';

export const diagnostics = {
  add: (level: DiagnosticsLevel, message: string, data?: unknown) => {
    const sanitizedMessage = redactString(message).slice(0, MAX_ENTRY_MESSAGE_CHARS);
    const entry: DiagnosticsEntry = {
      ts: Date.now(),
      level,
      message: sanitizedMessage,
      data: data === undefined ? undefined : sanitize(data),
    };

    const state = loadState();
    const next = [...state.entries, entry].slice(-MAX_ENTRIES);
    saveState({ v: 1, entries: next });

    try {
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new Event(DIAGNOSTIC_UPDATED_EVENT));
      }
    } catch {
      // ignore
    }
  },

  getEntries: (): DiagnosticsEntry[] => {
    return loadState().entries;
  },

  clear: () => {
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
  },

  sanitize,
};

export const DIAGNOSTIC_ERROR_EVENT = 'podly:diagnostic-error';

export const emitDiagnosticError = (payload: DiagnosticErrorPayload) => {
  const safePayload = diagnostics.sanitize(payload) as DiagnosticErrorPayload;
  diagnostics.add('error', safePayload.title + ': ' + safePayload.message, safePayload);
  try {
    window.dispatchEvent(new CustomEvent(DIAGNOSTIC_ERROR_EVENT, { detail: safePayload }));
  } catch {
    // ignore
  }
};

let consoleWrapped = false;

export const initFrontendDiagnostics = () => {
  if (typeof window === 'undefined') return;

  if (!consoleWrapped) {
    consoleWrapped = true;
    const wrap = (level: DiagnosticsLevel, original: (...args: unknown[]) => void) =>
      (...args: unknown[]) => {
        try {
          const msg = args
            .map((a) => (typeof a === 'string' ? a : safeJsonStringify(diagnostics.sanitize(a))))
            .join(' ');
          diagnostics.add(level, msg);
        } catch {
          // ignore
        }
        original(...args);
      };

    console.log = wrap('info', console.log.bind(console));
    console.info = wrap('info', console.info.bind(console));
    console.warn = wrap('warn', console.warn.bind(console));
    console.error = wrap('error', console.error.bind(console));
  }

  window.addEventListener('error', (event) => {
    emitDiagnosticError({
      title: 'Unhandled error',
      message: event.message || 'Unknown error',
      kind: 'app',
      details: {
        filename: event.filename,
        lineno: event.lineno,
        colno: event.colno,
      },
    });
  });

  window.addEventListener('unhandledrejection', (event) => {
    const reason = (event as PromiseRejectionEvent).reason;
    emitDiagnosticError({
      title: 'Unhandled promise rejection',
      message: typeof reason === 'string' ? reason : 'Promise rejected',
      kind: 'app',
      details: reason,
    });
  });
};

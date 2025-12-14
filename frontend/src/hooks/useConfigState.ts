import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { configApi } from '../services/api';
import { toast } from 'react-hot-toast';
import type {
  CombinedConfig,
  ConfigResponse,
  EnvOverrideEntry,
  EnvOverrideMap,
  LLMConfig,
  WhisperConfig,
} from '../types';

const DEFAULT_ENV_HINTS: Record<string, EnvOverrideEntry> = {
  'groq.api_key': { env_var: 'GROQ_API_KEY' },
  'llm.llm_api_key': { env_var: 'LLM_API_KEY' },
  'llm.llm_model': { env_var: 'LLM_MODEL' },
  'llm.openai_base_url': { env_var: 'OPENAI_BASE_URL' },
  'whisper.whisper_type': { env_var: 'WHISPER_TYPE' },
  'whisper.api_key': { env_var: 'WHISPER_REMOTE_API_KEY' },
  'whisper.base_url': { env_var: 'WHISPER_REMOTE_BASE_URL' },
  'whisper.model': { env_var: 'WHISPER_REMOTE_MODEL' },
  'whisper.timeout_sec': { env_var: 'WHISPER_REMOTE_TIMEOUT_SEC' },
  'whisper.chunksize_mb': { env_var: 'WHISPER_REMOTE_CHUNKSIZE_MB' },
  'whisper.max_retries': { env_var: 'GROQ_MAX_RETRIES' },
};

const getValueAtPath = (obj: unknown, path: string): unknown => {
  if (!obj || typeof obj !== 'object') {
    return undefined;
  }
  return path.split('.').reduce<unknown>((acc, key) => {
    if (!acc || typeof acc !== 'object') {
      return undefined;
    }
    return (acc as Record<string, unknown>)[key];
  }, obj);
};

const valuesDiffer = (a: unknown, b: unknown): boolean => {
  if (a === b) {
    return false;
  }
  const aEmpty = a === null || a === undefined || a === '';
  const bEmpty = b === null || b === undefined || b === '';
  if (aEmpty && bEmpty) {
    return false;
  }
  return true;
};

export interface ConnectionStatus {
  status: 'loading' | 'ok' | 'error';
  message: string;
  error: string;
}

export interface UseConfigStateReturn {
  // Data
  pending: CombinedConfig | null;
  configData: CombinedConfig | undefined;
  envOverrides: EnvOverrideMap;
  isLoading: boolean;

  // Status
  llmStatus: ConnectionStatus;
  whisperStatus: ConnectionStatus;
  hasEdits: boolean;
  localWhisperAvailable: boolean | null;
  isSaving: boolean;

  // Actions
  setField: (path: string[], value: unknown) => void;
  updatePending: (
    transform: (prevConfig: CombinedConfig) => CombinedConfig,
    markDirty?: boolean
  ) => void;
  probeConnections: () => Promise<void>;
  handleSave: () => void;
  refetch: () => void;
  setHasEdits: (value: boolean) => void;

  // Helpers
  getEnvHint: (path: string, fallback?: EnvOverrideEntry) => EnvOverrideEntry | undefined;
  getWhisperApiKey: (w: WhisperConfig | undefined) => string;

  // Recommended defaults
  groqRecommendedModel: string;
  groqRecommendedWhisper: string;

  // Env warning modal
  envWarningPaths: string[];
  showEnvWarning: boolean;
  handleConfirmEnvWarning: () => void;
  handleDismissEnvWarning: () => void;

  // Whisper type change handler
  handleWhisperTypeChange: (nextType: 'local' | 'remote' | 'groq') => void;

  // Groq quick setup mutation
  applyGroqKey: (key: string) => Promise<void>;
  isApplyingGroqKey: boolean;
}

export function useConfigState(): UseConfigStateReturn {
  const { data, isLoading, refetch } = useQuery<ConfigResponse>({
    queryKey: ['config'],
    queryFn: configApi.getConfig,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const configData = data?.config;
  const envOverrides = useMemo<EnvOverrideMap>(() => data?.env_overrides ?? {}, [data]);

  const getEnvHint = useCallback(
    (path: string, fallback?: EnvOverrideEntry) =>
      envOverrides[path] ?? fallback ?? DEFAULT_ENV_HINTS[path],
    [envOverrides]
  );

  const [pending, setPending] = useState<CombinedConfig | null>(null);
  const [hasEdits, setHasEdits] = useState(false);
  const [localWhisperAvailable, setLocalWhisperAvailable] = useState<boolean | null>(null);

  // Connection statuses
  const [llmStatus, setLlmStatus] = useState<ConnectionStatus>({
    status: 'loading',
    message: '',
    error: '',
  });
  const [whisperStatus, setWhisperStatus] = useState<ConnectionStatus>({
    status: 'loading',
    message: '',
    error: '',
  });

  // Env warning modal state
  const [envWarningPaths, setEnvWarningPaths] = useState<string[]>([]);
  const [showEnvWarning, setShowEnvWarning] = useState(false);

  const initialProbeDone = useRef(false);
  const groqRecommendedModel = useMemo(() => 'groq/openai/gpt-oss-120b', []);
  const groqRecommendedWhisper = useMemo(() => 'whisper-large-v3-turbo', []);

  const getWhisperApiKey = (w: WhisperConfig | undefined): string => {
    if (!w) return '';
    if (w.whisper_type === 'remote') return w.api_key ?? '';
    if (w.whisper_type === 'groq') return w.api_key ?? '';
    return '';
  };

  const updatePending = useCallback(
    (transform: (prevConfig: CombinedConfig) => CombinedConfig, markDirty: boolean = true) => {
      let updated = false;
      setPending((prevConfig) => {
        if (!prevConfig) {
          return prevConfig;
        }
        const nextConfig = transform(prevConfig);
        if (nextConfig === prevConfig) {
          return prevConfig;
        }
        updated = true;
        return nextConfig;
      });

      if (updated && markDirty) {
        setHasEdits(true);
      }
    },
    []
  );

  const setField = useCallback(
    (path: string[], value: unknown) => {
      updatePending((prevConfig) => {
        const prevRecord = prevConfig as unknown as Record<string, unknown>;
        const lastIndex = path.length - 1;

        let existingParent: Record<string, unknown> | null = prevRecord;
        for (let i = 0; i < lastIndex; i++) {
          const key = path[i];
          const rawNext: unknown = existingParent?.[key];
          const nextParent: Record<string, unknown> | null =
            rawNext && typeof rawNext === 'object'
              ? (rawNext as Record<string, unknown>)
              : null;
          if (!nextParent) {
            existingParent = null;
            break;
          }
          existingParent = nextParent;
        }

        if (existingParent) {
          const currentValue = existingParent[path[lastIndex]];
          if (Object.is(currentValue, value)) {
            return prevConfig;
          }
        }

        const next: Record<string, unknown> = { ...prevRecord };

        let cursor: Record<string, unknown> = next;
        let sourceCursor: Record<string, unknown> = prevRecord;

        for (let i = 0; i < lastIndex; i++) {
          const key = path[i];
          const currentSource = (sourceCursor?.[key] as Record<string, unknown>) ?? {};
          const clonedChild: Record<string, unknown> = { ...currentSource };
          cursor[key] = clonedChild;
          cursor = clonedChild;
          sourceCursor = currentSource;
        }

        cursor[path[lastIndex]] = value;

        return next as unknown as CombinedConfig;
      });
    },
    [updatePending]
  );

  // Initialize pending from config data
  useEffect(() => {
    if (!configData) {
      return;
    }
    setPending((prev) => {
      if (prev === null) {
        return configData;
      }
      if (hasEdits) {
        return prev;
      }
      return configData;
    });
  }, [configData, hasEdits]);

  // Probe connections
  const probeConnections = async () => {
    if (!pending) return;
    setLlmStatus({ status: 'loading', message: '', error: '' });
    setWhisperStatus({ status: 'loading', message: '', error: '' });

    try {
      const [llmRes, whisperRes] = await Promise.all([
        configApi.testLLM({ llm: pending.llm as LLMConfig }),
        configApi.testWhisper({ whisper: pending.whisper as WhisperConfig }),
      ]);

      if (llmRes?.ok) {
        setLlmStatus({
          status: 'ok',
          message: llmRes.message || 'LLM connection OK',
          error: '',
        });
      } else {
        setLlmStatus({
          status: 'error',
          message: '',
          error: llmRes?.error || 'LLM connection failed',
        });
      }

      if (whisperRes?.ok) {
        setWhisperStatus({
          status: 'ok',
          message: whisperRes.message || 'Whisper connection OK',
          error: '',
        });
      } else {
        setWhisperStatus({
          status: 'error',
          message: '',
          error: whisperRes?.error || 'Whisper test failed',
        });
      }
    } catch (err: unknown) {
      const e = err as {
        response?: { data?: { error?: string; message?: string } };
        message?: string;
      };
      const msg =
        e?.response?.data?.error ||
        e?.response?.data?.message ||
        e?.message ||
        'Connection test failed';
      setLlmStatus({ status: 'error', message: '', error: msg });
      setWhisperStatus({ status: 'error', message: '', error: msg });
    }
  };

  // Initial probe
  useEffect(() => {
    if (!pending || initialProbeDone.current) return;
    initialProbeDone.current = true;
    void probeConnections();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending]);

  // Probe whisper capabilities
  useEffect(() => {
    let cancelled = false;
    configApi
      .getWhisperCapabilities()
      .then((res) => {
        if (!cancelled) setLocalWhisperAvailable(!!res.local_available);
      })
      .catch(() => {
        if (!cancelled) setLocalWhisperAvailable(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // If local is unavailable but selected, switch to safe default
  useEffect(() => {
    if (!pending || localWhisperAvailable !== false) return;
    const currentType = pending.whisper.whisper_type;
    if (currentType === 'local') {
      setField(['whisper', 'whisper_type'], 'remote');
    }
  }, [localWhisperAvailable, pending, setField]);

  // Save mutation
  const saveMutation = useMutation({
    mutationFn: async () => {
      return configApi.updateConfig((pending ?? {}) as Partial<CombinedConfig>);
    },
    onSuccess: () => {
      setHasEdits(false);
      refetch();
    },
  });

  const saveToastMessages = {
    loading: 'Saving changes...',
    success: 'Configuration saved',
    error: (err: unknown) => {
      if (typeof err === 'object' && err !== null) {
        const e = err as {
          response?: { data?: { error?: string; details?: string; message?: string } };
          message?: string;
        };
        return (
          e.response?.data?.message ||
          e.response?.data?.error ||
          e.response?.data?.details ||
          e.message ||
          'Failed to save configuration'
        );
      }
      return 'Failed to save configuration';
    },
  } as const;

  const getEnvManagedConflicts = (): string[] => {
    if (!pending || !configData) {
      return [];
    }
    return Object.keys(envOverrides).filter((path) => {
      const baseline = getValueAtPath(configData, path);
      const current = getValueAtPath(pending, path);
      return valuesDiffer(current, baseline);
    });
  };

  const triggerSaveMutation = () => {
    toast.promise(saveMutation.mutateAsync(), saveToastMessages);
  };

  const handleSave = () => {
    if (saveMutation.isPending) {
      return;
    }
    const envConflicts = getEnvManagedConflicts();
    if (envConflicts.length > 0) {
      setEnvWarningPaths(envConflicts);
      setShowEnvWarning(true);
      return;
    }
    triggerSaveMutation();
  };

  const handleConfirmEnvWarning = () => {
    setShowEnvWarning(false);
    triggerSaveMutation();
  };

  const handleDismissEnvWarning = () => {
    setShowEnvWarning(false);
    setEnvWarningPaths([]);
  };

  // Whisper type change handler
  const handleWhisperTypeChange = (nextType: 'local' | 'remote' | 'groq') => {
    updatePending((prevConfig) => {
      const prevWhisper = {
        ...(prevConfig.whisper as unknown as Record<string, unknown>),
      };
      const prevModelRaw = (prevWhisper?.model as string | undefined) ?? '';
      const prevModel = String(prevModelRaw).toLowerCase();

      const isNonGroqDefault =
        prevModel === 'base' || prevModel === 'base.en' || prevModel === 'whisper-1';
      const isDeprecatedGroq = prevModel === 'distil-whisper-large-v3-en';

      let nextModel: string | undefined = prevWhisper?.model as string | undefined;

      if (nextType === 'groq') {
        if (!nextModel || isNonGroqDefault || isDeprecatedGroq) {
          nextModel = 'whisper-large-v3-turbo';
        }
      } else if (nextType === 'remote') {
        if (!nextModel || prevModel === 'base' || prevModel === 'base.en') {
          nextModel = 'whisper-1';
        }
      } else if (nextType === 'local') {
        if (!nextModel || prevModel === 'whisper-1' || prevModel.startsWith('whisper-large')) {
          nextModel = 'base.en';
        }
      }

      const nextWhisper: Record<string, unknown> = {
        ...prevWhisper,
        whisper_type: nextType,
      };

      if (nextType === 'groq') {
        nextWhisper.model = nextModel ?? 'whisper-large-v3-turbo';
        nextWhisper.language = (prevWhisper.language as string | undefined) || 'en';
        delete nextWhisper.base_url;
        delete nextWhisper.timeout_sec;
        delete nextWhisper.chunksize_mb;
      } else if (nextType === 'remote') {
        nextWhisper.model = nextModel ?? 'whisper-1';
        nextWhisper.language = (prevWhisper.language as string | undefined) || 'en';
      } else if (nextType === 'local') {
        nextWhisper.model = nextModel ?? 'base.en';
        delete nextWhisper.api_key;
      } else if (nextType === 'test') {
        delete nextWhisper.model;
        delete nextWhisper.api_key;
      }

      return {
        ...prevConfig,
        whisper: nextWhisper as unknown as WhisperConfig,
      } as CombinedConfig;
    });
  };

  // Groq key mutation
  const applyGroqKeyMutation = useMutation({
    mutationFn: async (key: string) => {
      const next = {
        llm: {
          ...(pending?.llm as LLMConfig),
          llm_api_key: key,
          llm_model: groqRecommendedModel,
        },
        whisper: {
          whisper_type: 'groq',
          api_key: key,
          model: groqRecommendedWhisper,
          language: 'en',
          max_retries: 3,
        },
      } as Partial<CombinedConfig>;

      updatePending((prevConfig) => ({
        ...prevConfig,
        llm: next.llm as LLMConfig,
        whisper: next.whisper as WhisperConfig,
      }));

      const [llmRes, whisperRes] = await Promise.all([
        configApi.testLLM({ llm: next.llm as LLMConfig }),
        configApi.testWhisper({ whisper: next.whisper as WhisperConfig }),
      ]);
      if (!llmRes?.ok) throw new Error(llmRes?.error || 'LLM test failed');
      if (!whisperRes?.ok) throw new Error(whisperRes?.error || 'Whisper test failed');

      return await configApi.updateConfig(next);
    },
    onSuccess: () => {
      setHasEdits(false);
      refetch();
      toast.success('Groq key verified and saved. Defaults applied.');
      setLlmStatus({ status: 'ok', message: 'LLM connection OK', error: '' });
      setWhisperStatus({ status: 'ok', message: 'Whisper connection OK', error: '' });
    },
  });

  const applyGroqKey = async (key: string) => {
    await toast.promise(applyGroqKeyMutation.mutateAsync(key), {
      loading: 'Verifying Groq key and applying defaults...',
      success: 'Groq configured successfully',
      error: (err: unknown) => {
        const e = err as {
          response?: { data?: { error?: string; message?: string } };
          message?: string;
        };
        return (
          e?.response?.data?.error ||
          e?.response?.data?.message ||
          e?.message ||
          'Failed to configure Groq'
        );
      },
    });
  };

  return {
    // Data
    pending,
    configData,
    envOverrides,
    isLoading,

    // Status
    llmStatus,
    whisperStatus,
    hasEdits,
    localWhisperAvailable,
    isSaving: saveMutation.isPending,

    // Actions
    setField,
    updatePending,
    probeConnections,
    handleSave,
    refetch,
    setHasEdits,

    // Helpers
    getEnvHint,
    getWhisperApiKey,

    // Recommended defaults
    groqRecommendedModel,
    groqRecommendedWhisper,

    // Env warning modal
    envWarningPaths,
    showEnvWarning,
    handleConfirmEnvWarning,
    handleDismissEnvWarning,

    // Whisper type change
    handleWhisperTypeChange,

    // Groq quick setup
    applyGroqKey,
    isApplyingGroqKey: applyGroqKeyMutation.isPending,
  };
}

export default useConfigState;

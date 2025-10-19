import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { configApi } from '../services/api';
import { toast } from 'react-hot-toast';
import type { CombinedConfig, LLMConfig, WhisperConfig } from '../types';

export default function ConfigPage() {
  const { data, isLoading, refetch } = useQuery<CombinedConfig>({
    queryKey: ['config'],
    queryFn: configApi.getConfig,
  });

  const [pending, setPending] = useState<CombinedConfig | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showGroqHelp, setShowGroqHelp] = useState(false);
  const [showGroqPricing, setShowGroqPricing] = useState(false);
  const [localWhisperAvailable, setLocalWhisperAvailable] = useState<boolean | null>(null);
  const [llmStatus, setLlmStatus] = useState<'loading' | 'ok' | 'error'>('loading');
  const [llmMessage, setLlmMessage] = useState<string>('');
  const [llmError, setLlmError] = useState<string>('');
  const [whisperStatus, setWhisperStatus] = useState<'loading' | 'ok' | 'error'>('loading');
  const [whisperMessage, setWhisperMessage] = useState<string>('');
  const [whisperError, setWhisperError] = useState<string>('');
  const initialProbeDone = useRef(false);
  const groqRecommendedModel = useMemo(() => 'groq/openai/gpt-oss-120b', []);
  const groqRecommendedWhisper = useMemo(() => 'whisper-large-v3-turbo', []);

  const getWhisperApiKey = (w: WhisperConfig | undefined): string => {
    if (!w) return '';
    if (w.whisper_type === 'remote') return w.api_key ?? '';
    if (w.whisper_type === 'groq') return w.api_key ?? '';
    return '';
  };

  useEffect(() => {
    setPending(data ?? null);
  }, [data]);

  const probeConnections = async () => {
    if (!pending) return;
    setLlmStatus('loading');
    setWhisperStatus('loading');
    setLlmMessage('');
    setLlmError('');
    setWhisperMessage('');
    setWhisperError('');
    try {
      const [llmRes, whisperRes] = await Promise.all([
        configApi.testLLM({ llm: pending.llm as LLMConfig }),
        configApi.testWhisper({ whisper: pending.whisper as WhisperConfig }),
      ]);

      if (llmRes?.ok) {
        setLlmStatus('ok');
        setLlmMessage(llmRes.message || 'LLM connection OK');
      } else {
        setLlmStatus('error');
        setLlmError(llmRes?.error || 'LLM connection failed');
      }

      if (whisperRes?.ok) {
        setWhisperStatus('ok');
        setWhisperMessage(whisperRes.message || 'Whisper connection OK');
      } else {
        setWhisperStatus('error');
        setWhisperError(whisperRes?.error || 'Whisper test failed');
      }
    } catch (err: unknown) {
      const e = err as { response?: { data?: { error?: string; message?: string } }; message?: string };
      setLlmStatus('error');
      setWhisperStatus('error');
      const msg = e?.response?.data?.error || e?.response?.data?.message || e?.message || 'Connection test failed';
      setLlmError(msg);
      setWhisperError(msg);
    }
  };

  useEffect(() => {
    if (!pending || initialProbeDone.current) return;
    initialProbeDone.current = true;
    void probeConnections();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      return configApi.updateConfig((pending ?? {}) as Partial<CombinedConfig>);
    },
    onSuccess: () => {
      refetch();
    },
  });

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

      setPending((prev) => ({
        ...(prev as CombinedConfig),
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
      refetch();
      toast.success('Groq key verified and saved. Defaults applied.');
      setLlmStatus('ok');
      setLlmMessage('LLM connection OK');
      setWhisperStatus('ok');
      setWhisperMessage('Whisper connection OK');
    },
  });

  // Probe whisper capabilities once and adapt UI/state
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

  // If local is unavailable but selected, switch to a safe default
  useEffect(() => {
    if (!pending || localWhisperAvailable !== false) return;
    const currentType = pending.whisper.whisper_type;
    if (currentType === 'local') {
      setField(['whisper', 'whisper_type'], 'remote');
    }
  }, [localWhisperAvailable, pending]);

  if (isLoading || !pending) {
    return <div className="text-sm text-gray-700">Loading configuration...</div>;
  }

  const setField = (path: string[], value: unknown) => {
    setPending((prev) => {
      const next: Record<string, unknown> = {
        ...(prev as unknown as Record<string, unknown>),
      };
      let cursor: Record<string, unknown> = next;
      for (let i = 0; i < path.length - 1; i++) {
        const key = path[i];
        const child = (cursor[key] as Record<string, unknown>) ?? {};
        cursor[key] = child;
        cursor = child;
      }
      cursor[path[path.length - 1]] = value;
      return next as unknown as CombinedConfig;
    });
  };

  const handleWhisperTypeChange = (
    nextType: 'local' | 'remote' | 'groq'
  ) => {
    setPending((prev) => {
      if (!prev) return prev;

      const prevWhisper = prev.whisper as unknown as Record<string, unknown>;
      const prevModelRaw = (prevWhisper?.model as string | undefined) ?? '';
      const prevModel = String(prevModelRaw).toLowerCase();

      const isNonGroqDefault = prevModel === 'base' || prevModel === 'base.en' || prevModel === 'whisper-1';
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
        ...prev,
        whisper: nextWhisper as unknown as WhisperConfig,
      } as CombinedConfig;
    });
  };


  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Configuration</h2>
      </div>

      <Section title="Connection Status">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="flex items-start justify-between border rounded p-3">
            <div>
              <div className="text-sm font-medium text-gray-900">LLM</div>
              <div
                className={
                  'text-xs ' +
                  (llmStatus === 'ok'
                    ? 'text-green-700'
                    : llmStatus === 'error'
                    ? 'text-red-700'
                    : 'text-gray-600')
                }
              >
                {llmStatus === 'loading' && 'Testing...'}
                {llmStatus === 'ok' && (llmMessage || 'LLM connection OK')}
                {llmStatus === 'error' && (llmError || 'LLM connection failed')}
              </div>
            </div>
            <button
              type="button"
              className="text-xs text-indigo-600 hover:underline"
              onClick={() => void probeConnections()}
            >
              Retry
            </button>
          </div>
          <div className="flex items-start justify-between border rounded p-3">
            <div>
              <div className="text-sm font-medium text-gray-900">Whisper</div>
              <div
                className={
                  'text-xs ' +
                  (whisperStatus === 'ok'
                    ? 'text-green-700'
                    : whisperStatus === 'error'
                    ? 'text-red-700'
                    : 'text-gray-600')
                }
              >
                {whisperStatus === 'loading' && 'Testing...'}
                {whisperStatus === 'ok' && (whisperMessage || 'Whisper connection OK')}
                {whisperStatus === 'error' && (whisperError || 'Whisper test failed')}
              </div>
            </div>
            <button
              type="button"
              className="text-xs text-indigo-600 hover:underline"
              onClick={() => void probeConnections()}
            >
              Retry
            </button>
          </div>
        </div>
      </Section>

      <Section title="Quick Setup">
        <div className="text-sm text-gray-700 mb-2 flex items-center gap-2">
          <span>Enter your Groq API key to use the recommended setup.</span>
          <button
            type="button"
            className="text-indigo-600 hover:underline"
            onClick={() => setShowGroqHelp((v) => !v)}
          >
            {showGroqHelp ? 'Hide help' : '(need help getting a key?)'}
          </button>
          <button
            type="button"
            className="text-indigo-600 hover:underline"
            onClick={() => setShowGroqPricing((v) => !v)}
          >
            {showGroqPricing ? 'Hide pricing' : '(pricing guide)'}
          </button>
        </div>
        {showGroqHelp && (
          <div className="text-sm text-gray-700 mb-2 bg-indigo-50 border border-indigo-200 rounded p-3 space-y-2">
            <ol className="list-decimal pl-5 space-y-1">
              <li>
                Visit the{' '}
                <a
                  className="text-indigo-700 underline"
                  href="https://console.groq.com/keys"
                  target="_blank"
                  rel="noreferrer"
                >
                  Groq Console
                </a>{' '}
                and sign in or create an account.
              </li>
              <li>Open the Keys page and click "Create API Key".</li>
              <li>Copy the key (it starts with <code>gsk_</code>) and paste it below.</li>
              <li>
                <strong>Recommended:</strong> Set a billing limit at{' '}
                <a
                  className="text-indigo-700 underline"
                  href="https://console.groq.com/settings/billing"
                  target="_blank"
                  rel="noreferrer"
                >
                  Settings → Billing → Limits
                </a>{' '}
                to control costs and receive usage alerts.
              </li>
            </ol>
          </div>
        )}
        {showGroqPricing && (
          <div className="text-sm text-gray-700 mb-2 bg-green-50 border border-green-200 rounded p-3 space-y-3">
            <div>
              <h4 className="font-semibold text-green-800 mb-2">Groq Pricing Guide</h4>
              <p className="text-green-700 mb-3">
                Based on the recommended models: <code>whisper-large-v3-turbo</code> and <code>llama-3.3-70b-versatile</code>
              </p>
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="bg-white border border-green-300 rounded p-3">
                <h5 className="font-medium text-green-800 mb-2">Whisper (Transcription)</h5>
                <ul className="space-y-1 text-green-700">
                  <li>• <strong>whisper-large-v3-turbo:</strong> $0.04/hour</li>
                  <li>• Speed: 216x real-time</li>
                  <li>• Minimum charge: 10 seconds per request</li>
                </ul>
              </div>
              
              <div className="bg-white border border-green-300 rounded p-3">
                <h5 className="font-medium text-green-800 mb-2">LLM (Ad Detection)</h5>
                <ul className="space-y-1 text-green-700">
                  <li>• <strong>llama-3.3-70b-versatile:</strong></li>
                  <li>• Input: $0.59/1M tokens</li>
                  <li>• Output: $0.79/1M tokens</li>
                  <li>• ~1M tokens ≈ 750,000 words</li>
                </ul>
              </div>
            </div>
            
            <div className="bg-white border border-green-300 rounded p-3">
              <h5 className="font-medium text-green-800 mb-2">Estimated Monthly Cost (6 podcasts, 6 hours/week)</h5>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-green-700">
                <div>
                  <strong>Transcription:</strong><br />
                  24 hours/month × $0.04 = <span className="font-semibold">$0.96/month</span>
                </div>
                <div>
                  <strong>Ad Detection:</strong><br />
                  ~2M tokens × $0.69 avg = <span className="font-semibold">$1.38/month</span>
                </div>
                <div className="md:col-span-1">
                  <strong>Total Estimate:</strong><br />
                  <span className="font-semibold text-lg">~$2.34/month</span>
                </div>
              </div>
              <p className="text-xs text-green-600 mt-2">
                * Actual costs may vary based on podcast length, complexity, and token usage. 
                Consider setting a $5-10/month billing limit for safety.
              </p>
            </div>
          </div>
        )}
        <Field label="Groq API Key">
          <div className="flex gap-2">
            <input
              className="input"
              type="text"
              placeholder="gsk_..."
              value={pending?.whisper?.whisper_type === 'groq' ? getWhisperApiKey(pending?.whisper) : (pending?.llm?.llm_api_key || '')}
              onChange={(e) => {
                const val = e.target.value;
                setPending((prev) => {
                  if (!prev) return prev;
                  return {
                    ...prev,
                    llm: {
                      ...(prev.llm as LLMConfig),
                      llm_api_key: val,
                      llm_model: groqRecommendedModel,
                    },
                    whisper: {
                      whisper_type: 'groq',
                      api_key: val,
                      model: groqRecommendedWhisper,
                      language: 'en',
                      max_retries: 3,
                    } as WhisperConfig,
                  } as CombinedConfig;
                });
              }}
              onBlur={(e) => {
                const key = e.target.value.trim();
                if (!key) return;
                toast.promise(applyGroqKeyMutation.mutateAsync(key), {
                  loading: 'Verifying Groq key and applying defaults...',
                  success: 'Groq configured successfully',
                  error: (err: unknown) => {
                    const e = err as { response?: { data?: { error?: string; message?: string } }; message?: string };
                    return e?.response?.data?.error || e?.response?.data?.message || e?.message || 'Failed to configure Groq';
                  },
                });
              }}
              onPaste={(e) => {
                const text = e.clipboardData.getData('text').trim();
                if (!text) return;
                toast.promise(applyGroqKeyMutation.mutateAsync(text), {
                  loading: 'Verifying Groq key and applying defaults...',
                  success: 'Groq configured successfully',
                  error: (err: unknown) => {
                    const er = err as { response?: { data?: { error?: string; message?: string } }; message?: string };
                    return er?.response?.data?.error || er?.response?.data?.message || er?.message || 'Failed to configure Groq';
                  },
                });
              }}
            />
          </div>
        </Field>
      </Section>

      <div className="flex items-center justify-end">
        <button
          onClick={() => setShowAdvanced((v) => !v)}
          className="px-3 py-2 text-sm rounded border border-gray-300 text-gray-700 hover:bg-gray-50"
        >
          {showAdvanced ? 'Hide Advanced Settings' : 'Show Advanced Settings'}
        </button>
      </div>

      {showAdvanced && (
        <div className="space-y-6">
          <Section title="LLM">
            <Field label="API Key">
              <input
                className="input"
                type="text"
                value={pending?.llm?.llm_api_key || ''}
                onChange={(e) => setField(['llm', 'llm_api_key'], e.target.value)}
              />
            </Field>
            <Field label="OpenAI Base URL">
              <input
                className="input"
                type="text"
                placeholder="https://api.openai.com/v1"
                value={pending?.llm?.openai_base_url || ''}
                onChange={(e) => setField(['llm', 'openai_base_url'], e.target.value)}
              />
            </Field>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Field label="Model">
                <div className="relative">
                  <input
                    list="llm-model-datalist"
                    className="input"
                    type="text"
                    value={pending?.llm?.llm_model ?? ''}
                    onChange={(e) => setField(['llm', 'llm_model'], e.target.value)}
                    placeholder="e.g. groq/openai/gpt-oss-120b"
                  />
                </div>
              </Field>
              <Field label="OpenAI Timeout (sec)">
                <input
                  className="input"
                  type="number"
                  value={pending?.llm?.openai_timeout ?? 300}
                  onChange={(e) => setField(['llm', 'openai_timeout'], Number(e.target.value))}
                />
              </Field>
              <Field label="OpenAI Max Tokens">
                <input
                  className="input"
                  type="number"
                  value={pending?.llm?.openai_max_tokens ?? 4096}
                  onChange={(e) => setField(['llm', 'openai_max_tokens'], Number(e.target.value))}
                />
              </Field>
              <Field label="Max Concurrent LLM Calls">
                <input
                  className="input"
                  type="number"
                  value={pending?.llm?.llm_max_concurrent_calls ?? 3}
                  onChange={(e) => setField(['llm', 'llm_max_concurrent_calls'], Number(e.target.value))}
                />
              </Field>
              <Field label="Max Retry Attempts">
                <input
                  className="input"
                  type="number"
                  value={pending?.llm?.llm_max_retry_attempts ?? 5}
                  onChange={(e) => setField(['llm', 'llm_max_retry_attempts'], Number(e.target.value))}
                />
              </Field>
              <Field label="Enable Token Rate Limiting">
                <input
                  type="checkbox"
                  checked={!!pending?.llm?.llm_enable_token_rate_limiting}
                  onChange={(e) => setField(['llm', 'llm_enable_token_rate_limiting'], e.target.checked)}
                />
              </Field>
              <Field label="Max Input Tokens Per Call (optional)">
                <input
                  className="input"
                  type="number"
                  value={pending?.llm?.llm_max_input_tokens_per_call ?? ''}
                  onChange={(e) => setField(['llm', 'llm_max_input_tokens_per_call'], e.target.value === '' ? null : Number(e.target.value))}
                />
              </Field>
              <Field label="Max Input Tokens Per Minute (optional)">
                <input
                  className="input"
                  type="number"
                  value={pending?.llm?.llm_max_input_tokens_per_minute ?? ''}
                  onChange={(e) => setField(['llm', 'llm_max_input_tokens_per_minute'], e.target.value === '' ? null : Number(e.target.value))}
                />
              </Field>
            </div>
            <div className="flex justify-center">
              <button
                onClick={() => {
                  toast.promise(
                    configApi.testLLM({ llm: pending.llm as LLMConfig }),
                    {
                      loading: 'Testing LLM connection...',
                      success: (res: { ok: boolean; message?: string }) => res?.message || 'LLM connection OK',
                      error: (err: unknown) => {
                        const e = err as { response?: { data?: { error?: string; message?: string } }; message?: string };
                        return (
                          e?.response?.data?.error ||
                          e?.response?.data?.message ||
                          e?.message ||
                          'LLM connection failed'
                        );
                      }
                    }
                  );
                }}
                className="mt-2 px-3 py-2 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700"
              >
                Test LLM
              </button>
            </div>
          </Section>

          <Section title="Whisper">
            <Field label="Type">
              <select
                className="input"
                value={
                  (pending?.whisper?.whisper_type as string | undefined) ?? (localWhisperAvailable === false ? 'remote' : 'local')
                }
                onChange={(e) => handleWhisperTypeChange(e.target.value as 'local' | 'remote' | 'groq')}
              >
                {localWhisperAvailable !== false && <option value="local">local</option>}
                <option value="remote">remote</option>
                <option value="groq">groq</option>
              </select>
            </Field>
            {pending?.whisper?.whisper_type === 'local' && (
              <Field label="Local Model">
                <input
                  className="input"
                  type="text"
                  value={pending?.whisper?.model || 'base'}
                  onChange={(e) => setField(['whisper', 'model'], e.target.value)}
                />
              </Field>
            )}
            {pending?.whisper?.whisper_type === 'remote' && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <Field label="API Key">
                  <input
                    className="input"
                    type="text"
                    value={getWhisperApiKey(pending?.whisper)}
                    onChange={(e) => setField(['whisper', 'api_key'], e.target.value)}
                  />
                </Field>
                <Field label="Remote Model">
                  <input
                    className="input"
                    type="text"
                    value={pending?.whisper?.model || 'whisper-1'}
                    onChange={(e) => setField(['whisper', 'model'], e.target.value)}
                  />
                </Field>
                <Field label="Base URL">
                  <input
                    className="input"
                    type="text"
                    placeholder="https://api.openai.com/v1"
                    value={pending?.whisper?.base_url || ''}
                    onChange={(e) => setField(['whisper', 'base_url'], e.target.value)}
                  />
                </Field>
                <Field label="Language">
                  <input
                    className="input"
                    type="text"
                    value={pending?.whisper?.language || 'en'}
                    onChange={(e) => setField(['whisper', 'language'], e.target.value)}
                  />
                </Field>
                <Field label="Timeout (sec)">
                  <input
                    className="input"
                    type="number"
                    value={pending?.whisper?.timeout_sec ?? 600}
                    onChange={(e) => setField(['whisper', 'timeout_sec'], Number(e.target.value))}
                  />
                </Field>
                <Field label="Chunk Size (MB)">
                  <input
                    className="input"
                    type="number"
                    value={pending?.whisper?.chunksize_mb ?? 24}
                    onChange={(e) => setField(['whisper', 'chunksize_mb'], Number(e.target.value))}
                  />
                </Field>
              </div>
            )}
            {pending?.whisper?.whisper_type === 'groq' && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <Field label="API Key">
                  <input
                    className="input"
                    type="text"
                    value={getWhisperApiKey(pending?.whisper)}
                    onChange={(e) => setField(['whisper', 'api_key'], e.target.value)}
                  />
                </Field>
                <Field label="Model">
                  <input
                    className="input"
                    type="text"
                    value={pending?.whisper?.model || 'whisper-large-v3-turbo'}
                    onChange={(e) => setField(['whisper', 'model'], e.target.value)}
                  />
                </Field>
                <Field label="Language">
                  <input
                    className="input"
                    type="text"
                    value={pending?.whisper?.language || 'en'}
                    onChange={(e) => setField(['whisper', 'language'], e.target.value)}
                  />
                </Field>
                <Field label="Max Retries">
                  <input
                    className="input"
                    type="number"
                    value={pending?.whisper?.max_retries ?? 3}
                    onChange={(e) => setField(['whisper', 'max_retries'], Number(e.target.value))}
                  />
                </Field>
              </div>
            )}
            <div className="flex justify-center">
              <button
                onClick={() => {
                  toast.promise(
                    configApi.testWhisper({ whisper: pending.whisper as WhisperConfig }),
                    {
                      loading: 'Testing Whisper...',
                      success: (res: { ok: boolean; message?: string }) => res?.message || 'Whisper OK',
                      error: (err: unknown) => {
                        const e = err as { response?: { data?: { error?: string; message?: string } }; message?: string };
                        return (
                          e?.response?.data?.error ||
                          e?.response?.data?.message ||
                          e?.message ||
                          'Whisper test failed'
                        );
                      }
                    }
                  );
                }}
                className="mt-2 px-3 py-2 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700"
              >
                Test Whisper
              </button>
            </div>
          </Section>

          <Section title="Processing">
            <Field label="Number of Segments per Prompt">
              <input
                className="input"
                type="number"
                value={pending?.processing?.num_segments_to_input_to_prompt ?? 30}
                onChange={(e) => setField(['processing', 'num_segments_to_input_to_prompt'], Number(e.target.value))}
              />
            </Field>
          </Section>

          <Section title="Output">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Field label="Fade (ms)">
                <input
                  className="input"
                  type="number"
                  value={pending?.output?.fade_ms ?? 3000}
                  onChange={(e) => setField(['output', 'fade_ms'], Number(e.target.value))}
                />
              </Field>
              <Field label="Min Segment Separation (sec)">
                <input
                  className="input"
                  type="number"
                  value={pending?.output?.min_ad_segement_separation_seconds ?? 60}
                  onChange={(e) => setField(['output', 'min_ad_segement_separation_seconds'], Number(e.target.value))}
                />
              </Field>
              <Field label="Min Segment Length (sec)">
                <input
                  className="input"
                  type="number"
                  value={pending?.output?.min_ad_segment_length_seconds ?? 14}
                  onChange={(e) => setField(['output', 'min_ad_segment_length_seconds'], Number(e.target.value))}
                />
              </Field>
              <Field label="Min Confidence">
                <input
                  className="input"
                  type="number"
                  step="0.01"
                  value={pending?.output?.min_confidence ?? 0.8}
                  onChange={(e) => setField(['output', 'min_confidence'], Number(e.target.value))}
                />
              </Field>
            </div>
          </Section>

          <Section title="App">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Field label="Background Interval (min)">
                <input
                  className="input"
                  type="number"
                  value={pending?.app?.background_update_interval_minute ?? ''}
                  onChange={(e) => setField(['app', 'background_update_interval_minute'], e.target.value === '' ? null : Number(e.target.value))}
                />
              </Field>
              <Field label="Auto-whitelist new episodes">
                <input
                  type="checkbox"
                  checked={!!pending?.app?.automatically_whitelist_new_episodes}
                  onChange={(e) => setField(['app', 'automatically_whitelist_new_episodes'], e.target.checked)}
                />
              </Field>
              <Field label="Number of episodes to whitelist from new feed archive">
                <input
                  className="input"
                  type="number"
                  value={pending?.app?.number_of_episodes_to_whitelist_from_archive_of_new_feed ?? 1}
                  onChange={(e) => setField(['app', 'number_of_episodes_to_whitelist_from_archive_of_new_feed'], Number(e.target.value))}
                />
              </Field>
            </div>
          </Section>

          <div className="flex items-center justify-end">
            <button
              onClick={() => {
                toast.promise(
                  saveMutation.mutateAsync(),
                  {
                    loading: 'Saving changes...',
                    success: 'Configuration saved',
                    error: (err: unknown) => {
                      if (typeof err === 'object' && err !== null) {
                        const e = err as { response?: { data?: { error?: string; details?: string; message?: string } }; message?: string };
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
                  }
                );
              }}
              className="px-3 py-2 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700"
              disabled={saveMutation.isPending}
            >
              {saveMutation.isPending ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </div>
      )}
      
      {/* Extra padding to prevent audio player overlay from obscuring bottom settings */}
      <div className="h-24"></div>
      {/* Datalist options rendered once at end to ensure they exist in DOM */}
      <LlmModelDatalist />
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="bg-white rounded border p-4">
      <h3 className="text-sm font-semibold text-gray-900 mb-3">{title}</h3>
      <div className="space-y-3">{children}</div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex items-center justify-between gap-3">
      <span className="w-60 text-sm text-gray-700">{label}</span>
      <div className="flex-1">{children}</div>
      <style>{`.input{width:100%;padding:0.5rem;border:1px solid #e5e7eb;border-radius:0.375rem;font-size:0.875rem}`}</style>
    </label>
  );
}

const LLM_MODEL_ALIASES: string[] = [
  // OpenAI aliases
  'openai/gpt-4',
  'openai/gpt-4o',
  // Anthropic
  'anthropic/claude-3.5-sonnet',
  'anthropic/claude-3.5-haiku',
  // Google Gemini
  'gemini/gemini-2.0-flash',
  'gemini/gemini-1.5-pro',
  'gemini/gemini-1.5-flash',
  // Groq popular models
  'groq/openai/gpt-oss-120b',
];

function LlmModelDatalist() {
  return (
    <datalist id="llm-model-datalist">
      {LLM_MODEL_ALIASES.map((m) => (
        <option key={m} value={m} />
      ))}
    </datalist>
  );
}

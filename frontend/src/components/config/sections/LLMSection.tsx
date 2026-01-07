import { useState } from 'react';
import { toast } from 'react-hot-toast';
import { configApi } from '../../../services/api';
import { useConfigContext } from '../ConfigContext';
import { Section, Field, SaveButton, TestButton } from '../shared';
import type { LLMConfig } from '../../../types';

const LLM_MODEL_ALIASES: string[] = [
  'openai/gpt-4',
  'openai/gpt-4o',
  'anthropic/claude-3.5-sonnet',
  'anthropic/claude-3.5-haiku',
  'gemini/gemini-3-flash-preview',
  'gemini/gemini-2.0-flash',
  'gemini/gemini-1.5-pro',
  'gemini/gemini-1.5-flash',
  'groq/openai/gpt-oss-120b',
];

export default function LLMSection() {
  const { pending, setField, getEnvHint, handleSave, isSaving } = useConfigContext();
  const [showBaseUrlInfo, setShowBaseUrlInfo] = useState(false);

  if (!pending) return null;

  const handleTestLLM = () => {
    toast.promise(configApi.testLLM({ llm: pending.llm as LLMConfig }), {
      loading: 'Testing LLM connection...',
      success: (res: { ok: boolean; message?: string }) => res?.message || 'LLM connection OK',
      error: (err: unknown) => {
        const e = err as {
          response?: { data?: { error?: string; message?: string } };
          message?: string;
        };
        return (
          e?.response?.data?.error ||
          e?.response?.data?.message ||
          e?.message ||
          'LLM connection failed'
        );
      },
    });
  };

  return (
    <div className="space-y-6">
      <Section title="LLM">
        <Field label="API Key" envMeta={getEnvHint('llm.llm_api_key')}>
          <input
            className="input"
            type="text"
            placeholder={pending?.llm?.llm_api_key_preview || ''}
            value={pending?.llm?.llm_api_key || ''}
            onChange={(e) => setField(['llm', 'llm_api_key'], e.target.value)}
          />
        </Field>

        <label className="flex items-start justify-between gap-3">
          <div className="w-60">
            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-700">OpenAI Base URL</span>
              <button
                type="button"
                className="px-2 py-1 text-xs border border-gray-300 rounded hover:bg-gray-50"
                onClick={() => setShowBaseUrlInfo((v) => !v)}
                title="When is this used?"
              >
                ⓘ
              </button>
            </div>
            {getEnvHint('llm.openai_base_url')?.env_var && (
              <code className="mt-1 block text-xs text-gray-500 font-mono">
                {getEnvHint('llm.openai_base_url')?.env_var}
              </code>
            )}
          </div>
          <div className="flex-1 space-y-2">
            <input
              className="input"
              type="text"
              placeholder="https://api.openai.com/v1"
              value={pending?.llm?.openai_base_url || ''}
              onChange={(e) => setField(['llm', 'openai_base_url'], e.target.value)}
            />
            {showBaseUrlInfo && <BaseUrlInfoBox />}
          </div>
        </label>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Field label="Model" envMeta={getEnvHint('llm.llm_model')}>
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
          <Field label="Enable Boundary Refinement" hint="LLM-based ad boundary refinement for improved precision">
            <input
              type="checkbox"
              checked={pending?.llm?.enable_boundary_refinement ?? true}
              onChange={(e) => setField(['llm', 'enable_boundary_refinement'], e.target.checked)}
            />
          </Field>
          <Field label="Max Input Tokens Per Call (optional)">
            <input
              className="input"
              type="number"
              value={pending?.llm?.llm_max_input_tokens_per_call ?? ''}
              onChange={(e) =>
                setField(
                  ['llm', 'llm_max_input_tokens_per_call'],
                  e.target.value === '' ? null : Number(e.target.value)
                )
              }
            />
          </Field>
          <Field label="Max Input Tokens Per Minute (optional)">
            <input
              className="input"
              type="number"
              value={pending?.llm?.llm_max_input_tokens_per_minute ?? ''}
              onChange={(e) =>
                setField(
                  ['llm', 'llm_max_input_tokens_per_minute'],
                  e.target.value === '' ? null : Number(e.target.value)
                )
              }
            />
          </Field>
        </div>

        <TestButton onClick={handleTestLLM} label="Test LLM" />
      </Section>

      <SaveButton onSave={handleSave} isPending={isSaving} />

      {/* Datalist for model suggestions */}
      <datalist id="llm-model-datalist">
        {LLM_MODEL_ALIASES.map((m) => (
          <option key={m} value={m} />
        ))}
      </datalist>

      <style>{`.input{width:100%;padding:0.5rem;border:1px solid #e5e7eb;border-radius:0.375rem;font-size:0.875rem}`}</style>
    </div>
  );
}

function BaseUrlInfoBox() {
  return (
    <div className="text-xs text-gray-700 bg-blue-50 border border-blue-200 rounded p-3 space-y-2">
      <p className="font-semibold">When is Base URL used?</p>
      <p>
        The Base URL is <strong>only used for models without a provider prefix</strong>. LiteLLM
        automatically routes provider-prefixed models to their respective APIs.
      </p>
      <div className="space-y-1">
        <p className="font-medium">✅ Base URL is IGNORED for:</p>
        <ul className="list-disc pl-5 space-y-0.5">
          <li>
            <code className="bg-white px-1 rounded">groq/openai/gpt-oss-120b</code> → Groq API
          </li>
          <li>
            <code className="bg-white px-1 rounded">anthropic/claude-3.5-sonnet</code> → Anthropic
            API
          </li>
          <li>
            <code className="bg-white px-1 rounded">gemini/gemini-3-flash-preview</code> → Google API
          </li>
          <li>
            <code className="bg-white px-1 rounded">gemini/gemini-2.0-flash</code> → Google API
          </li>
        </ul>
      </div>
      <div className="space-y-1">
        <p className="font-medium">⚙️ Base URL is USED for:</p>
        <ul className="list-disc pl-5 space-y-0.5">
          <li>
            Unprefixed models like <code className="bg-white px-1 rounded">gpt-4o</code>
          </li>
          <li>Self-hosted OpenAI-compatible endpoints</li>
          <li>LiteLLM proxy servers or local LLMs</li>
        </ul>
      </div>
      <p className="italic text-gray-600">For the default Groq setup, you don't need to set this.</p>
    </div>
  );
}

import { useMemo } from 'react';
import { toast } from 'react-hot-toast';
import { configApi } from '../../../services/api';
import { useConfigContext } from '../ConfigContext';
import { Section, Field, SaveButton, TestButton } from '../shared';
import type { WhisperConfig } from '../../../types';

export default function WhisperSection() {
  const {
    pending,
    setField,
    getEnvHint,
    handleSave,
    isSaving,
    localWhisperAvailable,
    handleWhisperTypeChange,
    getWhisperApiKey,
    envOverrides,
  } = useConfigContext();

  const whisperApiKeyPreview =
    pending?.whisper?.whisper_type === 'remote' || pending?.whisper?.whisper_type === 'groq'
      ? (pending.whisper as { api_key_preview?: string }).api_key_preview
      : undefined;

  const whisperApiKeyPlaceholder = useMemo(() => {
    if (pending?.whisper?.whisper_type === 'remote' || pending?.whisper?.whisper_type === 'groq') {
      if (whisperApiKeyPreview) {
        return whisperApiKeyPreview;
      }
      const override = envOverrides['whisper.api_key'];
      if (override) {
        return override.value_preview || override.value || '';
      }
    }
    return '';
  }, [whisperApiKeyPreview, pending?.whisper?.whisper_type, envOverrides]);

  if (!pending) return null;

  const handleTestWhisper = () => {
    toast.promise(configApi.testWhisper({ whisper: pending.whisper as WhisperConfig }), {
      loading: 'Testing Whisper...',
      success: (res: { ok: boolean; message?: string }) => res?.message || 'Whisper OK',
      error: (err: unknown) => {
        const e = err as {
          response?: { data?: { error?: string; message?: string } };
          message?: string;
        };
        return (
          e?.response?.data?.error ||
          e?.response?.data?.message ||
          e?.message ||
          'Whisper test failed'
        );
      },
    });
  };

  const whisperType = pending?.whisper?.whisper_type ?? (localWhisperAvailable === false ? 'remote' : 'local');

  return (
    <div className="space-y-6">
      <Section title="Whisper">
        <Field label="Type" envMeta={getEnvHint('whisper.whisper_type')}>
          <select
            className="input"
            value={whisperType}
            onChange={(e) => handleWhisperTypeChange(e.target.value as 'local' | 'remote' | 'groq')}
          >
            {localWhisperAvailable !== false && <option value="local">local</option>}
            <option value="remote">remote</option>
            <option value="groq">groq</option>
          </select>
        </Field>

        {/* Local Whisper Options */}
        {pending?.whisper?.whisper_type === 'local' && (
          <Field
            label="Local Model"
            envMeta={getEnvHint('whisper.model', { env_var: 'WHISPER_LOCAL_MODEL' })}
          >
            <input
              className="input"
              type="text"
              value={(pending?.whisper as { model?: string })?.model || 'base'}
              onChange={(e) => setField(['whisper', 'model'], e.target.value)}
            />
          </Field>
        )}

        {/* Remote Whisper Options */}
        {pending?.whisper?.whisper_type === 'remote' && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Field
              label="API Key"
              envMeta={getEnvHint('whisper.api_key', { env_var: 'WHISPER_REMOTE_API_KEY' })}
            >
              <input
                className="input"
                type="text"
                placeholder={whisperApiKeyPlaceholder}
                value={getWhisperApiKey(pending?.whisper)}
                onChange={(e) => setField(['whisper', 'api_key'], e.target.value)}
              />
            </Field>
            <Field
              label="Remote Model"
              envMeta={getEnvHint('whisper.model', { env_var: 'WHISPER_REMOTE_MODEL' })}
            >
              <input
                className="input"
                type="text"
                value={(pending?.whisper as { model?: string })?.model || 'whisper-1'}
                onChange={(e) => setField(['whisper', 'model'], e.target.value)}
              />
            </Field>
            <Field label="Base URL" envMeta={getEnvHint('whisper.base_url')}>
              <input
                className="input"
                type="text"
                placeholder="https://api.openai.com/v1"
                value={(pending?.whisper as { base_url?: string })?.base_url || ''}
                onChange={(e) => setField(['whisper', 'base_url'], e.target.value)}
              />
            </Field>
            <Field label="Language">
              <input
                className="input"
                type="text"
                value={(pending?.whisper as { language?: string })?.language || 'en'}
                onChange={(e) => setField(['whisper', 'language'], e.target.value)}
              />
            </Field>
            <Field label="Timeout (sec)" envMeta={getEnvHint('whisper.timeout_sec')}>
              <input
                className="input"
                type="number"
                value={(pending?.whisper as { timeout_sec?: number })?.timeout_sec ?? 600}
                onChange={(e) => setField(['whisper', 'timeout_sec'], Number(e.target.value))}
              />
            </Field>
            <Field label="Chunk Size (MB)" envMeta={getEnvHint('whisper.chunksize_mb')}>
              <input
                className="input"
                type="number"
                value={(pending?.whisper as { chunksize_mb?: number })?.chunksize_mb ?? 24}
                onChange={(e) => setField(['whisper', 'chunksize_mb'], Number(e.target.value))}
              />
            </Field>
          </div>
        )}

        {/* Groq Whisper Options */}
        {pending?.whisper?.whisper_type === 'groq' && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Field
              label="API Key"
              envMeta={getEnvHint('whisper.api_key', { env_var: 'GROQ_API_KEY' })}
            >
              <input
                className="input"
                type="text"
                placeholder={whisperApiKeyPlaceholder}
                value={getWhisperApiKey(pending?.whisper)}
                onChange={(e) => setField(['whisper', 'api_key'], e.target.value)}
              />
            </Field>
            <Field
              label="Model"
              envMeta={getEnvHint('whisper.model', { env_var: 'GROQ_WHISPER_MODEL' })}
            >
              <input
                className="input"
                type="text"
                value={(pending?.whisper as { model?: string })?.model || 'whisper-large-v3-turbo'}
                onChange={(e) => setField(['whisper', 'model'], e.target.value)}
              />
            </Field>
            <Field label="Language">
              <input
                className="input"
                type="text"
                value={(pending?.whisper as { language?: string })?.language || 'en'}
                onChange={(e) => setField(['whisper', 'language'], e.target.value)}
              />
            </Field>
            <Field label="Max Retries" envMeta={getEnvHint('whisper.max_retries')}>
              <input
                className="input"
                type="number"
                value={(pending?.whisper as { max_retries?: number })?.max_retries ?? 3}
                onChange={(e) => setField(['whisper', 'max_retries'], Number(e.target.value))}
              />
            </Field>
          </div>
        )}

        <TestButton onClick={handleTestWhisper} label="Test Whisper" />
      </Section>

      <SaveButton onSave={handleSave} isPending={isSaving} />

      <style>{`.input{width:100%;padding:0.5rem;border:1px solid #e5e7eb;border-radius:0.375rem;font-size:0.875rem}`}</style>
    </div>
  );
}

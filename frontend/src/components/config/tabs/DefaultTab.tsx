import { useState } from 'react';
import { useConfigContext } from '../ConfigContext';
import { Section, Field, ConnectionStatusCard } from '../shared';
import type { WhisperConfig, LLMConfig } from '../../../types';

export default function DefaultTab() {
  const {
    pending,
    updatePending,
    llmStatus,
    whisperStatus,
    probeConnections,
    getEnvHint,
    getWhisperApiKey,
    groqRecommendedModel,
    groqRecommendedWhisper,
    applyGroqKey,
  } = useConfigContext();

  const [showGroqHelp, setShowGroqHelp] = useState(false);
  const [showGroqPricing, setShowGroqPricing] = useState(false);

  if (!pending) return null;

  const handleGroqKeyChange = (val: string) => {
    updatePending((prevConfig) => {
      return {
        ...prevConfig,
        llm: {
          ...(prevConfig.llm as LLMConfig),
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
      };
    });
  };

  const handleGroqKeyApply = (key: string) => {
    if (!key.trim()) return;
    void applyGroqKey(key.trim());
  };

  const currentGroqKey =
    pending?.whisper?.whisper_type === 'groq'
      ? getWhisperApiKey(pending?.whisper)
      : pending?.llm?.llm_api_key || '';

  const groqKeyPlaceholder =
    pending?.whisper?.whisper_type === 'groq'
      ? pending?.whisper?.api_key_preview || ''
      : pending?.llm?.llm_api_key_preview || '';

  return (
    <div className="space-y-6">
      <Section title="Connection Status">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <ConnectionStatusCard
            title="LLM"
            status={llmStatus.status}
            message={llmStatus.message}
            error={llmStatus.error}
            onRetry={() => void probeConnections()}
          />
          <ConnectionStatusCard
            title="Whisper"
            status={whisperStatus.status}
            message={whisperStatus.message}
            error={whisperStatus.error}
            onRetry={() => void probeConnections()}
          />
        </div>
      </Section>

      <Section title="Quick Setup">
        <div className="text-sm text-gray-700 mb-2 flex items-center gap-2 flex-wrap">
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

        {showGroqHelp && <GroqHelpBox />}
        {showGroqPricing && <GroqPricingBox />}

        <Field label="Groq API Key" envMeta={getEnvHint('groq.api_key')}>
          <div className="flex gap-2">
            <input
              className="input"
              type="text"
              placeholder={groqKeyPlaceholder}
              value={currentGroqKey}
              onChange={(e) => handleGroqKeyChange(e.target.value)}
              onBlur={(e) => handleGroqKeyApply(e.target.value)}
              onPaste={(e) => {
                const text = e.clipboardData.getData('text').trim();
                if (text) handleGroqKeyApply(text);
              }}
            />
          </div>
        </Field>
      </Section>

      {/* Input styling */}
      <style>{`.input{width:100%;padding:0.5rem;border:1px solid #e5e7eb;border-radius:0.375rem;font-size:0.875rem}`}</style>
    </div>
  );
}

function GroqHelpBox() {
  return (
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
        <li>
          Copy the key (it starts with <code>gsk_</code>) and paste it below.
        </li>
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
  );
}

function GroqPricingBox() {
  return (
    <div className="text-sm text-gray-700 mb-2 bg-green-50 border border-green-200 rounded p-3 space-y-3">
      <div>
        <h4 className="font-semibold text-green-800 mb-2">Groq Pricing Guide</h4>
        <p className="text-green-700 mb-3">
          Based on the recommended models: <code>whisper-large-v3-turbo</code> and{' '}
          <code>llama-3.3-70b-versatile</code>
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-white border border-green-300 rounded p-3">
          <h5 className="font-medium text-green-800 mb-2">Whisper (Transcription)</h5>
          <ul className="space-y-1 text-green-700">
            <li>
              • <strong>whisper-large-v3-turbo:</strong> $0.04/hour
            </li>
            <li>• Speed: 216x real-time</li>
            <li>• Minimum charge: 10 seconds per request</li>
          </ul>
        </div>

        <div className="bg-white border border-green-300 rounded p-3">
          <h5 className="font-medium text-green-800 mb-2">LLM (Ad Detection)</h5>
          <ul className="space-y-1 text-green-700">
            <li>
              • <strong>llama-3.3-70b-versatile:</strong>
            </li>
            <li>• Input: $0.59/1M tokens</li>
            <li>• Output: $0.79/1M tokens</li>
            <li>• ~1M tokens ≈ 750,000 words</li>
          </ul>
        </div>
      </div>

      <div className="bg-white border border-green-300 rounded p-3">
        <h5 className="font-medium text-green-800 mb-2">
          Estimated Monthly Cost (6 podcasts, 6 hours/week)
        </h5>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-green-700">
          <div>
            <strong>Transcription:</strong>
            <br />
            24 hours/month × $0.04 = <span className="font-semibold">$0.96/month</span>
          </div>
          <div>
            <strong>Ad Detection:</strong>
            <br />
            ~2M tokens × $0.69 avg = <span className="font-semibold">$1.38/month</span>
          </div>
          <div className="md:col-span-1">
            <strong>Total Estimate:</strong>
            <br />
            <span className="font-semibold text-lg">~$2.34/month</span>
          </div>
        </div>
        <p className="text-xs text-green-600 mt-2">
          * Actual costs may vary based on podcast length, complexity, and token usage. Consider
          setting a $5-10/month billing limit for safety.
        </p>
      </div>
    </div>
  );
}

import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'react-hot-toast';
import { discordApi } from '../../../services/api';
import { Section } from '../shared';

export default function DiscordTab() {
  const queryClient = useQueryClient();
  
  const { data, isLoading, error } = useQuery({
    queryKey: ['discord-config'],
    queryFn: discordApi.getConfig,
  });

  const [form, setForm] = useState({
    client_id: '',
    client_secret: '',
    redirect_uri: '',
    guild_ids: '',
    allow_registration: true,
  });

  const [hasSecretChange, setHasSecretChange] = useState(false);

  // Initialize form when data loads
  useEffect(() => {
    if (data?.config) {
      setForm({
        client_id: data.config.client_id || '',
        client_secret: '', // Don't prefill secret
        redirect_uri: data.config.redirect_uri || '',
        guild_ids: data.config.guild_ids || '',
        allow_registration: data.config.allow_registration,
      });
      setHasSecretChange(false);
    }
  }, [data]);

  const mutation = useMutation({
    mutationFn: discordApi.updateConfig,
    onSuccess: () => {
      toast.success('Discord settings saved');
      queryClient.invalidateQueries({ queryKey: ['discord-config'] });
      queryClient.invalidateQueries({ queryKey: ['discord-status'] });
      setHasSecretChange(false);
    },
    onError: (err: Error) => {
      toast.error(`Failed to save: ${err.message}`);
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    
    const payload: Record<string, unknown> = {
      client_id: form.client_id,
      redirect_uri: form.redirect_uri,
      guild_ids: form.guild_ids,
      allow_registration: form.allow_registration,
    };

    // Only include secret if it was changed
    if (hasSecretChange && form.client_secret) {
      payload.client_secret = form.client_secret;
    }

    mutation.mutate(payload);
  };

  const envOverrides = data?.env_overrides || {};

  if (isLoading) {
    return <div className="text-sm text-gray-600">Loading Discord configuration...</div>;
  }

  if (error) {
    return <div className="text-sm text-red-600">Failed to load Discord configuration</div>;
  }

  return (
    <div className="space-y-6">
      <Section title="Discord SSO Configuration">
        <StatusIndicator enabled={data?.config.enabled ?? false} />
        
        <form onSubmit={handleSubmit} className="mt-6 space-y-4 max-w-xl">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Client ID
              {envOverrides.client_id && (
                <span className="ml-2 text-xs text-amber-600">
                  (Overridden by {envOverrides.client_id.env_var})
                </span>
              )}
            </label>
            <input
              type="text"
              className="input"
              value={form.client_id}
              onChange={(e) => setForm({ ...form, client_id: e.target.value })}
              placeholder="Your Discord application Client ID"
              disabled={!!envOverrides.client_id}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Client Secret
              {envOverrides.client_secret ? (
                <span className="ml-2 text-xs text-amber-600">
                  (Overridden by {envOverrides.client_secret.env_var})
                </span>
              ) : data?.config.client_secret_preview ? (
                <span className="ml-2 text-xs text-gray-500">
                  (Current: {data.config.client_secret_preview})
                </span>
              ) : null}
            </label>
            <input
              type="password"
              className="input"
              value={form.client_secret}
              onChange={(e) => {
                setForm({ ...form, client_secret: e.target.value });
                setHasSecretChange(true);
              }}
              placeholder={data?.config.client_secret_preview ? '••••••••' : 'Your Discord application Client Secret'}
              disabled={!!envOverrides.client_secret}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Redirect URI
              {envOverrides.redirect_uri && (
                <span className="ml-2 text-xs text-amber-600">
                  (Overridden by {envOverrides.redirect_uri.env_var})
                </span>
              )}
            </label>
            <input
              type="url"
              className="input"
              value={form.redirect_uri}
              onChange={(e) => setForm({ ...form, redirect_uri: e.target.value })}
              placeholder="https://your-domain.com/api/auth/discord/callback"
              disabled={!!envOverrides.redirect_uri}
            />
            <p className="text-xs text-gray-500 mt-1">
              Must match the URI configured in Discord Developer Portal
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Guild IDs (optional)
              {envOverrides.guild_ids && (
                <span className="ml-2 text-xs text-amber-600">
                  (Overridden by {envOverrides.guild_ids.env_var})
                </span>
              )}
            </label>
            <input
              type="text"
              className="input"
              value={form.guild_ids}
              onChange={(e) => setForm({ ...form, guild_ids: e.target.value })}
              placeholder="123456789,987654321"
              disabled={!!envOverrides.guild_ids}
            />
            <p className="text-xs text-gray-500 mt-1">
              Comma-separated Discord server IDs to restrict access
            </p>
          </div>

          <div>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={form.allow_registration}
                onChange={(e) => setForm({ ...form, allow_registration: e.target.checked })}
                disabled={!!envOverrides.allow_registration}
                className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
              />
              <span className="text-sm text-gray-700">
                Allow new users to register via Discord
              </span>
            </label>
            {envOverrides.allow_registration && (
              <p className="text-xs text-amber-600 mt-1 ml-6">
                Overridden by {envOverrides.allow_registration.env_var}
              </p>
            )}
          </div>

          <div className="pt-4">
            <button
              type="submit"
              disabled={mutation.isPending}
              className="px-4 py-2 rounded bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-60"
            >
              {mutation.isPending ? 'Saving...' : 'Save Discord Settings'}
            </button>
          </div>
        </form>
      </Section>

      <Section title="Setup Instructions">
        <SetupInstructions />
      </Section>
      
      <style>{`.input{width:100%;padding:0.5rem;border:1px solid #e5e7eb;border-radius:0.375rem;font-size:0.875rem}`}</style>
    </div>
  );
}

function StatusIndicator({ enabled }: { enabled: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <div
        className={`w-3 h-3 rounded-full ${
          enabled ? 'bg-green-500' : 'bg-gray-300'
        }`}
      />
      <span className="text-sm font-medium text-gray-900">
        {enabled ? 'Discord SSO is enabled' : 'Discord SSO is not configured'}
      </span>
    </div>
  );
}

function SetupInstructions() {
  return (
    <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 space-y-4">
      <h4 className="text-sm font-medium text-gray-900">
        Discord Developer Portal Setup
      </h4>
      <ol className="text-sm text-gray-600 list-decimal list-inside space-y-2">
        <li>
          Go to{' '}
          <a
            href="https://discord.com/developers/applications"
            target="_blank"
            rel="noopener noreferrer"
            className="text-indigo-600 hover:text-indigo-800 underline"
          >
            Discord Developer Portal
          </a>
        </li>
        <li>Create a new application or select an existing one</li>
        <li>Navigate to <strong>OAuth2 → General</strong></li>
        <li>Copy the <strong>Client ID</strong> and <strong>Client Secret</strong></li>
        <li>Add your redirect URI to the list of allowed redirects</li>
        <li>The redirect URI should be: <code className="bg-gray-100 px-1 rounded text-xs">https://your-domain/api/auth/discord/callback</code></li>
      </ol>
      
      <div className="pt-2 border-t border-gray-200">
        <p className="text-xs text-gray-500">
          <strong>Note:</strong> Environment variables (DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, etc.) 
          take precedence over values configured here.
        </p>
      </div>
    </div>
  );
}

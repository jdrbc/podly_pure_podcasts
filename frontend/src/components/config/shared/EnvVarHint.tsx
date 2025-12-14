import type { EnvOverrideEntry } from '../../../types';

interface EnvVarHintProps {
  meta?: EnvOverrideEntry;
}

export default function EnvVarHint({ meta }: EnvVarHintProps) {
  if (!meta?.env_var) {
    return null;
  }

  return (
    <code className="mt-1 block text-xs text-gray-500 font-mono">{meta.env_var}</code>
  );
}

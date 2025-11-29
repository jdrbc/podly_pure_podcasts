import type { ReactNode } from 'react';
import type { EnvOverrideEntry } from '../../../types';
import EnvVarHint from './EnvVarHint';

interface FieldProps {
  label: string;
  children: ReactNode;
  envMeta?: EnvOverrideEntry;
  labelWidth?: string;
}

export default function Field({
  label,
  children,
  envMeta,
  labelWidth = 'w-60',
}: FieldProps) {
  return (
    <label className="flex items-start justify-between gap-3">
      <div className={labelWidth}>
        <span className="block text-sm text-gray-700">{label}</span>
        <EnvVarHint meta={envMeta} />
      </div>
      <div className="flex-1">{children}</div>
    </label>
  );
}

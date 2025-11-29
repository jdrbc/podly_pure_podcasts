import { createContext, useContext } from 'react';
import type { UseConfigStateReturn } from '../../hooks/useConfigState';

export type ConfigTabId = 'default' | 'advanced' | 'users' | 'credits';
export type AdvancedSubtab = 'llm' | 'whisper' | 'processing' | 'output' | 'app';

export interface ConfigContextValue extends UseConfigStateReturn {
  activeTab: ConfigTabId;
  setActiveTab: (tab: ConfigTabId) => void;
  activeSubtab: AdvancedSubtab;
  setActiveSubtab: (subtab: AdvancedSubtab) => void;
  isAdmin: boolean;
  showSecurityControls: boolean;
}

export const ConfigContext = createContext<ConfigContextValue | null>(null);

export function useConfigContext(): ConfigContextValue {
  const context = useContext(ConfigContext);
  if (!context) {
    throw new Error('useConfigContext must be used within ConfigProvider');
  }
  return context;
}

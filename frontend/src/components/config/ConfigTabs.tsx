import { useMemo, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import useConfigState from '../../hooks/useConfigState';
import { ConfigContext, type ConfigTabId, type AdvancedSubtab } from './ConfigContext';
import { EnvOverrideWarningModal } from './shared';
import DefaultTab from './tabs/DefaultTab';
import AdvancedTab from './tabs/AdvancedTab';
import UserManagementTab from './tabs/UserManagementTab';
import CreditsTab from './tabs/CreditsTab';

const TABS: { id: ConfigTabId; label: string; adminOnly?: boolean }[] = [
  { id: 'default', label: 'Default' },
  { id: 'advanced', label: 'Advanced' },
  { id: 'users', label: 'User Management', adminOnly: true },
  { id: 'credits', label: 'Credits', adminOnly: true },
];

export default function ConfigTabs() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { user, requireAuth } = useAuth();
  const configState = useConfigState();

  const showSecurityControls = requireAuth && !!user;
  const isAdmin = showSecurityControls && user?.role === 'admin';

  // Get tab from URL or default
  const activeTab = useMemo<ConfigTabId>(() => {
    const urlTab = searchParams.get('tab') as ConfigTabId | null;
    if (urlTab && TABS.some((t) => t.id === urlTab)) {
      // Check admin-only tabs
      const tab = TABS.find((t) => t.id === urlTab);
      if (tab?.adminOnly && !isAdmin) {
        return 'default';
      }
      return urlTab;
    }
    return 'default';
  }, [searchParams, isAdmin]);

  const activeSubtab = useMemo<AdvancedSubtab>(() => {
    const urlSubtab = searchParams.get('section') as AdvancedSubtab | null;
    if (urlSubtab && ['llm', 'whisper', 'processing', 'output', 'app'].includes(urlSubtab)) {
      return urlSubtab;
    }
    return 'llm';
  }, [searchParams]);

  const setActiveTab = useCallback((tab: ConfigTabId) => {
    setSearchParams((prev) => {
      const newParams = new URLSearchParams(prev);
      newParams.set('tab', tab);
      if (tab !== 'advanced') {
        newParams.delete('section');
      }
      return newParams;
    }, { replace: true });
  }, [setSearchParams]);

  const setActiveSubtab = useCallback((subtab: AdvancedSubtab) => {
    setSearchParams((prev) => {
      const newParams = new URLSearchParams(prev);
      newParams.set('section', subtab);
      return newParams;
    }, { replace: true });
  }, [setSearchParams]);

  // Redirect if on admin-only tab without permission
  useEffect(() => {
    const tab = TABS.find((t) => t.id === activeTab);
    if (tab?.adminOnly && !isAdmin) {
      setActiveTab('default');
    }
  }, [isAdmin, activeTab, setActiveTab]);

  const contextValue = useMemo(
    () => ({
      ...configState,
      activeTab,
      setActiveTab,
      activeSubtab,
      setActiveSubtab,
      isAdmin,
      showSecurityControls,
    }),
    [configState, activeTab, setActiveTab, activeSubtab, setActiveSubtab, isAdmin, showSecurityControls]
  );

  const visibleTabs = TABS.filter((tab) => !tab.adminOnly || isAdmin);

  if (configState.isLoading || !configState.pending) {
    return <div className="text-sm text-gray-700">Loading configuration...</div>;
  }

  return (
    <ConfigContext.Provider value={contextValue}>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">Configuration</h2>
        </div>

        {/* Tab Navigation */}
        <div className="border-b border-gray-200 overflow-x-auto">
          <nav className="flex space-x-8 min-w-max" aria-label="Config tabs">
            {visibleTabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`py-3 px-1 border-b-2 font-medium text-sm whitespace-nowrap ${
                  activeTab === tab.id
                    ? 'border-indigo-500 text-indigo-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </div>

        {/* Tab Content */}
        <div className="mt-4">
          {activeTab === 'default' && <DefaultTab />}
          {activeTab === 'advanced' && <AdvancedTab />}
          {activeTab === 'users' && isAdmin && <UserManagementTab />}
          {activeTab === 'credits' && isAdmin && <CreditsTab />}
        </div>

        {/* Env Warning Modal */}
        {configState.showEnvWarning && configState.envWarningPaths.length > 0 && (
          <EnvOverrideWarningModal
            paths={configState.envWarningPaths}
            overrides={configState.envOverrides}
            onCancel={configState.handleDismissEnvWarning}
            onConfirm={configState.handleConfirmEnvWarning}
          />
        )}

        {/* Extra padding to prevent audio player overlay from obscuring bottom settings */}
        <div className="h-24"></div>
      </div>
    </ConfigContext.Provider>
  );
}

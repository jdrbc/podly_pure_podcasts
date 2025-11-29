import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'react-hot-toast';
import { BrowserRouter as Router, Routes, Route, Link, Navigate } from 'react-router-dom';
import { AudioPlayerProvider } from './contexts/AudioPlayerContext';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import HomePage from './pages/HomePage';
import JobsPage from './pages/JobsPage';
import ConfigPage from './pages/ConfigPage';
import LoginPage from './pages/LoginPage';
import AudioPlayer from './components/AudioPlayer';
import { creditsApi } from './services/api';
import './App.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 0,
      gcTime: 0,
      refetchOnMount: 'always',
      refetchOnWindowFocus: 'always',
      refetchOnReconnect: 'always',
    },
  },
});

function AppShell() {
  const { status, requireAuth, isAuthenticated, user, logout } = useAuth();
  const [showAddCreditsModal, setShowAddCreditsModal] = useState(false);
  const { data: balanceData } = useQuery({
    queryKey: ['credits', 'balance'],
    queryFn: creditsApi.getBalance,
    enabled: !!user && requireAuth && isAuthenticated,
    retry: false,
  });

  if (status === 'loading') {
    return (
      <div className="h-screen flex items-center justify-center bg-gray-50">
        <div className="flex flex-col items-center gap-4">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600" />
          <p className="text-sm text-gray-600">Loading authentication…</p>
        </div>
      </div>
    );
  }

  if (requireAuth && !isAuthenticated) {
    return <LoginPage />;
  }

  const showConfigLink = !requireAuth || user?.role === 'admin';

  return (
    <div className="h-screen bg-gray-50 flex flex-col overflow-hidden">
      <header className="bg-white shadow-sm border-b flex-shrink-0">
        <div className="px-2 sm:px-4 lg:px-6">
          <div className="flex items-center justify-between h-12">
            <div className="flex items-center">
              <Link to="/" className="flex items-center">
                <img 
                  src="/images/logos/logo.webp" 
                  alt="Podly" 
                  className="h-6 w-auto"
                />
                <h1 className="ml-2 text-lg font-semibold text-gray-900">
                  Podly
                </h1>
              </Link>
            </div>
            <nav className="flex items-center space-x-4">
              <Link to="/" className="text-sm font-medium text-gray-700 hover:text-gray-900">
                Home
              </Link>
              <Link to="/jobs" className="text-sm font-medium text-gray-700 hover:text-gray-900">
                Jobs
              </Link>
              {showConfigLink && (
                <Link to="/config" className="text-sm font-medium text-gray-700 hover:text-gray-900">
                  Config
                </Link>
              )}
              {requireAuth && user && (
                <div className="flex items-center gap-3 text-sm text-gray-600 flex-shrink-0">
                  {balanceData?.balance && (
                    <div className="flex items-center gap-1">
                      <div
                        className={`px-2 py-1 rounded-l-md border text-xs whitespace-nowrap ${
                          parseFloat(balanceData.balance) < 0
                            ? 'border-red-200 text-red-700 bg-red-50'
                            : 'border-emerald-200 text-emerald-700 bg-emerald-50'
                        }`}
                        title="Credits balance"
                      >
                        {parseFloat(balanceData.balance) < 0 ? 'Balance due: ' : 'Credits: '}
                        {balanceData.balance}
                      </div>
                      <button
                        onClick={() => setShowAddCreditsModal(true)}
                        className="px-2 py-1 rounded-r-md border border-l-0 border-blue-200 text-blue-700 bg-blue-50 hover:bg-blue-100 text-xs whitespace-nowrap transition-colors"
                        title="Add credits"
                      >
                        + Add
                      </button>
                    </div>
                  )}
                  <span className="hidden sm:inline whitespace-nowrap">{user.username}</span>
                  <button
                    onClick={logout}
                    className="px-3 py-1 border border-gray-200 rounded-md hover:bg-gray-100 transition-colors whitespace-nowrap"
                  >
                    Logout
                  </button>
                </div>
              )}
            </nav>
          </div>
        </div>
      </header>

      <main className="flex-1 px-2 sm:px-4 lg:px-6 py-4 overflow-auto">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/jobs" element={<JobsPage />} />
          {showConfigLink && <Route path="/config" element={<ConfigPage />} />}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>

      <AudioPlayer />
      <Toaster position="top-center" toastOptions={{ duration: 3000 }} />

      {/* Add Credits Modal */}
      {showAddCreditsModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full mx-4 p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-gray-900">Add Credits</h2>
              <button
                onClick={() => setShowAddCreditsModal(false)}
                className="text-gray-400 hover:text-gray-600 transition-colors"
              >
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="space-y-4">
              <p className="text-gray-600">
                To request additional credits, please join our Discord server and ask in the <strong>#preview-server</strong> channel.
              </p>
              <a
                href="https://discord.gg/FRB98GtF6N"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-center gap-2 w-full rounded-md bg-[#5865F2] px-4 py-2 text-white font-medium hover:bg-[#4752C4] transition-colors"
              >
                <svg className="h-5 w-5" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/>
                </svg>
                Join Discord Server
              </a>
            </div>
            <button
              onClick={() => setShowAddCreditsModal(false)}
              className="mt-4 w-full px-4 py-2 border border-gray-200 rounded-md text-gray-600 hover:bg-gray-50 transition-colors"
            >
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <AudioPlayerProvider>
          <Router>
            <AppShell />
          </Router>
        </AudioPlayerProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}

export default App;

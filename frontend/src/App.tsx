import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'react-hot-toast';
import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom';
import { AudioPlayerProvider } from './contexts/AudioPlayerContext';
import HomePage from './pages/HomePage';
import JobsPage from './pages/JobsPage';
import ConfigPage from './pages/ConfigPage';
import AudioPlayer from './components/AudioPlayer';
import './App.css';

const queryClient = new QueryClient();

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AudioPlayerProvider>
        <Router>
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
                    <Link to="/config" className="text-sm font-medium text-gray-700 hover:text-gray-900">
                      Config
                    </Link>
                  </nav>
                </div>
              </div>
            </header>

            <main className="flex-1 px-2 sm:px-4 lg:px-6 py-4 overflow-auto">
              <Routes>
              <Route path="/" element={<HomePage />} />
                <Route path="/jobs" element={<JobsPage />} />
                <Route path="/config" element={<ConfigPage />} />
              </Routes>
            </main>
            
            <AudioPlayer />
            <Toaster position="top-center" toastOptions={{ duration: 3000 }} />
          </div>
        </Router>
      </AudioPlayerProvider>
    </QueryClientProvider>
  );
}

export default App;

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { feedsApi } from '../services/api';
import FeedList from '../components/FeedList';
import FeedDetail from '../components/FeedDetail';
import AddFeedForm from '../components/AddFeedForm';
import type { Feed } from '../types';

export default function HomePage() {
  const [showAddForm, setShowAddForm] = useState(false);
  const [selectedFeed, setSelectedFeed] = useState<Feed | null>(null);

  const { data: feeds, isLoading, error, refetch } = useQuery({
    queryKey: ['feeds'],
    queryFn: feedsApi.getFeeds,
  });

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-md p-4">
        <p className="text-red-800">Error loading feeds. Please try again.</p>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col lg:flex-row gap-6">
      {/* Left Panel - Feed List (hidden on mobile when feed is selected) */}
      <div className={`flex-1 lg:max-w-md xl:max-w-lg flex flex-col ${
        selectedFeed ? 'hidden lg:flex' : 'flex'
      }`}>
        <div className="flex justify-between items-center mb-6">
          <h2 className="text-2xl font-bold text-gray-900">Podcast Feeds</h2>
          <button
            onClick={() => setShowAddForm(!showAddForm)}
            className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-md font-medium transition-colors"
          >
            {showAddForm ? 'Cancel' : 'Add Feed'}
          </button>
        </div>

        {showAddForm && (
          <div className="mb-6">
            <AddFeedForm 
              onSuccess={() => {
                setShowAddForm(false);
                refetch();
              }}
            />
          </div>
        )}

        <div className="flex-1 min-h-0 overflow-hidden">
          <FeedList 
            feeds={feeds || []} 
            onFeedDeleted={refetch}
            onFeedSelected={setSelectedFeed}
            selectedFeedId={selectedFeed?.id}
          />
        </div>
      </div>

      {/* Right Panel - Feed Detail */}
      {selectedFeed && (
        <div className={`flex-1 lg:flex-[2] ${
          selectedFeed ? 'flex' : 'hidden lg:flex'
        } flex-col bg-white rounded-lg shadow border overflow-hidden`}>
          <FeedDetail 
            feed={selectedFeed} 
            onClose={() => setSelectedFeed(null)}
            onFeedDeleted={() => {
              setSelectedFeed(null);
              refetch();
            }}
          />
        </div>
      )}

      {/* Empty State for Desktop */}
      {!selectedFeed && (
        <div className="hidden lg:flex flex-[2] items-center justify-center bg-gray-50 rounded-lg border-2 border-dashed border-gray-300">
          <div className="text-center">
            <svg className="mx-auto h-12 w-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
            </svg>
            <h3 className="mt-2 text-sm font-medium text-gray-900">No podcast selected</h3>
            <p className="mt-1 text-sm text-gray-500">Select a podcast from the list to view details and episodes.</p>
          </div>
        </div>
      )}
    </div>
  );
} 
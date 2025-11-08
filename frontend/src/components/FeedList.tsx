import { useMemo, useState } from 'react';
import type { Feed } from '../types';
import { feedsApi } from '../services/api';

interface FeedListProps {
  feeds: Feed[];
  onFeedDeleted: () => void;
  onFeedSelected: (feed: Feed) => void;
  selectedFeedId?: number;
}

export default function FeedList({ feeds, onFeedDeleted, onFeedSelected, selectedFeedId }: FeedListProps) {
  const [searchTerm, setSearchTerm] = useState('');
  const handleDeleteFeed = async (feedId: number) => {
    if (confirm('Are you sure you want to delete this feed?')) {
      try {
        await feedsApi.deleteFeed(feedId);
        onFeedDeleted();
      } catch (error) {
        console.error('Failed to delete feed:', error);
        alert('Failed to delete feed');
      }
    }
  };

  // Ensure feeds is an array
  const feedsArray = Array.isArray(feeds) ? feeds : [];

  if (feedsArray.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500 text-lg">No podcast feeds added yet.</p>
        <p className="text-gray-400 mt-2">Click "Add Feed" to get started.</p>
      </div>
    );
  }

  const filteredFeeds = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    if (!term) {
      return feedsArray;
    }
    return feedsArray.filter((feed) => {
      const title = feed.title?.toLowerCase() ?? '';
      const author = feed.author?.toLowerCase() ?? '';
      return title.includes(term) || author.includes(term);
    });
  }, [feedsArray, searchTerm]);

  return (
    <div className="flex flex-col h-full">
      <div className="mb-3">
        <label htmlFor="feed-search" className="sr-only">
          Search feeds
        </label>
        <input
          id="feed-search"
          type="search"
          placeholder="Search feeds"
          value={searchTerm}
          onChange={(event) => setSearchTerm(event.target.value)}
          className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder:text-gray-500 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
        />
      </div>
      <div className="space-y-2 overflow-y-auto h-full pb-20">
        {filteredFeeds.length === 0 ? (
          <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-gray-300 bg-gray-50 px-4 py-8 text-center">
            <p className="text-sm text-gray-500">
              No podcasts match &quot;{searchTerm}&quot;
            </p>
          </div>
        ) : (
          filteredFeeds.map((feed) => (
            <div 
              key={feed.id} 
              className={`bg-white rounded-lg shadow border cursor-pointer transition-all hover:shadow-md ${
                selectedFeedId === feed.id ? 'ring-2 ring-blue-500 border-blue-200' : ''
              }`}
              onClick={() => onFeedSelected(feed)}
            >
              <div className="p-4">
                <div className="flex items-start gap-3">
                  {/* Podcast Image */}
                  <div className="flex-shrink-0">
                    {feed.image_url ? (
                      <img
                        src={feed.image_url}
                        alt={feed.title}
                        className="w-12 h-12 rounded-lg object-cover"
                      />
                    ) : (
                      <div className="w-12 h-12 rounded-lg bg-gray-200 flex items-center justify-center">
                        <svg className="w-6 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                        </svg>
                      </div>
                    )}
                  </div>

                  {/* Feed Info */}
                  <div className="flex-1 min-w-0">
                    <h3 className="font-medium text-gray-900 line-clamp-2">{feed.title}</h3>
                    {feed.author && (
                      <p className="text-sm text-gray-600 mt-1">by {feed.author}</p>
                    )}
                    <div className="flex items-center justify-between mt-2">
                      <span className="text-xs text-gray-500">{feed.posts_count} episodes</span>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteFeed(feed.id);
                        }}
                        className="text-red-600 hover:text-red-800 text-xs font-medium opacity-0 group-hover:opacity-100 transition-opacity"
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
} 

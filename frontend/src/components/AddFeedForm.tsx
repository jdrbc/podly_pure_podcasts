import { useState } from 'react';
import { feedsApi } from '../services/api';
import type { PodcastSearchResult } from '../types';

interface AddFeedFormProps {
  onSuccess: () => void;
}

type AddMode = 'url' | 'search';

const PAGE_SIZE = 10;

export default function AddFeedForm({ onSuccess }: AddFeedFormProps) {
  const [url, setUrl] = useState('');
  const [activeMode, setActiveMode] = useState<AddMode>('search');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [addingFeedUrl, setAddingFeedUrl] = useState<string | null>(null);

  const [searchTerm, setSearchTerm] = useState('');
  const [searchResults, setSearchResults] = useState<PodcastSearchResult[]>([]);
  const [searchError, setSearchError] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [searchPage, setSearchPage] = useState(1);
  const [totalResults, setTotalResults] = useState(0);

  const resetSearchState = () => {
    setSearchResults([]);
    setSearchError('');
    setSearchPage(1);
    setTotalResults(0);
  };

  const handleSubmitManual = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return;

    setError('');
    await addFeed(url.trim(), 'url');
  };

  const addFeed = async (feedUrl: string, source: AddMode) => {
    setIsSubmitting(true);
    setAddingFeedUrl(source === 'url' ? 'manual' : feedUrl);
    setError('');

    try {
      await feedsApi.addFeed(feedUrl);
      if (source === 'url') {
        setUrl('');
      }
      onSuccess();
    } catch (err) {
      console.error('Failed to add feed:', err);
      setError('Failed to add feed. Please check the URL and try again.');
    } finally {
      setIsSubmitting(false);
      setAddingFeedUrl(null);
    }
  };

  const performSearch = async () => {
    if (!searchTerm.trim()) {
      setSearchError('Enter a search term to find podcasts.');
      return;
    }

    setIsSearching(true);
    setSearchError('');

    try {
      const response = await feedsApi.searchFeeds(searchTerm.trim());
      setSearchResults(response.results);
      setTotalResults(response.total ?? response.results.length);
      setSearchPage(1);
    } catch (err) {
      console.error('Podcast search failed:', err);
      setSearchError('Failed to search podcasts. Please try again.');
      setSearchResults([]);
    } finally {
      setIsSearching(false);
    }
  };

  const handleSearchSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await performSearch();
  };

  const handleAddFromSearch = async (result: PodcastSearchResult) => {
    await addFeed(result.feedUrl, 'search');
  };

  const totalPages =
    totalResults === 0 ? 1 : Math.max(1, Math.ceil(totalResults / PAGE_SIZE));
  const startIndex =
    totalResults === 0 ? 0 : (searchPage - 1) * PAGE_SIZE + 1;
  const endIndex =
    totalResults === 0
      ? 0
      : Math.min(searchPage * PAGE_SIZE, totalResults);
  const displayedResults = searchResults.slice(
    (searchPage - 1) * PAGE_SIZE,
    (searchPage - 1) * PAGE_SIZE + PAGE_SIZE
  );

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 sm:p-6">
      <h3 className="text-lg font-medium text-gray-900 mb-4">Add New Podcast Feed</h3>

      <div className="flex flex-col sm:flex-row gap-2 mb-4">
        <button
          type="button"
          onClick={() => {
            setActiveMode('url');
          }}
          className={`flex-1 px-3 py-2 rounded-md border transition-colors ${
            activeMode === 'url'
              ? 'bg-blue-50 border-blue-500 text-blue-700'
              : 'border-gray-200 text-gray-600 hover:bg-gray-100'
          }`}
        >
          Enter RSS URL
        </button>
        <button
          type="button"
          onClick={() => {
            setActiveMode('search');
            setError('');
            resetSearchState();
          }}
          className={`flex-1 px-3 py-2 rounded-md border ${
            activeMode === 'search'
              ? 'bg-blue-50 border-blue-500 text-blue-700'
              : 'border-gray-200 text-gray-600 hover:bg-gray-100'
          }`}
        >
          Search Podcasts
        </button>
      </div>

      {activeMode === 'url' && (
        <form onSubmit={handleSubmitManual} className="space-y-4">
          <div>
            <label htmlFor="feed-url" className="block text-sm font-medium text-gray-700 mb-1">
              RSS Feed URL
            </label>
            <input
              type="url"
              id="feed-url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com/podcast/feed.xml"
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              required
            />
          </div>

          {error && (
            <div className="text-red-600 text-sm">{error}</div>
          )}

          <div className="flex flex-col sm:flex-row sm:justify-end gap-3">
            <button
              type="submit"
              disabled={isSubmitting || !url.trim()}
              className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white px-4 py-2 rounded-md font-medium transition-colors sm:w-auto w-full"
            >
              {isSubmitting && addingFeedUrl === 'manual' ? 'Adding...' : 'Add Feed'}
            </button>
          </div>
        </form>
      )}

      {activeMode === 'search' && (
        <div className="space-y-4">
          <form onSubmit={handleSearchSubmit} className="flex flex-col md:flex-row gap-3">
            <div className="flex-1">
              <label htmlFor="search-term" className="block text-sm font-medium text-gray-700 mb-1">
                Search keyword
              </label>
              <input
                type="text"
                id="search-term"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="e.g. history, space, entrepreneurship"
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>

            <div className="flex items-end">
              <button
                type="submit"
                disabled={isSearching}
                className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white px-4 py-2 rounded-md font-medium transition-colors w-full md:w-auto"
              >
                {isSearching ? 'Searching...' : 'Search'}
              </button>
            </div>
          </form>

          {searchError && (
            <div className="text-red-600 text-sm">{searchError}</div>
          )}

          {isSearching && searchResults.length === 0 && (
            <div className="text-sm text-gray-600">Searching for podcasts...</div>
          )}

          {!isSearching && searchResults.length === 0 && totalResults === 0 && searchTerm && !searchError && (
            <div className="text-sm text-gray-600">No podcasts found. Try a different search term.</div>
          )}

          {searchResults.length > 0 && (
            <div className="space-y-3">
              <div className="flex justify-between items-center text-sm text-gray-500">
                <span>
                  Showing {startIndex}-{endIndex} of {totalResults} results
                </span>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() =>
                      setSearchPage((prev) => Math.max(prev - 1, 1))
                    }
                    disabled={isSearching || searchPage <= 1}
                    className="px-3 py-1 border border-gray-200 rounded-md disabled:text-gray-400 disabled:border-gray-200 hover:bg-gray-100 transition-colors"
                  >
                    Previous
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      setSearchPage((prev) => Math.min(prev + 1, totalPages))
                    }
                    disabled={isSearching || searchPage >= totalPages}
                    className="px-3 py-1 border border-gray-200 rounded-md disabled:text-gray-400 disabled:border-gray-200 hover:bg-gray-100 transition-colors"
                  >
                    Next
                  </button>
                </div>
              </div>

              <ul className="space-y-3 max-h-[45vh] sm:max-h-80 overflow-y-auto pr-2">
                {displayedResults.map((result) => (
                  <li
                    key={result.feedUrl}
                    className="flex gap-3 p-3 border border-gray-200 rounded-md bg-gray-50"
                  >
                    {result.artworkUrl ? (
                      <img
                        src={result.artworkUrl}
                        alt={result.title}
                        className="w-16 h-16 rounded-md object-cover"
                      />
                    ) : (
                      <div className="w-16 h-16 rounded-md bg-gray-200 flex items-center justify-center text-gray-500 text-xs">
                        No Image
                      </div>
                    )}
                    <div className="flex-1">
                      <h4 className="font-medium text-gray-900">{result.title}</h4>
                      {result.author && (
                        <p className="text-sm text-gray-600">{result.author}</p>
                      )}
                      {result.genres.length > 0 && (
                        <p className="text-xs text-gray-500 mt-1">
                          {result.genres.join(' · ')}
                        </p>
                      )}
                      <p className="text-xs text-gray-500 break-all mt-2">{result.feedUrl}</p>
                    </div>
                    <div className="flex items-center">
                      <button
                        type="button"
                        onClick={() => handleAddFromSearch(result)}
                        disabled={isSubmitting && addingFeedUrl === result.feedUrl}
                        className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white px-3 py-2 rounded-md text-sm transition-colors"
                      >
                        {isSubmitting && addingFeedUrl === result.feedUrl ? 'Adding...' : 'Add'}
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

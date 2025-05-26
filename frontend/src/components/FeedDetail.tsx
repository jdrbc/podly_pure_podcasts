import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useState, useEffect, useRef } from 'react';
import type { Feed, Episode } from '../types';
import { feedsApi } from '../services/api';
import DownloadButton from './DownloadButton';
import PlayButton from './PlayButton';
import ProcessingStatsButton from './ProcessingStatsButton';

interface FeedDetailProps {
  feed: Feed;
  onClose?: () => void;
  onFeedDeleted?: () => void;
}

type SortOption = 'newest' | 'oldest' | 'title';

export default function FeedDetail({ feed, onClose, onFeedDeleted }: FeedDetailProps) {
  const [sortBy, setSortBy] = useState<SortOption>('newest');
  const [showStickyHeader, setShowStickyHeader] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [showMenu, setShowMenu] = useState(false);
  const queryClient = useQueryClient();
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const feedHeaderRef = useRef<HTMLDivElement>(null);

  const { data: episodes, isLoading, error } = useQuery({
    queryKey: ['episodes', feed.id],
    queryFn: () => feedsApi.getFeedPosts(feed.id),
  });

  const whitelistMutation = useMutation({
    mutationFn: ({ guid, whitelisted }: { guid: string; whitelisted: boolean }) =>
      feedsApi.togglePostWhitelist(guid, whitelisted),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['episodes', feed.id] });
    },
  });

  const bulkWhitelistMutation = useMutation({
    mutationFn: () => feedsApi.toggleAllPostsWhitelist(feed.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['episodes', feed.id] });
    },
  });

  const deleteFeedMutation = useMutation({
    mutationFn: () => feedsApi.deleteFeed(feed.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['feeds'] });
      if (onFeedDeleted) {
        onFeedDeleted();
      }
    },
  });

  // Handle scroll to show/hide sticky header
  useEffect(() => {
    const scrollContainer = scrollContainerRef.current;
    const feedHeader = feedHeaderRef.current;
    
    if (!scrollContainer || !feedHeader) return;

    const handleScroll = () => {
      const scrollTop = scrollContainer.scrollTop;
      const feedHeaderHeight = feedHeader.offsetHeight;
      
      // Show sticky header when scrolled past the feed header
      setShowStickyHeader(scrollTop > feedHeaderHeight - 100);
    };

    scrollContainer.addEventListener('scroll', handleScroll);
    return () => scrollContainer.removeEventListener('scroll', handleScroll);
  }, []);

  // Handle click outside to close menu
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (showMenu && !(event.target as Element).closest('.menu-container')) {
        setShowMenu(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showMenu]);

  const handleWhitelistToggle = (episode: Episode) => {
    whitelistMutation.mutate({
      guid: episode.guid,
      whitelisted: !episode.whitelisted,
    });
  };

  const handleBulkWhitelistToggle = () => {
    bulkWhitelistMutation.mutate();
  };

  const handleDeleteFeed = () => {
    if (confirm(`Are you sure you want to delete "${feed.title}"? This action cannot be undone.`)) {
      deleteFeedMutation.mutate();
    }
  };

  const sortedEpisodes = episodes ? [...episodes].sort((a, b) => {
    switch (sortBy) {
      case 'newest':
        return new Date(b.release_date || 0).getTime() - new Date(a.release_date || 0).getTime();
      case 'oldest':
        return new Date(a.release_date || 0).getTime() - new Date(b.release_date || 0).getTime();
      case 'title':
        return a.title.localeCompare(b.title);
      default:
        return 0;
    }
  }) : [];

  // Calculate whitelist status for bulk button
  const whitelistedCount = episodes ? episodes.filter(ep => ep.whitelisted).length : 0;
  const totalCount = episodes ? episodes.length : 0;
  const allWhitelisted = totalCount > 0 && whitelistedCount === totalCount;

  const formatDate = (dateString: string | null) => {
    if (!dateString) return 'Unknown date';
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    });
  };

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return '';
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (hours > 0) {
      return `${hours}h ${minutes}m`;
    }
    return `${minutes}m`;
  };

  return (
    <div className="h-full flex flex-col bg-white relative">
      {/* Mobile Header */}
      <div className="flex items-center justify-between p-4 border-b lg:hidden">
        <h2 className="text-lg font-semibold text-gray-900">Podcast Details</h2>
        {onClose && (
          <button
            onClick={onClose}
            className="p-2 text-gray-400 hover:text-gray-600"
          >
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>

      {/* Sticky Header - appears when scrolling */}
      <div className={`absolute top-16 lg:top-0 left-0 right-0 z-10 bg-white border-b transition-all duration-300 ${
        showStickyHeader ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-full pointer-events-none'
      }`}>
        <div className="p-4">
          <div className="flex items-center gap-3">
            {feed.image_url && (
              <img
                src={feed.image_url}
                alt={feed.title}
                className="w-10 h-10 rounded-lg object-cover"
              />
            )}
            <div className="flex-1 min-w-0">
              <h2 className="font-semibold text-gray-900 truncate">{feed.title}</h2>
              {feed.author && (
                <p className="text-sm text-gray-600 truncate">by {feed.author}</p>
              )}
            </div>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as SortOption)}
              className="text-sm border border-gray-300 rounded-md px-3 py-1 bg-white"
            >
              <option value="newest">Newest First</option>
              <option value="oldest">Oldest First</option>
              <option value="title">Title A-Z</option>
            </select>

            {/* do not add addtional controls to sticky headers */}
          </div>
        </div>
      </div>

      {/* Scrollable Content */}
      <div ref={scrollContainerRef} className="flex-1 overflow-y-auto">
        {/* Feed Info Header */}
        <div ref={feedHeaderRef} className="p-6 border-b">
          <div className="flex flex-col gap-6">
            {/* Top Section: Image and Title */}
            <div className="flex items-end gap-6">
              {/* Podcast Image */}
              <div className="flex-shrink-0">
                {feed.image_url ? (
                  <img
                    src={feed.image_url}
                    alt={feed.title}
                    className="w-32 h-32 sm:w-40 sm:h-40 rounded-lg object-cover shadow-lg"
                  />
                ) : (
                  <div className="w-32 h-32 sm:w-40 sm:h-40 rounded-lg bg-gray-200 flex items-center justify-center shadow-lg">
                    <svg className="w-16 h-16 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                    </svg>
                  </div>
                )}
              </div>

              {/* Title aligned to bottom-left of image */}
              <div className="flex-1 min-w-0 pb-2">
                <h1 className="text-2xl font-bold text-gray-900 mb-1">{feed.title}</h1>
                {feed.author && (
                  <p className="text-lg text-gray-600">by {feed.author}</p>
                )}
                <div className="mt-2 text-sm text-gray-500">
                  <span>{feed.posts_count} episodes</span>
                </div>
              </div>
            </div>

            {/* RSS Button and Menu */}
            <div className="flex items-center gap-3">
              {/* Podly RSS Subscribe Button */}
              <button 
                onClick={() => window.open(`http://localhost:5002/feed/${feed.id}`, '_blank')}
                className="flex items-center gap-2 px-4 py-2 bg-orange-500 hover:bg-orange-600 text-white rounded-lg font-medium transition-colors"
              >
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M6.503 20.752c0 1.794-1.456 3.248-3.251 3.248S0 22.546 0 20.752s1.456-3.248 3.252-3.248 3.251 1.454 3.251 3.248zM1.677 6.082v4.15c6.988 0 12.65 5.662 12.65 12.65h4.15c0-9.271-7.529-16.8-16.8-16.8zM1.677.014v4.151C14.44 4.165 24.836 14.561 24.85 27.324H29c-.014-15.344-12.342-27.672-27.323-27.31z"/>
                </svg>
                Subscribe to Podly RSS
              </button>

              {/* Ellipsis Menu */}
              <div className="relative menu-container">
                <button
                  onClick={() => setShowMenu(!showMenu)}
                  className="w-10 h-10 rounded-lg bg-gray-100 hover:bg-gray-200 flex items-center justify-center text-gray-600 hover:text-gray-800 transition-colors"
                >
                  <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 8c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"/>
                  </svg>
                </button>

                {/* Dropdown Menu */}
                {showMenu && (
                  <div className="absolute top-full left-0 mt-1 w-56 bg-white rounded-lg shadow-lg border border-gray-200 py-1 z-20">
                    <button
                      onClick={() => {
                        if (!allWhitelisted) {
                          handleBulkWhitelistToggle();
                        }
                        setShowMenu(false);
                      }}
                      disabled={bulkWhitelistMutation.isPending || totalCount === 0 || allWhitelisted}
                      className="w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-3 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <span className="text-green-600">✓</span>
                      Enable all episodes
                    </button>
                    
                    <button
                      onClick={() => {
                        if (allWhitelisted) {
                          handleBulkWhitelistToggle();
                        }
                        setShowMenu(false);
                      }}
                      disabled={bulkWhitelistMutation.isPending || totalCount === 0 || !allWhitelisted}
                      className="w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-3 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <span className="text-red-600">⛔</span>
                      Disable all episodes
                    </button>

                    <button
                      onClick={() => {
                        setShowHelp(!showHelp);
                        setShowMenu(false);
                      }}
                      className="w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-3"
                    >
                      <span className="text-blue-600">ℹ️</span>
                      Explain whitelist
                    </button>

                    <button
                      onClick={() => {
                        window.open(feed.rss_url, '_blank');
                        setShowMenu(false);
                      }}
                      className="w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-3"
                    >
                      <svg className="w-4 h-4 text-gray-500" fill="currentColor" viewBox="0 0 24 24">
                        <path d="M6.503 20.752c0 1.794-1.456 3.248-3.251 3.248S0 22.546 0 20.752s1.456-3.248 3.252-3.248 3.251 1.454 3.251 3.248zM1.677 6.082v4.15c6.988 0 12.65 5.662 12.65 12.65h4.15c0-9.271-7.529-16.8-16.8-16.8zM1.677.014v4.151C14.44 4.165 24.836 14.561 24.85 27.324H29c-.014-15.344-12.342-27.672-27.323-27.31z"/>
                      </svg>
                      Original RSS feed
                    </button>

                    <div className="border-t border-gray-100 my-1"></div>

                    <button
                      onClick={() => {
                        handleDeleteFeed();
                        setShowMenu(false);
                      }}
                      disabled={deleteFeedMutation.isPending}
                      className="w-full px-4 py-2 text-left text-sm text-red-600 hover:bg-red-50 flex items-center gap-3 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                      Delete feed
                    </button>
                  </div>
                )}
              </div>
            </div>

            {/* Feed Description */}
            {feed.description && (
              <div className="text-gray-700 leading-relaxed">
                <p>{feed.description.replace(/<[^>]*>/g, '')}</p>
              </div>
            )}
          </div>
        </div>

        {/* Episodes Header with Sort Only */}
        <div className="p-4 border-b bg-gray-50">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold text-gray-900">Episodes</h3>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as SortOption)}
              className="text-sm border border-gray-300 rounded-md px-3 py-1 bg-white"
            >
              <option value="newest">Newest First</option>
              <option value="oldest">Oldest First</option>
              <option value="title">Title A-Z</option>
            </select>
          </div>
        </div>

        {/* Help Explainer */}
        {showHelp && (
          <div className="bg-blue-50 border-b border-blue-200 p-4">
            <div className="max-w-2xl">
              <h4 className="font-semibold text-blue-900 mb-2">About Enabling & Disabling Ad Removal</h4>
              <div className="text-sm text-blue-800 space-y-2 text-left">
                <p>
                  <strong>Enabled episodes</strong> are processed by Podly to automatically detect and remove advertisements, 
                  giving you a clean, ad-free listening experience.
                </p>
                <p>
                  <strong>Disabled episodes</strong> are not processed and won't be available for download through Podly. 
                  This is useful for episodes you don't want to listen to.
                </p>
                <p>
                  <strong>Why whitelist episodes?</strong> Processing takes time and computational resources. 
                  By only enabling episodes you want to hear, you can save LLM credits. This is useful when adding a new feed with a large back catalog.
                </p>
              </div>
              <button
                onClick={() => setShowHelp(false)}
                className="mt-3 text-xs text-blue-600 hover:text-blue-800 font-medium"
              >
                Got it, hide this explanation
              </button>
            </div>
          </div>
        )}

        {/* Episodes List */}
        <div>
          {isLoading ? (
            <div className="p-6">
              <div className="animate-pulse space-y-4">
                {[...Array(5)].map((_, i) => (
                  <div key={i} className="h-20 bg-gray-200 rounded"></div>
                ))}
              </div>
            </div>
          ) : error ? (
            <div className="p-6">
              <p className="text-red-600">Failed to load episodes</p>
            </div>
          ) : sortedEpisodes.length === 0 ? (
            <div className="p-6 text-center">
              <p className="text-gray-500">No episodes found</p>
            </div>
          ) : (
            <div className="divide-y divide-gray-200">
              {sortedEpisodes.map((episode) => (
                <div key={episode.id} className="p-4 hover:bg-gray-50">
                  <div className="flex flex-col gap-3">
                    {/* Top Section: Thumbnail and Title */}
                    <div className="flex items-start gap-3">
                      {/* Episode/Podcast Thumbnail */}
                      <div className="flex-shrink-0">
                        {(episode.image_url || feed.image_url) ? (
                          <img
                            src={episode.image_url || feed.image_url}
                            alt={episode.title}
                            className="w-16 h-16 rounded-lg object-cover"
                          />
                        ) : (
                          <div className="w-16 h-16 rounded-lg bg-gray-200 flex items-center justify-center">
                            <svg className="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                            </svg>
                          </div>
                        )}
                      </div>
                      
                      {/* Title and Feed Name */}
                      <div className="flex-1 min-w-0 text-left">
                        <h4 className="font-medium text-gray-900 mb-1 line-clamp-2 text-left">
                          {episode.title}
                        </h4>
                        <p className="text-sm text-gray-600 text-left">
                          {feed.title}
                        </p>
                      </div>
                    </div>

                    {/* Episode Description */}
                    {episode.description && (
                      <div className="text-left">
                        <p className="text-sm text-gray-500 line-clamp-3">
                          {episode.description.replace(/<[^>]*>/g, '').substring(0, 300)}...
                        </p>
                      </div>
                    )}

                    {/* Metadata: Date and Duration */}
                    <div className="flex items-center gap-2 text-sm text-gray-500">
                      <span>{formatDate(episode.release_date)}</span>
                      {episode.duration && (
                        <>
                          <span>•</span>
                          <span>{formatDuration(episode.duration)}</span>
                        </>
                      )}
                    </div>

                    {/* Bottom Controls */}
                    <div className="flex items-center justify-between">
                      {/* Left side: Whitelist and Download buttons */}
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => handleWhitelistToggle(episode)}
                          disabled={whitelistMutation.isPending}
                          className={`px-3 py-1 text-xs font-medium rounded-full transition-colors flex items-center justify-center gap-1 ${
                            episode.whitelisted
                              ? 'bg-green-100 text-green-800 hover:bg-green-200'
                              : 'bg-gray-100 text-gray-800 hover:bg-gray-200'
                          } ${whitelistMutation.isPending ? 'opacity-50 cursor-not-allowed' : ''}`}
                        >
                          {whitelistMutation.isPending ? (
                            <>
                              <svg className="w-3 h-3 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                              </svg>
                              <span>...</span>
                            </>
                          ) : episode.whitelisted ? (
                            <>
                              <span>✅</span>
                              <span>Enabled</span>
                            </>
                          ) : (
                            <>
                              <span>⛔</span>
                              <span>Disabled</span>
                            </>
                          )}
                        </button>
                        
                        <DownloadButton
                          episodeGuid={episode.guid}
                          isWhitelisted={episode.whitelisted}
                          hasProcessedAudio={episode.has_processed_audio}
                          feedId={feed.id}
                          className="min-w-[100px]"
                        />
                        
                        <ProcessingStatsButton
                          episodeGuid={episode.guid}
                          hasProcessedAudio={episode.has_processed_audio}
                          className="ml-2"
                        />
                      </div>

                      {/* Right side: Play button */}
                      <div className="flex-shrink-0">
                        <PlayButton
                          episode={episode}
                          className="ml-2"
                        />
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
} 
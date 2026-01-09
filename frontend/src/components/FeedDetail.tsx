import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useState, useEffect, useRef, useMemo } from 'react';
import { toast } from 'react-hot-toast';
import type { Feed, Episode, PagedResult } from '../types';
import { feedsApi } from '../services/api';
import DownloadButton from './DownloadButton';
import PlayButton from './PlayButton';
import ProcessingStatsButton from './ProcessingStatsButton';
import EpisodeProcessingStatus from './EpisodeProcessingStatus';
import FeedSettingsModal from './FeedSettingsModal';
import { useAuth } from '../contexts/AuthContext';
import { copyToClipboard } from '../utils/clipboard';
import { emitDiagnosticError } from '../utils/diagnostics';
import { getHttpErrorInfo } from '../utils/httpError';

interface FeedDetailProps {
  feed: Feed;
  onClose?: () => void;
  onFeedDeleted?: () => void;
}

type SortOption = 'newest' | 'oldest' | 'title';

interface ProcessingEstimate {
  post_guid: string;
  estimated_minutes: number;
  can_process: boolean;
  reason: string | null;
}

const EPISODES_PAGE_SIZE = 25;

export default function FeedDetail({ feed, onClose, onFeedDeleted }: FeedDetailProps) {
  const { requireAuth, isAuthenticated, user } = useAuth();
  const [sortBy, setSortBy] = useState<SortOption>('newest');
  const [showStickyHeader, setShowStickyHeader] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [showMenu, setShowMenu] = useState(false);
  const queryClient = useQueryClient();
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const feedHeaderRef = useRef<HTMLDivElement>(null);
  const [currentFeed, setCurrentFeed] = useState(feed);
  const [pendingEpisode, setPendingEpisode] = useState<Episode | null>(null);
  const [showProcessingModal, setShowProcessingModal] = useState(false);
  const [processingEstimate, setProcessingEstimate] = useState<ProcessingEstimate | null>(null);
  const [isEstimating, setIsEstimating] = useState(false);
  const [estimateError, setEstimateError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [showSettingsModal, setShowSettingsModal] = useState(false);

  const isAdmin = !requireAuth || user?.role === 'admin';
  const whitelistedOnly = requireAuth && !isAdmin;

  const {
    data: episodesPage,
    isLoading,
    isFetching,
    error,
  } = useQuery<PagedResult<Episode>, Error, PagedResult<Episode>, [string, number, number, boolean]>({
    queryKey: ['episodes', currentFeed.id, page, whitelistedOnly],
    queryFn: () =>
      feedsApi.getFeedPosts(currentFeed.id, {
        page,
        pageSize: EPISODES_PAGE_SIZE,
        whitelistedOnly,
      }),
    placeholderData: (previousData) => previousData,
  });

  const whitelistMutation = useMutation({
    mutationFn: ({ guid, whitelisted, triggerProcessing }: { guid: string; whitelisted: boolean; triggerProcessing?: boolean }) =>
      feedsApi.togglePostWhitelist(guid, whitelisted, triggerProcessing),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['episodes', currentFeed.id] });
    },
    onError: (err) => {
      const { status, data, message } = getHttpErrorInfo(err);
      emitDiagnosticError({
        title: 'Failed to update whitelist status',
        message,
        kind: status ? 'http' : 'network',
        details: {
          status,
          response: data,
        },
      });
    },
  });

  const bulkWhitelistMutation = useMutation({
    mutationFn: () => feedsApi.toggleAllPostsWhitelist(currentFeed.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['episodes', currentFeed.id] });
    },
  });

  const refreshFeedMutation = useMutation({
    mutationFn: () => feedsApi.refreshFeed(currentFeed.id),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['feeds'] });
      queryClient.invalidateQueries({ queryKey: ['episodes', currentFeed.id] });
      toast.success(data?.message ?? 'Feed refreshed');
    },
    onError: (err) => {
      console.error('Failed to refresh feed', err);
      const { status, data, message } = getHttpErrorInfo(err);
      emitDiagnosticError({
        title: 'Failed to refresh feed',
        message,
        kind: status ? 'http' : 'network',
        details: {
          status,
          response: data,
          feedId: currentFeed.id,
        },
      });
    },
  });

  const deleteFeedMutation = useMutation({
    mutationFn: () => feedsApi.deleteFeed(currentFeed.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['feeds'] });
      if (onFeedDeleted) {
        onFeedDeleted();
      }
    },
    onError: (err) => {
      console.error('Failed to delete feed', err);
      const { status, data, message } = getHttpErrorInfo(err);
      emitDiagnosticError({
        title: 'Failed to delete feed',
        message,
        kind: status ? 'http' : 'network',
        details: {
          status,
          response: data,
          feedId: currentFeed.id,
        },
      });
    },
  });

  const joinFeedMutation = useMutation({
    mutationFn: () => feedsApi.joinFeed(currentFeed.id),
    onSuccess: (data) => {
      toast.success('Joined feed');
      setCurrentFeed(data);
      queryClient.invalidateQueries({ queryKey: ['feeds'] });
    },
    onError: (err) => {
      console.error('Failed to join feed', err);
      const { status, data, message } = getHttpErrorInfo(err);
      emitDiagnosticError({
        title: 'Failed to join feed',
        message,
        kind: status ? 'http' : 'network',
        details: {
          status,
          response: data,
          feedId: currentFeed.id,
        },
      });
    },
  });

  const leaveFeedMutation = useMutation({
    mutationFn: () => feedsApi.leaveFeed(currentFeed.id),
    onSuccess: () => {
      toast.success('Removed from your feeds');
      setCurrentFeed((prev) => (prev ? { ...prev, is_member: false, is_active_subscription: false } : prev));
      queryClient.invalidateQueries({ queryKey: ['feeds'] });
      if (onFeedDeleted && !isAdmin) {
        onFeedDeleted();
      }
    },
    onError: (err) => {
      console.error('Failed to leave feed', err);
      const { status, data, message } = getHttpErrorInfo(err);
      emitDiagnosticError({
        title: 'Failed to remove feed',
        message,
        kind: status ? 'http' : 'network',
        details: {
          status,
          response: data,
          feedId: currentFeed.id,
        },
      });
    },
  });

  useEffect(() => {
    setCurrentFeed(feed);
  }, [feed]);

  useEffect(() => {
    setPage(1);
  }, [feed.id, whitelistedOnly]);

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
    if (!episode.whitelisted) {
      setPendingEpisode(episode);
      setShowProcessingModal(true);
      setProcessingEstimate(null);
      setEstimateError(null);
      setIsEstimating(true);
      feedsApi
        .getProcessingEstimate(episode.guid)
        .then((estimate) => {
          setProcessingEstimate(estimate);
        })
        .catch((err) => {
          console.error('Failed to load processing estimate', err);
          const { status, data, message } = getHttpErrorInfo(err);
          emitDiagnosticError({
            title: 'Failed to load processing estimate',
            message,
            kind: status ? 'http' : 'network',
            details: {
              status,
              response: data,
              postGuid: episode.guid,
            },
          });
          setEstimateError(message ?? 'Unable to estimate processing time');
        })
        .finally(() => setIsEstimating(false));
      return;
    }

    whitelistMutation.mutate({
      guid: episode.guid,
      whitelisted: false,
    });
  };

  const handleConfirmProcessing = () => {
    if (!pendingEpisode) return;
    whitelistMutation.mutate(
      {
        guid: pendingEpisode.guid,
        whitelisted: true,
        triggerProcessing: true,
      },
      {
        onSuccess: () => {
          setShowProcessingModal(false);
          setPendingEpisode(null);
          setProcessingEstimate(null);
        },
      }
    );
  };

  const handleCancelProcessing = () => {
    setShowProcessingModal(false);
    setPendingEpisode(null);
    setProcessingEstimate(null);
    setEstimateError(null);
  };

  const isMember = Boolean(currentFeed.is_member);
  const isActiveSubscription = currentFeed.is_active_subscription !== false;

  // Admins can manage everything; regular users are read-only.
  const canDeleteFeed = isAdmin; // only admins can delete feeds
  const canModifyEpisodes = !requireAuth ? true : Boolean(isAdmin);
  const canBulkModifyEpisodes = !requireAuth ? true : Boolean(isAdmin);
  const canSubscribe = !requireAuth || isMember;
  const showPodlyRssButton = !(requireAuth && isAdmin && !isMember);
  const showWhitelistUi = canModifyEpisodes && isAdmin;

  const episodes = episodesPage?.items ?? [];
  const totalCount = episodesPage?.total ?? 0;
  const whitelistedCount =
    episodesPage?.whitelisted_total ?? episodes.filter((ep: Episode) => ep.whitelisted).length;
  const totalPages = Math.max(
    1,
    episodesPage?.total_pages ?? Math.ceil(totalCount / EPISODES_PAGE_SIZE)
  );
  const hasEpisodes = totalCount > 0;
  const visibleStart = hasEpisodes ? (page - 1) * EPISODES_PAGE_SIZE + 1 : 0;
  const visibleEnd = hasEpisodes ? Math.min(totalCount, page * EPISODES_PAGE_SIZE) : 0;

  useEffect(() => {
    if (page > totalPages && totalPages > 0) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  const handleBulkWhitelistToggle = () => {
    if (requireAuth && !isAdmin) {
      toast.error('Only admins can bulk toggle whitelist status.');
      return;
    }
    bulkWhitelistMutation.mutate();
  };

  const handleDeleteFeed = () => {
    if (confirm(`Are you sure you want to delete "${currentFeed.title}"? This action cannot be undone.`)) {
      deleteFeedMutation.mutate();
    }
  };

  const episodesToShow = useMemo(() => episodes, [episodes]);

  const sortedEpisodes = useMemo(() => {
    const list = [...episodesToShow];
    return list.sort((a, b) => {
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
    });
  }, [episodesToShow, sortBy]);

  // Calculate whitelist status for bulk button
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

  const handleCopyRssToClipboard = async () => {
    if (requireAuth && !isAuthenticated) {
      toast.error('Please sign in to copy a protected RSS URL.');
      return;
    }

    try {
      let rssUrl: string;
      if (requireAuth) {
        const response = await feedsApi.createProtectedFeedShareLink(currentFeed.id);
        rssUrl = response.url;
      } else {
        rssUrl = new URL(`/feed/${currentFeed.id}`, window.location.origin).toString();
      }

      await copyToClipboard(rssUrl, 'Copy the Feed RSS URL:', 'Feed URL copied to clipboard!');
    } catch (err) {
      console.error('Failed to copy feed URL', err);
      toast.error('Failed to copy feed URL');
    }
  };

  const handleCopyOriginalRssToClipboard = async () => {
    try {
      const rssUrl = currentFeed.rss_url || '';
      if (!rssUrl) throw new Error('No RSS URL');

      await copyToClipboard(rssUrl, 'Copy the Original RSS URL:', 'Original RSS URL copied to clipboard');
    } catch (err) {
      console.error('Failed to copy original RSS URL', err);
      toast.error('Failed to copy original RSS URL');
    }
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
            {currentFeed.image_url && (
              <img
                src={currentFeed.image_url}
                alt={currentFeed.title}
                className="w-10 h-10 rounded-lg object-cover"
              />
            )}
            <div className="flex-1 min-w-0">
              <h2 className="font-semibold text-gray-900 truncate">{currentFeed.title}</h2>
              {currentFeed.author && (
                <p className="text-sm text-gray-600 truncate">by {currentFeed.author}</p>
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
                {currentFeed.image_url ? (
                  <img
                    src={currentFeed.image_url}
                    alt={currentFeed.title}
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
                <h1 className="text-2xl font-bold text-gray-900 mb-1">{currentFeed.title}</h1>
                {currentFeed.author && (
                  <p className="text-lg text-gray-600">by {currentFeed.author}</p>
                )}
                <div className="mt-2 text-sm text-gray-500">
                  <span>{totalCount} episodes visible</span>
                </div>
                {requireAuth && isAdmin && (
                  <div className="mt-2 flex items-center gap-2 flex-wrap text-sm">
                    <span
                      className={`px-2 py-1 rounded-full text-xs font-medium border ${
                        isMember
                          ? 'bg-green-50 text-green-700 border-green-200'
                          : 'bg-gray-100 text-gray-600 border-gray-200'
                      }`}
                    >
                      {isMember ? 'Joined' : 'Not joined'}
                    </span>
                    {isMember && !isActiveSubscription && (
                      <span className="px-2 py-1 rounded-full text-xs font-medium border bg-amber-50 text-amber-700 border-amber-200">
                        Paused
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* RSS Button and Menu */}
            <div className="flex items-center gap-3">
              {/* Podly RSS Subscribe Button */}
              {showPodlyRssButton && (
                <button
                  onClick={handleCopyRssToClipboard}
                  title="Copy Podly RSS feed URL"
                  className={`flex items-center gap-3 px-5 py-2 bg-black hover:bg-gray-900 text-white rounded-lg font-medium transition-colors ${
                    !canSubscribe ? 'opacity-60 cursor-not-allowed' : ''
                  }`}
                  disabled={!canSubscribe}
                >
                  <img
                    src="/rss-round-color-icon.svg"
                    alt="Podly RSS"
                    className="w-6 h-6"
                    aria-hidden="true"
                  />
                  <span className="text-white">
                    {canSubscribe ? 'Subscribe to Podly RSS' : 'Join feed to subscribe'}
                  </span>
                </button>
              )}

              {requireAuth && isAdmin && !isMember && (
                <button
                  onClick={() => joinFeedMutation.mutate()}
                  disabled={joinFeedMutation.isPending}
                  className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-colors ${
                    joinFeedMutation.isPending
                      ? 'bg-blue-100 text-blue-300 cursor-not-allowed'
                      : 'bg-blue-600 text-white hover:bg-blue-700'
                  }`}
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                  </svg>
                  Join feed
                </button>
              )}

              {canModifyEpisodes && (
                <button
                  onClick={() => refreshFeedMutation.mutate()}
                  disabled={refreshFeedMutation.isPending}
                  title="Refresh feed from source"
                  className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-colors ${
                    refreshFeedMutation.isPending
                      ? 'bg-gray-200 text-gray-500 cursor-not-allowed'
                      : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                  }`}
                >
                  <img
                    className={`w-4 h-4 ${refreshFeedMutation.isPending ? 'animate-spin' : ''}`}
                    src="/reload-icon.svg"
                    alt="Refresh feed"
                    aria-hidden="true"
                  />
                  <span>Refresh Feed</span>
                </button>
              )}

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
                  <div className="absolute top-full right-0 mt-1 w-56 bg-white rounded-lg shadow-lg border border-gray-200 py-1 z-20 max-w-[calc(100vw-2rem)]">
                      {canBulkModifyEpisodes && (
                        <>
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
                      </>
                      )}

                      {isAdmin && (
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
                      )}

                      {isAdmin && (
                        <button
                          onClick={() => {
                            setShowSettingsModal(true);
                            setShowMenu(false);
                          }}
                          className="w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-3"
                        >
                          <svg className="w-4 h-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                          </svg>
                          Feed settings
                        </button>
                      )}

                    <button
                      onClick={() => {
                        handleCopyOriginalRssToClipboard();
                        setShowMenu(false);
                      }}
                      className="w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-3"
                    >
                      <img src="/rss-round-color-icon.svg" alt="Original RSS" className="w-4 h-4" />
                      Original RSS feed
                    </button>

                    {requireAuth && isAdmin && isMember && (
                      <>
                        <div className="border-t border-gray-100 my-1"></div>
                        <button
                          onClick={() => {
                            leaveFeedMutation.mutate();
                            setShowMenu(false);
                          }}
                          disabled={leaveFeedMutation.isPending}
                          className="w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-3 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                          </svg>
                          Leave feed
                        </button>
                      </>
                    )}

                    {canDeleteFeed && (
                      <>
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
                      </>
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* Feed Description */}
            {currentFeed.description && (
              <div className="text-gray-700 leading-relaxed">
                <p>{currentFeed.description.replace(/<[^>]*>/g, '')}</p>
              </div>
            )}
          </div>
        </div>

        {/* Inactive Subscription Warning */}
        {currentFeed.is_member && currentFeed.is_active_subscription === false && (
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 flex items-start gap-3">
            <svg className="w-5 h-5 text-amber-600 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <div>
              <h3 className="text-sm font-medium text-amber-800">Processing Paused</h3>
              <p className="text-sm text-amber-700 mt-1">
                This feed exceeds your plan's allowance. New episodes will not be processed automatically until you upgrade your plan or leave other feeds.
              </p>
            </div>
          </div>
        )}

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

            {/* Help Explainer (admins only) */}
            {showHelp && isAdmin && (
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
                  Enable only the episodes you want to hear to keep your feed focused. This is useful when adding a new feed with a large back catalog.
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
                  <div className={`flex flex-col ${episode.whitelisted ? 'gap-3' : 'gap-2'}`}>
                    {/* Top Section: Thumbnail and Title */}
                    <div className="flex items-start gap-3">
                      {/* Episode/Podcast Thumbnail */}
                      <div className="flex-shrink-0">
                        {(episode.image_url || currentFeed.image_url) ? (
                          <img
                            src={episode.image_url || currentFeed.image_url}
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
                          {currentFeed.title}
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

                    {/* Metadata: Status, Date and Duration */}
                    <div className="flex items-center gap-2 text-sm text-gray-500">
                      {showWhitelistUi && (
                        <>
                          <button
                            onClick={() => handleWhitelistToggle(episode)}
                            disabled={whitelistMutation.isPending}
                            className={`px-2 py-1 text-xs font-medium rounded-full transition-colors flex items-center justify-center gap-1 ${
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
                          <span>•</span>
                        </>
                      )}
                      <span>{formatDate(episode.release_date)}</span>
                      {episode.duration && (
                        <>
                          <span>•</span>
                          <span>{formatDuration(episode.duration)}</span>
                        </>
                      )}
                      <>
                        <span>•</span>
                        <span>
                          {episode.download_count ? episode.download_count : 0} {episode.download_count === 1 ? 'download' : 'downloads'}
                        </span>
                      </>
                    </div>

                    {/* Bottom Controls - only show if episode is whitelisted */}
                    {episode.whitelisted && (
                      <div className="flex items-center justify-between">
                        {/* Left side: Download buttons */}
                        <div className="flex items-center gap-2">
                          <DownloadButton
                            episodeGuid={episode.guid}
                            isWhitelisted={episode.whitelisted}
                            hasProcessedAudio={episode.has_processed_audio}
                            feedId={currentFeed.id}
                            canModifyEpisodes={canModifyEpisodes}
                            className="min-w-[100px]"
                          />

                          <EpisodeProcessingStatus
                            episodeGuid={episode.guid}
                            isWhitelisted={episode.whitelisted}
                            hasProcessedAudio={episode.has_processed_audio}
                            feedId={currentFeed.id}
                          />

                          <ProcessingStatsButton
                            episodeGuid={episode.guid}
                            hasProcessedAudio={episode.has_processed_audio}
                          />
                        </div>

                        {/* Right side: Play button */}
                        <div className="flex-shrink-0 w-12 flex justify-end">
                          {episode.has_processed_audio && (
                            <PlayButton
                              episode={episode}
                              className="ml-2"
                            />
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {totalCount > 0 && (
          <div className="flex items-center justify-between px-4 py-3 border-t bg-white">
            <div className="text-sm text-gray-600">
              Showing {visibleStart}-{visibleEnd} of {totalCount} episodes
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPage((prev) => Math.max(1, prev - 1))}
                disabled={page === 1 || isLoading || isFetching}
                className={`px-3 py-1 text-sm rounded-md border transition-colors ${
                  page === 1 || isLoading || isFetching
                    ? 'bg-gray-100 text-gray-400 border-gray-200 cursor-not-allowed'
                    : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                }`}
              >
                Previous
              </button>
              <span className="text-sm text-gray-700">
                Page {page} of {totalPages}
              </span>
              <button
                onClick={() => setPage((prev) => Math.min(totalPages, prev + 1))}
                disabled={page >= totalPages || isLoading || isFetching}
                className={`px-3 py-1 text-sm rounded-md border transition-colors ${
                  page >= totalPages || isLoading || isFetching
                    ? 'bg-gray-100 text-gray-400 border-gray-200 cursor-not-allowed'
                    : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                }`}
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>

      {showProcessingModal && pendingEpisode && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={handleCancelProcessing}>
          <div
            className="bg-white rounded-xl shadow-2xl max-w-lg w-full p-6 space-y-4"
            onClick={(event) => event.stopPropagation()}
          >
            <h3 className="text-lg font-semibold text-gray-900">Enable episode</h3>
            <p className="text-sm text-gray-600">{pendingEpisode.title}</p>
            {isEstimating && (
              <div className="flex items-center gap-2 text-sm text-gray-500">
                <div className="w-4 h-4 border-2 border-gray-300 border-t-gray-600 rounded-full animate-spin" />
                Estimating processing time…
              </div>
            )}
            {!isEstimating && estimateError && (
              <p className="text-sm text-red-600">{estimateError}</p>
            )}
            {!isEstimating && processingEstimate && (
              <div className="bg-gray-50 rounded-lg p-4 text-sm text-gray-700 space-y-1">
                <p><strong>Estimated minutes:</strong> {processingEstimate.estimated_minutes.toFixed(2)}</p>
                {!processingEstimate.can_process && (
                  <p className="text-red-600 font-medium">Processing not available for this episode.</p>
                )}
              </div>
            )}
            <div className="flex justify-end gap-3">
              <button
                onClick={handleCancelProcessing}
                className="px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-800"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmProcessing}
                disabled={
                  whitelistMutation.isPending ||
                  isEstimating ||
                  !processingEstimate?.can_process
                }
                className={`px-4 py-2 rounded-lg text-sm font-medium ${
                  whitelistMutation.isPending || isEstimating || !processingEstimate?.can_process
                    ? 'bg-gray-200 text-gray-500 cursor-not-allowed'
                    : 'bg-blue-600 text-white hover:bg-blue-700'
                }`}
              >
                {whitelistMutation.isPending ? 'Starting…' : 'Confirm & process'}
              </button>
            </div>
          </div>
        </div>
      )}

      <FeedSettingsModal
        feed={currentFeed}
        isOpen={showSettingsModal}
        onClose={() => setShowSettingsModal(false)}
      />
    </div>
  );
}

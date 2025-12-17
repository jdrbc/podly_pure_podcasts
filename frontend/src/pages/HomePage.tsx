import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { feedsApi, configApi, billingApi } from '../services/api';
import FeedList from '../components/FeedList';
import FeedDetail from '../components/FeedDetail';
import AddFeedForm from '../components/AddFeedForm';
import type { Feed, ConfigResponse } from '../types';
import { toast } from 'react-hot-toast';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate } from 'react-router-dom';
import { copyToClipboard } from '../utils/clipboard';
import { emitDiagnosticError } from '../utils/diagnostics';
import { getHttpErrorInfo } from '../utils/httpError';

export default function HomePage() {
  const navigate = useNavigate();
  const [showAddForm, setShowAddForm] = useState(false);
  const [selectedFeed, setSelectedFeed] = useState<Feed | null>(null);
  const { requireAuth, user } = useAuth();

  const { data: feeds, isLoading, error, refetch } = useQuery({
    queryKey: ['feeds'],
    queryFn: feedsApi.getFeeds,
  });

  const { data: billingSummary, refetch: refetchBilling } = useQuery({
    queryKey: ['billing', 'summary'],
    queryFn: billingApi.getSummary,
    enabled: requireAuth && !!user,
  });

  useQuery<ConfigResponse>({
    queryKey: ['config'],
    queryFn: configApi.getConfig,
    enabled: !requireAuth || user?.role === 'admin',
  });
  const canRefreshAll = !requireAuth || user?.role === 'admin';
  const refreshAllMutation = useMutation({
    mutationFn: () => feedsApi.refreshAllFeeds(),
    onSuccess: (data) => {
      toast.success(
        `Refreshed ${data.feeds_refreshed} feeds and enqueued ${data.jobs_enqueued} jobs`
      );
      refetch();
    },
    onError: (err) => {
      console.error('Failed to refresh all feeds', err);
      const { status, data, message } = getHttpErrorInfo(err);
      emitDiagnosticError({
        title: 'Failed to refresh all feeds',
        message,
        kind: status ? 'http' : 'network',
        details: {
          status,
          response: data,
        },
      });
    },
  });

  const updateQuantityMutation = useMutation({
    mutationFn: (quantity: number) =>
      billingApi.setQuantity(quantity, {
        subscriptionId: billingSummary?.stripe_subscription_id ?? null,
      }),
    onSuccess: (res) => {
      const resRecord = res as unknown as Record<string, unknown>;
      const checkoutUrl = resRecord && typeof resRecord === 'object' ? resRecord.checkout_url : null;
      if (typeof checkoutUrl === 'string' && checkoutUrl.length > 0) {
        window.location.href = checkoutUrl;
        return;
      }
      toast.success('Plan updated');
      refetchBilling();
    },
    onError: (err) => {
      console.error('Failed to update billing quantity', err);
      const { status, data, message } = getHttpErrorInfo(err);
      emitDiagnosticError({
        title: 'Failed to update plan',
        message,
        kind: status ? 'http' : 'network',
        details: {
          status,
          response: data,
        },
      });
    },
  });

  useEffect(() => {
    if (!showAddForm || typeof document === 'undefined') {
      return;
    }

    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = originalOverflow;
    };
  }, [showAddForm]);

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

  const planLimitReached =
    !!billingSummary &&
    billingSummary.feeds_in_use >= billingSummary.feed_allowance &&
    user?.role !== 'admin';

  const handleChangePlan = () => {
    const current = billingSummary?.feed_allowance ?? 0;
    const input = window.prompt('How many feeds do you want in your plan?', String(current));
    if (input === null) return;
    const quantity = Number(input);
    if (Number.isNaN(quantity) || quantity < 0) {
      toast.error('Enter a valid non-negative number of feeds.');
      return;
    }
    updateQuantityMutation.mutate(quantity, {
      onSuccess: () => {},
    });
  };


  const handleCopyAggregateLink = async () => {
    try {
      const { url } = await feedsApi.getAggregateFeedLink();
      await copyToClipboard(url, 'Copy the Aggregate RSS URL:', 'Aggregate feed URL copied to clipboard!');
    } catch (err) {
      console.error('Failed to get aggregate link', err);
      toast.error('Failed to get aggregate feed link');
    }
  };

  return (
    <div className="h-full flex flex-col lg:flex-row gap-6">
      {/* Left Panel - Feed List (hidden on mobile when feed is selected) */}
      <div className={`flex-1 lg:max-w-md xl:max-w-lg flex flex-col ${
        selectedFeed ? 'hidden lg:flex' : 'flex'
      }`}>
        <div className="flex justify-between items-center mb-6 gap-3">
          <h2 className="text-2xl font-bold text-gray-900">Podcast Feeds</h2>
          <div className="flex items-center gap-2">
            {canRefreshAll && (
              <button
                onClick={() => refreshAllMutation.mutate()}
                disabled={refreshAllMutation.isPending}
                title="Refresh all feeds"
                className={`flex items-center justify-center px-3 py-2 rounded-md border transition-colors ${
                  refreshAllMutation.isPending
                    ? 'border-gray-200 text-gray-400 cursor-not-allowed'
                    : 'border-gray-200 text-gray-600 hover:bg-gray-100'
                }`}
              >
                <img
                  src="/reload-icon.svg"
                  alt="Refresh all"
                  className={`w-4 h-4 ${refreshAllMutation.isPending ? 'animate-spin' : ''}`}
                />
              </button>
            )}
            <button
              onClick={handleCopyAggregateLink}
              className="flex items-center justify-center px-3 py-2 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-100 transition-colors"
              title="Copy your aggregate feed URL (last 3 episodes from each feed)"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              </svg>
            </button>
            <button
              onClick={() => {
                if (planLimitReached) {
                  navigate('/billing');
                } else {
                  setShowAddForm((prev) => !prev);
                }
              }}
              className={`px-4 py-2 rounded-md font-medium transition-colors ${
                planLimitReached
                  ? 'bg-amber-600 hover:bg-amber-700 text-white'
                  : 'bg-blue-600 hover:bg-blue-700 text-white'
              }`}
              title={planLimitReached ? 'Your plan is full. Click to upgrade.' : undefined}
            >
              {planLimitReached ? 'Plan full' : showAddForm ? 'Close' : 'Add Feed'}
            </button>
          </div>
        </div>

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

      {showAddForm && (
        <div
          className="fixed inset-0 z-50 flex items-start sm:items-center justify-center bg-black/60 backdrop-blur-sm p-4 sm:p-6"
          onClick={() => setShowAddForm(false)}
        >
          <div
            className="w-full max-w-3xl bg-white rounded-2xl shadow-2xl border border-gray-200 flex flex-col max-h-[90vh]"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-gray-200 px-4 sm:px-6 py-4">
              <div>
                <h2 className="text-xl sm:text-2xl font-semibold text-gray-900">Add a Podcast Feed</h2>
                <p className="text-sm text-gray-500 mt-1">
                  Paste an RSS URL or search the catalog to find shows to follow.
                </p>
              </div>
              <button
                onClick={() => setShowAddForm(false)}
                className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100 transition-colors"
                aria-label="Close add feed modal"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="overflow-y-auto px-4 sm:px-6 py-4">
              <AddFeedForm
                onSuccess={() => {
                  setShowAddForm(false);
                  refetch();
                  refetchBilling();
                }}
                onUpgradePlan={handleChangePlan}
                planLimitReached={planLimitReached}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

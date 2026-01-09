import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { feedsApi } from '../services/api';
import type { Feed, FeedSettingsUpdate } from '../types';

interface FeedSettingsModalProps {
  feed: Feed;
  isOpen: boolean;
  onClose: () => void;
}

const DEFAULT_FILTER_STRINGS = 'sponsor,advertisement,ad break,promo,brought to you by';

export default function FeedSettingsModal({ feed, isOpen, onClose }: FeedSettingsModalProps) {
  const queryClient = useQueryClient();

  const [strategy, setStrategy] = useState<'llm' | 'chapter'>(
    feed.ad_detection_strategy || 'llm'
  );
  const [filterStrings, setFilterStrings] = useState(
    feed.chapter_filter_strings || DEFAULT_FILTER_STRINGS
  );

  const updateMutation = useMutation({
    mutationFn: (settings: FeedSettingsUpdate) =>
      feedsApi.updateFeedSettings(feed.id, settings),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['feeds'] });
      onClose();
    },
  });

  const handleSave = () => {
    const settings: FeedSettingsUpdate = {
      ad_detection_strategy: strategy,
    };

    if (strategy === 'chapter') {
      settings.chapter_filter_strings = filterStrings || null;
    } else {
      settings.chapter_filter_strings = null;
    }

    updateMutation.mutate(settings);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />

      <div className="relative w-full max-w-md bg-white rounded-xl border border-gray-200 shadow-lg overflow-hidden">
        <div className="flex items-start justify-between gap-4 px-5 py-4 border-b border-gray-200">
          <div>
            <h2 className="text-base font-semibold text-gray-900">Feed Settings</h2>
            <p className="text-sm text-gray-600 mt-1">
              Configure ad detection for "{feed.title}"
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Ad Detection Strategy
            </label>
            <select
              value={strategy}
              onChange={(e) => setStrategy(e.target.value as 'llm' | 'chapter')}
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
            >
              <option value="llm">LLM (AI-based)</option>
              <option value="chapter">Chapter-based</option>
            </select>
            <p className="text-xs text-gray-500 mt-1">
              {strategy === 'llm'
                ? 'Uses AI transcription and classification to detect ads'
                : 'Removes chapters matching filter strings (requires chapter metadata)'}
            </p>
          </div>

          {strategy === 'chapter' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Filter Strings
              </label>
              <textarea
                value={filterStrings}
                onChange={(e) => setFilterStrings(e.target.value)}
                placeholder="sponsor,advertisement,ad break"
                rows={3}
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
              />
              <p className="text-xs text-gray-500 mt-1">
                Comma-separated list of strings. Chapters with titles containing any of these will be removed (case-insensitive).
              </p>
            </div>
          )}

          {updateMutation.isError && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-red-700">
                Failed to save settings. Please try again.
              </p>
            </div>
          )}
        </div>

        <div className="flex justify-end gap-3 px-5 py-4 border-t border-gray-200 bg-gray-50">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={updateMutation.isPending}
            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {updateMutation.isPending ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}

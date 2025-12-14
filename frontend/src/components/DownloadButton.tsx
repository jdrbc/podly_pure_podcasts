import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import axios from 'axios';
import { feedsApi } from '../services/api';
import ReprocessButton from './ReprocessButton';
import { configApi } from '../services/api';
import { toast } from 'react-hot-toast';
import { useEpisodeStatus } from '../hooks/useEpisodeStatus';

interface DownloadButtonProps {
  episodeGuid: string;
  isWhitelisted: boolean;
  hasProcessedAudio: boolean;
  feedId?: number;
  canModifyEpisodes?: boolean;
  className?: string;
}

export default function DownloadButton({
  episodeGuid,
  isWhitelisted,
  hasProcessedAudio,
  feedId,
  canModifyEpisodes = true,
  className = ''
}: DownloadButtonProps) {
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  
  const { data: status } = useEpisodeStatus(episodeGuid, isWhitelisted, hasProcessedAudio, feedId);
  
  const isProcessing = status?.status === 'pending' || status?.status === 'running' || status?.status === 'starting';
  const isCompleted = hasProcessedAudio || status?.status === 'completed';
  const downloadUrl = status?.download_url || (hasProcessedAudio ? `/api/posts/${episodeGuid}/download` : undefined);

  const handleDownloadClick = async () => {
    if (!isWhitelisted) {
      setError('Post must be whitelisted before processing');
      return;
    }

    // Guard when LLM API key is not configured - use fresh server check
    try {
      const { configured } = await configApi.isConfigured();
      if (!configured) {
        toast.error('Add an API key in Config before processing.');
        return;
      }
    } catch (err) {
      if (!(axios.isAxiosError(err) && err.response?.status === 403)) {
        toast.error('Unable to verify configuration. Please try again.');
        return;
      }
    }

    if (isCompleted && downloadUrl) {
      // Already processed, download directly
      try {
        await feedsApi.downloadPost(episodeGuid);
      } catch (err) {
        console.error('Error downloading file:', err);
        setError('Failed to download file');
      }
      return;
    }

    try {
      setError(null);
      // Optimistically update status to show processing state immediately
      queryClient.setQueryData(['episode-status', episodeGuid], {
        status: 'starting',
        step: 0,
        step_name: 'Starting',
        total_steps: 4,
        message: 'Requesting processing...'
      });

      const response = await feedsApi.processPost(episodeGuid);
      
      // Invalidate to trigger polling in the hook
      queryClient.invalidateQueries({ queryKey: ['episode-status', episodeGuid] });

      if (response.status === 'not_started') {
          setError('No processing job found');
      }
    } catch (err: unknown) {
      console.error('Error starting processing:', err);
      const errorMessage = err && typeof err === 'object' && 'response' in err
        ? (err as { response?: { data?: { error?: string; message?: string } } }).response?.data?.message 
          || (err as { response?: { data?: { error?: string } } }).response?.data?.error 
          || 'Failed to start processing'
        : 'Failed to start processing';
      setError(errorMessage);
      // Invalidate to clear optimistic update if failed
      queryClient.invalidateQueries({ queryKey: ['episode-status', episodeGuid] });
    }
  };

  // Show completed state with download button only
  if (isCompleted && downloadUrl) {
    return (
      <div className={`${className}`}>
        <div className="flex gap-2">
          <button
            onClick={handleDownloadClick}
            className="px-3 py-1 text-xs rounded font-medium transition-colors bg-blue-600 text-white hover:bg-blue-700"
            title="Download processed episode"
          >
            Download
          </button>
          <ReprocessButton
            episodeGuid={episodeGuid}
            isWhitelisted={isWhitelisted}
            feedId={feedId}
            canModifyEpisodes={canModifyEpisodes}
            onReprocessStart={() => {
              queryClient.invalidateQueries({ queryKey: ['episode-status', episodeGuid] });
            }}
          />
        </div>
        {error && (
          <div className="text-xs text-red-600 mt-1">
            {error}
          </div>
        )}
      </div>
    );
  }

  // If user can't modify episodes, don't show the Process button
  if (!canModifyEpisodes) {
    return null;
  }

  // If processing, hide the button (EpisodeProcessingStatus will show progress)
  if (isProcessing) {
    return null;
  }

  return (
    <div className={`space-y-2 ${className}`}>
      <button
        onClick={handleDownloadClick}
        className="px-3 py-1 text-xs rounded font-medium transition-colors border bg-white text-gray-700 border-gray-300 hover:bg-gray-50 hover:border-gray-400 hover:text-gray-900"
        title="Start processing episode"
      >
        Process
      </button>

      {/* Error message */}
      {error && (
        <div className="text-xs text-red-600 text-center">
          {error}
        </div>
      )}
    </div>
  );
}

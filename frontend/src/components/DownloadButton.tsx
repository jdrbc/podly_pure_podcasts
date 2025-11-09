import { useState, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import axios from 'axios';
import { feedsApi } from '../services/api';
import ReprocessButton from './ReprocessButton';
import { configApi } from '../services/api';
import { toast } from 'react-hot-toast';

interface DownloadButtonProps {
  episodeGuid: string;
  isWhitelisted: boolean;
  hasProcessedAudio: boolean;
  feedId?: number;
  className?: string;
}

interface ProcessingStatus {
  status: string;
  step: number;
  step_name: string;
  total_steps: number;
  message: string;
  download_url?: string;
  error?: string;
}

export default function DownloadButton({
  episodeGuid,
  isWhitelisted,
  hasProcessedAudio,
  feedId,
  className = ''
}: DownloadButtonProps) {
  const [isProcessing, setIsProcessing] = useState(false);
  const [status, setStatus] = useState<ProcessingStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  // Check initial status when component mounts
  useEffect(() => {
    if (hasProcessedAudio) {
      setStatus({
        status: 'completed',
        step: 4,
        step_name: 'Completed',
        total_steps: 4,
        message: 'Episode ready for download',
        download_url: `/api/posts/${episodeGuid}/download`
      });
    }
  }, [hasProcessedAudio, episodeGuid]);

  // Check for existing processing jobs on component mount
  useEffect(() => {
    const checkInitialStatus = async () => {
      // Only check if not already processed and is whitelisted
      if (!hasProcessedAudio && isWhitelisted) {
        try {
          const statusResponse = await feedsApi.getPostStatus(episodeGuid);

          // If there's an active job, set the processing state
          if (statusResponse.status === 'pending' || statusResponse.status === 'running') {
            setIsProcessing(true);
            setStatus(statusResponse);
          } else if (statusResponse.status === 'failed' || statusResponse.status === 'cancelled') {
            // Show any error from a failed job
            setStatus(statusResponse);
            if (statusResponse.error) {
              setError(statusResponse.error);
            }
          } else if (statusResponse.status === 'skipped' || statusResponse.status === 'completed') {
            setStatus(statusResponse);
          }
          // If status is 'not_started', leave the button in its default state
        } catch (err) {
          console.error('Error checking initial processing status:', err);
          // Don't set error state for API failures during initialization
        }
      }
    };

    checkInitialStatus();
  }, [episodeGuid, hasProcessedAudio, isWhitelisted]);

  // Poll for status updates when processing
  useEffect(() => {
    let interval: number;

    if (isProcessing) {
      interval = window.setInterval(async () => {
        try {
          const statusResponse = await feedsApi.getPostStatus(episodeGuid);
          setStatus(statusResponse);

          if (['completed', 'skipped', 'error', 'not_started'].includes(statusResponse.status)) {
            setIsProcessing(false);
            if (statusResponse.status === 'error') {
              setError(statusResponse.error || 'Processing failed');
            } else if (statusResponse.status === 'not_started') {
              setError('No processing job found');
            } else if ((statusResponse.status === 'completed' || statusResponse.status === 'skipped') && feedId) {
              // Invalidate the episodes query to refresh the parent component's data
              queryClient.invalidateQueries({ queryKey: ['episodes', feedId] });
            }
          }
        } catch (err) {
          console.error('Error checking status:', err);
          setError('Failed to check processing status');
          setIsProcessing(false);
        }
      }, 2000); // Poll every 2 seconds
    }

    return () => {
      if (interval) {
        clearInterval(interval);
      }
    };
  }, [isProcessing, episodeGuid, feedId, queryClient]);

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

    if (status?.download_url) {
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

      const response = await feedsApi.processPost(episodeGuid);

      if ((response.status === 'completed' || response.status === 'skipped') && response.download_url) {
        // Already processed
        setStatus({
          status: response.status,
          step: 4,
          step_name: response.status === 'skipped' ? 'Processing skipped' : 'Completed',
          total_steps: 4,
          message: 'Episode ready for download',
          download_url: response.download_url
        });

        // Trigger download
        try {
          await feedsApi.downloadPost(episodeGuid);
        } catch (err) {
          console.error('Error downloading file:', err);
          setError('Failed to download file');
        }
      } else if (response.status === 'started') {
        // Processing started, begin polling
        setIsProcessing(true);
        setStatus({
          status: 'processing',
          step: 1,
          step_name: 'Starting',
          total_steps: 4,
          message: 'Processing started...'
        });
      } else {
        // If we get any other status (like not_started), show error
        if (response.status === 'not_started') {
          setError('No processing job found');
        }
      }
    } catch (err: unknown) {
      console.error('Error starting processing:', err);
      const errorMessage = err && typeof err === 'object' && 'response' in err
        ? (err as { response?: { data?: { error?: string } } }).response?.data?.error || 'Failed to start processing'
        : 'Failed to start processing';
      setError(errorMessage);
    }
  };

  const getProgressPercentage = () => {
    if (!status) return 0;
    return (status.step / status.total_steps) * 100;
  };

  const getStepIcon = (stepNumber: number) => {
    if (!status) return '○';

    if (status.step > stepNumber) {
      return '✓'; // Completed
    } else if (status.step === stepNumber) {
      return '●'; // Current
    } else {
      return '○'; // Not started
    }
  };

  // Show completed state with download button only
  if (status?.status === 'completed' && status.download_url) {
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
            onReprocessStart={() => {
              // Reset status to trigger re-processing UI
              setStatus(null);
              setIsProcessing(true);
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

  return (
    <div className={`space-y-2 ${className}`}>
      <button
        onClick={handleDownloadClick}
        disabled={isProcessing}
        className={`px-3 py-1 text-xs rounded font-medium transition-colors border ${
          isProcessing
            ? 'bg-gray-500 text-white cursor-wait border-gray-500'
            : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50 hover:border-gray-400 hover:text-gray-900'
        }`}
        title={
          isProcessing
            ? 'Processing in progress...'
            : 'Start processing episode'
        }
      >
        {isProcessing ? (
          'Processing...'
        ) : (
          'Process'
        )}
      </button>

      {/* Progress indicator - only show while processing */}
      {isProcessing && status && (
        <div className="space-y-1">
          {/* Progress bar */}
          <div className="w-full bg-gray-200 rounded-full h-1.5">
            <div
              className={`h-1.5 rounded-full transition-all duration-300 ${
                status?.status === 'error' ? 'bg-red-500' : 'bg-blue-500'
              }`}
              style={{ width: `${getProgressPercentage()}%` }}
            />
          </div>

          {/* Step indicators */}
          <div className="flex justify-between text-xs text-gray-600">
            {[1, 2, 3, 4].map((stepNumber) => (
              <div
                key={stepNumber}
                className={`flex flex-col items-center ${
                  status?.step === stepNumber ? 'text-blue-600 font-medium' : ''
                } ${
                  status && status.step > stepNumber ? 'text-green-600' : ''
                }`}
              >
                <span className="text-xs">{getStepIcon(stepNumber)}</span>
                <span className="text-xs">{stepNumber}/4</span>
              </div>
            ))}
          </div>

          {/* Current step name */}
          {status && (
            <div className="text-xs text-center text-gray-600">
              {status.step_name}
            </div>
          )}
        </div>
      )}

      {/* Error message */}
      {error && (
        <div className="text-xs text-red-600 text-center">
          {error}
        </div>
      )}
    </div>
  );
}

import { useState, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { feedsApi } from '../services/api';

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

  // Poll for status updates when processing
  useEffect(() => {
    let interval: number;
    
    if (isProcessing) {
      interval = window.setInterval(async () => {
        try {
          const statusResponse = await feedsApi.getPostStatus(episodeGuid);
          setStatus(statusResponse);
          
          if (statusResponse.status === 'completed' || statusResponse.status === 'error' || statusResponse.status === 'not_started') {
            setIsProcessing(false);
            if (statusResponse.status === 'error') {
              setError(statusResponse.error || 'Processing failed');
            } else if (statusResponse.status === 'not_started') {
              setError('No processing job found');
            } else if (statusResponse.status === 'completed' && feedId) {
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
      
      if (response.status === 'completed' && response.download_url) {
        // Already processed
        setStatus({
          status: 'completed',
          step: 4,
          step_name: 'Completed',
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

  if (!isWhitelisted) {
    return (
      <button
        disabled
        className={`px-3 py-1 text-xs bg-gray-100 text-gray-500 rounded cursor-not-allowed ${className}`}
        title="Post must be whitelisted to download"
      >
        Not Whitelisted
      </button>
    );
  }

  // Show completed state with download button only
  if (status?.status === 'completed' && status.download_url) {
    return (
      <div className={`${className}`}>
        <button
          onClick={handleDownloadClick}
          className="px-3 py-1 text-xs rounded font-medium transition-colors bg-blue-600 text-white hover:bg-blue-700"
          title="Download processed episode"
        >
          ⬇ Download
        </button>
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
        className={`px-3 py-1 text-xs rounded font-medium transition-colors ${
          isProcessing
            ? 'bg-blue-600 text-white cursor-wait'
            : 'bg-blue-600 text-white hover:bg-blue-700'
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
          '🎵 Process'
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
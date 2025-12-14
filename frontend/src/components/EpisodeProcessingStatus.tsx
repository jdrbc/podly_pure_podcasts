import { useEpisodeStatus } from '../hooks/useEpisodeStatus';

interface EpisodeProcessingStatusProps {
  episodeGuid: string;
  isWhitelisted: boolean;
  hasProcessedAudio: boolean;
  feedId?: number;
  className?: string;
}

export default function EpisodeProcessingStatus({
  episodeGuid,
  isWhitelisted,
  hasProcessedAudio,
  feedId,
  className = ''
}: EpisodeProcessingStatusProps) {
  const { data: status } = useEpisodeStatus(episodeGuid, isWhitelisted, hasProcessedAudio, feedId);

  if (!status) return null;

  // Don't show anything if completed (DownloadButton handles this) or not started
  if (status.status === 'completed' || status.status === 'not_started') {
    return null;
  }

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

  return (
    <div className={`space-y-2 min-w-[200px] ${className}`}>
      {/* Progress indicator */}
      <div className="space-y-1">
        {/* Progress bar */}
        <div className="w-full bg-gray-200 rounded-full h-1.5">
          <div
            className={`h-1.5 rounded-full transition-all duration-300 ${
              status.status === 'error' || status.status === 'failed' ? 'bg-red-500' : 'bg-blue-500'
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
                status.step === stepNumber ? 'text-blue-600 font-medium' : ''
              } ${
                status.step > stepNumber ? 'text-green-600' : ''
              }`}
            >
              <span className="text-xs">{getStepIcon(stepNumber)}</span>
              <span className="text-xs">{stepNumber}/4</span>
            </div>
          ))}
        </div>

        {/* Current step name */}
        <div className="text-xs text-center text-gray-600">
          {status.step_name}
        </div>
      </div>

      {/* Error message */}
      {(status.error || status.status === 'failed' || status.status === 'error') && (
        <div className="text-xs text-red-600 text-center">
          {status.error || 'Processing failed'}
        </div>
      )}
    </div>
  );
}

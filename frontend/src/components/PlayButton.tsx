import { useAudioPlayer } from '../contexts/AudioPlayerContext';
import type { Episode } from '../types';

interface PlayButtonProps {
  episode: Episode;
  className?: string;
}

const PlayIcon = ({ className }: { className: string }) => (
  <svg className={className} fill="currentColor" viewBox="0 0 24 24">
    <path d="M8 5v14l11-7z"/>
  </svg>
);

const PauseIcon = ({ className }: { className: string }) => (
  <svg className={className} fill="currentColor" viewBox="0 0 24 24">
    <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/>
  </svg>
);

export default function PlayButton({ episode, className = '' }: PlayButtonProps) {
  const { currentEpisode, isPlaying, isLoading, playEpisode, togglePlayPause } = useAudioPlayer();
  
  const isCurrentEpisode = currentEpisode?.id === episode.id;
  const canPlay = episode.has_processed_audio;

  console.log(`PlayButton for "${episode.title}":`, {
    has_processed_audio: episode.has_processed_audio,
    whitelisted: episode.whitelisted,
    canPlay
  });

  const getDisabledReason = () => {
    if (!episode.has_processed_audio) {
      return 'Episode not processed yet';
    }
    return '';
  };

  const handleClick = () => {
    console.log('PlayButton clicked for episode:', episode.title);
    console.log('canPlay:', canPlay);
    console.log('isCurrentEpisode:', isCurrentEpisode);
    
    if (!canPlay) return;
    
    if (isCurrentEpisode) {
      console.log('Toggling play/pause for current episode');
      togglePlayPause();
    } else {
      console.log('Playing new episode');
      playEpisode(episode);
    }
  };

  const isDisabled = !canPlay || (isLoading && isCurrentEpisode);
  const disabledReason = getDisabledReason();
  const title = isDisabled && disabledReason 
    ? disabledReason 
    : isCurrentEpisode 
      ? (isPlaying ? 'Pause' : 'Play') 
      : 'Play episode';

  return (
    <button
      onClick={handleClick}
      disabled={isDisabled}
      className={`p-2 rounded-full transition-colors ${
        isDisabled 
          ? 'bg-gray-300 text-gray-500 cursor-not-allowed' 
          : 'bg-blue-600 text-white hover:bg-blue-700'
      } ${className}`}
      title={title}
    >
      {isLoading && isCurrentEpisode ? (
        <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
      ) : isCurrentEpisode && isPlaying ? (
        <PauseIcon className="w-4 h-4" />
      ) : (
        <PlayIcon className="w-4 h-4" />
      )}
    </button>
  );
} 
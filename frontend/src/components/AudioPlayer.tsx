import React, { useState, useRef, useEffect } from 'react';
import { useAudioPlayer } from '../contexts/AudioPlayerContext';

// Simple SVG icons to replace Heroicons
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

const SpeakerWaveIcon = ({ className }: { className: string }) => (
  <svg className={className} fill="currentColor" viewBox="0 0 24 24">
    <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>
  </svg>
);

const SpeakerXMarkIcon = ({ className }: { className: string }) => (
  <svg className={className} fill="currentColor" viewBox="0 0 24 24">
    <path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z"/>
  </svg>
);

const XMarkIcon = ({ className }: { className: string }) => (
  <svg className={className} fill="currentColor" viewBox="0 0 24 24">
    <path d="M6 18L18 6M6 6l12 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
  </svg>
);

export default function AudioPlayer() {
  const {
    currentEpisode,
    isPlaying,
    currentTime,
    duration,
    volume,
    isLoading,
    error,
    togglePlayPause,
    seekTo,
    setVolume
  } = useAudioPlayer();

  const [isDragging, setIsDragging] = useState(false);
  const [dragTime, setDragTime] = useState(0);
  const [showVolumeSlider, setShowVolumeSlider] = useState(false);
  const [showKeyboardShortcuts, setShowKeyboardShortcuts] = useState(false);
  const [dismissedError, setDismissedError] = useState<string | null>(null);
  const progressBarRef = useRef<HTMLDivElement>(null);
  const volumeSliderRef = useRef<HTMLDivElement>(null);

  // Reset dismissed error when a new error occurs
  useEffect(() => {
    if (error && error !== dismissedError) {
      setDismissedError(null);
    }
  }, [error, dismissedError]);

  // Close volume slider when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (volumeSliderRef.current && !volumeSliderRef.current.contains(event.target as Node)) {
        setShowVolumeSlider(false);
      }
    };

    if (showVolumeSlider) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [showVolumeSlider]);

  // Don't render if no episode is loaded
  if (!currentEpisode) {
    return null;
  }

  console.log('AudioPlayer rendering with:', {
    currentEpisode: currentEpisode?.title,
    isPlaying,
    isLoading,
    error,
    duration
  });

  const formatTime = (seconds: number) => {
    if (isNaN(seconds)) return '0:00';
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainingSeconds = Math.floor(seconds % 60);
    
    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
    }
    return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
  };

  const handleProgressClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!progressBarRef.current || !duration) return;
    
    const rect = progressBarRef.current.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const newTime = (clickX / rect.width) * duration;
    seekTo(newTime);
  };

  const handleProgressMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    setIsDragging(true);
    handleProgressClick(e);
  };

  const handleProgressMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!isDragging || !progressBarRef.current || !duration) return;
    
    const rect = progressBarRef.current.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const newTime = Math.max(0, Math.min((clickX / rect.width) * duration, duration));
    setDragTime(newTime);
  };

  const handleProgressMouseUp = () => {
    if (isDragging) {
      seekTo(dragTime);
      setIsDragging(false);
    }
  };

  const handleVolumeChange = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!volumeSliderRef.current) return;
    
    const rect = volumeSliderRef.current.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const newVolume = Math.max(0, Math.min(clickX / rect.width, 1));
    setVolume(newVolume);
  };

  const toggleMute = () => {
    setVolume(volume > 0 ? 0 : 1);
  };

  const dismissError = () => {
    setDismissedError(error);
  };

  const displayTime = isDragging ? dragTime : currentTime;
  const progressPercentage = duration > 0 ? (displayTime / duration) * 100 : 0;
  const shouldShowError = error && error !== dismissedError;

  return (
    <div className="fixed bottom-0 left-0 right-0 bg-white border-t border-gray-200 shadow-lg z-50">
      <div className="max-w-7xl mx-auto px-4 py-3">
        {shouldShowError && (
          <div className="mb-2 p-2 bg-red-100 border border-red-300 rounded text-red-700 text-sm flex items-center justify-between">
            <span>{error}</span>
            <button
              onClick={dismissError}
              className="ml-2 p-1 hover:bg-red-200 rounded transition-colors"
              aria-label="Dismiss error"
            >
              <XMarkIcon className="w-4 h-4" />
            </button>
          </div>
        )}
        
        <div className="flex items-center space-x-4">
          {/* Episode Info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center space-x-3">
              <div className="w-12 h-12 bg-gray-200 rounded flex-shrink-0 flex items-center justify-center">
                <span className="text-gray-500 text-xs">🎵</span>
              </div>
              <div className="min-w-0 flex-1">
                <h4 className="text-sm font-medium text-gray-900 truncate">
                  {currentEpisode.title}
                </h4>
                <p className="text-xs text-gray-500 truncate">
                  Episode • {formatTime(duration)}
                </p>
              </div>
            </div>
          </div>

          {/* Player Controls */}
          <div className="flex-1 max-w-2xl">
            {/* Control Buttons */}
            <div 
              className="flex items-center justify-center space-x-4 mb-2 relative"
              onMouseEnter={() => setShowKeyboardShortcuts(true)}
              onMouseLeave={() => setShowKeyboardShortcuts(false)}
            >
              <button
                onClick={togglePlayPause}
                disabled={isLoading}
                className="p-2 bg-gray-900 text-white rounded-full hover:bg-gray-800 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isLoading ? (
                  <div className="w-6 h-6 border-2 border-white border-t-transparent rounded-full animate-spin" />
                ) : isPlaying ? (
                  <PauseIcon className="w-6 h-6" />
                ) : (
                  <PlayIcon className="w-6 h-6" />
                )}
              </button>
              
              {/* Keyboard Shortcuts Tooltip */}
              {showKeyboardShortcuts && (
                <div className="absolute bottom-full mb-2 left-1/2 transform -translate-x-1/2 bg-gray-900 text-white text-xs rounded py-2 px-3 whitespace-nowrap z-10">
                  <div className="space-y-1">
                    <div>Space: Play/Pause</div>
                    <div>← →: Seek ±10s</div>
                    <div>↑ ↓: Volume ±10%</div>
                  </div>
                  <div className="absolute top-full left-1/2 transform -translate-x-1/2 border-4 border-transparent border-t-gray-900"></div>
                </div>
              )}
            </div>

            {/* Progress Bar */}
            <div className="flex items-center space-x-2 text-xs text-gray-500">
              <span className="w-10 text-right">{formatTime(displayTime)}</span>
              <div
                ref={progressBarRef}
                className="flex-1 h-1 bg-gray-200 rounded-full cursor-pointer relative group audio-player-progress"
                onMouseDown={handleProgressMouseDown}
                onMouseMove={handleProgressMouseMove}
                onMouseUp={handleProgressMouseUp}
                onMouseLeave={handleProgressMouseUp}
                onClick={handleProgressClick}
              >
                <div
                  className="h-full bg-gray-900 rounded-full relative"
                  style={{ width: `${progressPercentage}%` }}
                >
                  <div className="absolute right-0 top-1/2 transform -translate-y-1/2 w-3 h-3 bg-gray-900 rounded-full audio-player-progress-thumb" />
                </div>
              </div>
              <span className="w-10">{formatTime(duration)}</span>
            </div>
          </div>

          {/* Volume Control */}
          <div className="flex items-center space-x-2 relative">
            <button
              onClick={toggleMute}
              onMouseEnter={() => setShowVolumeSlider(true)}
              className="p-1 text-gray-600 hover:text-gray-900 transition-colors"
            >
              {volume === 0 ? (
                <SpeakerXMarkIcon className="w-5 h-5" />
              ) : (
                <SpeakerWaveIcon className="w-5 h-5" />
              )}
            </button>
            
            {showVolumeSlider && (
              <div
                ref={volumeSliderRef}
                className="absolute bottom-full right-0 mb-2 p-2 bg-white border border-gray-200 rounded shadow-lg audio-player-volume-slider"
                onMouseEnter={() => setShowVolumeSlider(true)}
              >
                <div
                  className="w-20 h-1 bg-gray-200 rounded-full cursor-pointer relative group"
                  onClick={handleVolumeChange}
                >
                  <div
                    className="h-full bg-gray-900 rounded-full relative"
                    style={{ width: `${volume * 100}%` }}
                  >
                    <div className="absolute right-0 top-1/2 transform -translate-y-1/2 w-3 h-3 bg-gray-900 rounded-full opacity-0 group-hover:opacity-100 transition-opacity" />
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
} 
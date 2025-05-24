import React, { createContext, useContext, useReducer, useRef, useEffect, useCallback } from 'react';
import type { Episode } from '../types';
import { feedsApi } from '../services/api';

interface AudioPlayerState {
  currentEpisode: Episode | null;
  isPlaying: boolean;
  currentTime: number;
  duration: number;
  volume: number;
  isLoading: boolean;
  error: string | null;
}

interface AudioPlayerContextType extends AudioPlayerState {
  playEpisode: (episode: Episode) => void;
  togglePlayPause: () => void;
  seekTo: (time: number) => void;
  setVolume: (volume: number) => void;
  audioRef: React.RefObject<HTMLAudioElement | null>;
}

type AudioPlayerAction =
  | { type: 'SET_EPISODE'; payload: Episode }
  | { type: 'SET_PLAYING'; payload: boolean }
  | { type: 'SET_CURRENT_TIME'; payload: number }
  | { type: 'SET_DURATION'; payload: number }
  | { type: 'SET_VOLUME'; payload: number }
  | { type: 'SET_LOADING'; payload: boolean }
  | { type: 'SET_ERROR'; payload: string | null };

const initialState: AudioPlayerState = {
  currentEpisode: null,
  isPlaying: false,
  currentTime: 0,
  duration: 0,
  volume: 1,
  isLoading: false,
  error: null,
};

function audioPlayerReducer(state: AudioPlayerState, action: AudioPlayerAction): AudioPlayerState {
  switch (action.type) {
    case 'SET_EPISODE':
      return { ...state, currentEpisode: action.payload, currentTime: 0, error: null };
    case 'SET_PLAYING':
      return { ...state, isPlaying: action.payload };
    case 'SET_CURRENT_TIME':
      return { ...state, currentTime: action.payload };
    case 'SET_DURATION':
      return { ...state, duration: action.payload };
    case 'SET_VOLUME':
      return { ...state, volume: action.payload };
    case 'SET_LOADING':
      return { ...state, isLoading: action.payload };
    case 'SET_ERROR':
      return { ...state, error: action.payload, isLoading: false };
    default:
      return state;
  }
}

const AudioPlayerContext = createContext<AudioPlayerContextType | undefined>(undefined);

export function AudioPlayerProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(audioPlayerReducer, initialState);
  const audioRef = useRef<HTMLAudioElement>(null);

  const playEpisode = (episode: Episode) => {
    console.log('playEpisode called with:', episode);
    console.log('Episode audio flags:', {
      has_processed_audio: episode.has_processed_audio,
      has_unprocessed_audio: episode.has_unprocessed_audio,
      download_url: episode.download_url
    });

    if (!episode.has_processed_audio) {
      console.log('No processed audio available for episode');
      dispatch({ type: 'SET_ERROR', payload: 'Post needs to be processed first' });
      return;
    }

    console.log('Setting episode and loading state');
    dispatch({ type: 'SET_EPISODE', payload: episode });
    dispatch({ type: 'SET_LOADING', payload: true });
    
    if (audioRef.current) {
      // Use the new API endpoint for audio
      const audioUrl = feedsApi.getPostAudioUrl(episode.guid);
      console.log('Using API audio URL:', audioUrl);
      
      audioRef.current.src = audioUrl;
      audioRef.current.load();
    } else {
      console.log('audioRef.current is null');
    }
  };

  const togglePlayPause = useCallback(() => {
    if (!audioRef.current || !state.currentEpisode) return;

    if (state.isPlaying) {
      audioRef.current.pause();
    } else {
      audioRef.current.play().catch((error) => {
        dispatch({ type: 'SET_ERROR', payload: 'Failed to play audio' });
        console.error('Audio play error:', error);
      });
    }
  }, [state.isPlaying, state.currentEpisode]);

  const seekTo = useCallback((time: number) => {
    if (audioRef.current) {
      audioRef.current.currentTime = time;
      dispatch({ type: 'SET_CURRENT_TIME', payload: time });
    }
  }, []);

  const setVolume = useCallback((volume: number) => {
    if (audioRef.current) {
      audioRef.current.volume = volume;
      dispatch({ type: 'SET_VOLUME', payload: volume });
    }
  }, []);

  // Audio event handlers
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const handleLoadedData = () => {
      dispatch({ type: 'SET_DURATION', payload: audio.duration });
      dispatch({ type: 'SET_LOADING', payload: false });
    };

    const handleTimeUpdate = () => {
      dispatch({ type: 'SET_CURRENT_TIME', payload: audio.currentTime });
    };

    const handlePlay = () => {
      dispatch({ type: 'SET_PLAYING', payload: true });
    };

    const handlePause = () => {
      dispatch({ type: 'SET_PLAYING', payload: false });
    };

    const handleEnded = () => {
      dispatch({ type: 'SET_PLAYING', payload: false });
      dispatch({ type: 'SET_CURRENT_TIME', payload: 0 });
    };

    const handleError = () => {
      const audio = audioRef.current;
      if (!audio) return;

      // Get more specific error information
      let errorMessage = 'Failed to load audio';
      
      if (audio.error) {
        switch (audio.error.code) {
          case MediaError.MEDIA_ERR_ABORTED:
            errorMessage = 'Audio loading was aborted';
            break;
          case MediaError.MEDIA_ERR_NETWORK:
            errorMessage = 'Network error while loading audio';
            break;
          case MediaError.MEDIA_ERR_DECODE:
            errorMessage = 'Audio file is corrupted or unsupported';
            break;
          case MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED:
            errorMessage = 'Audio format not supported or file not found';
            break;
          default:
            errorMessage = 'Unknown audio error';
        }
      }

      // Check if it's a network error that might indicate specific HTTP status
      if (audio.error?.code === MediaError.MEDIA_ERR_NETWORK || 
          audio.error?.code === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED) {
        // For network errors, provide more helpful messages
        if (state.currentEpisode) {
          if (!state.currentEpisode.has_processed_audio) {
            errorMessage = 'Post needs to be processed first';
          } else if (!state.currentEpisode.whitelisted) {
            errorMessage = 'Post is not whitelisted';
          } else {
            errorMessage = 'Audio file not available - try processing the post again';
          }
        }
      }

      console.error('Audio error:', audio.error, 'Message:', errorMessage);
      dispatch({ type: 'SET_ERROR', payload: errorMessage });
    };

    const handleCanPlay = () => {
      dispatch({ type: 'SET_LOADING', payload: false });
    };

    audio.addEventListener('loadeddata', handleLoadedData);
    audio.addEventListener('timeupdate', handleTimeUpdate);
    audio.addEventListener('play', handlePlay);
    audio.addEventListener('pause', handlePause);
    audio.addEventListener('ended', handleEnded);
    audio.addEventListener('error', handleError);
    audio.addEventListener('canplay', handleCanPlay);

    return () => {
      audio.removeEventListener('loadeddata', handleLoadedData);
      audio.removeEventListener('timeupdate', handleTimeUpdate);
      audio.removeEventListener('play', handlePlay);
      audio.removeEventListener('pause', handlePause);
      audio.removeEventListener('ended', handleEnded);
      audio.removeEventListener('error', handleError);
      audio.removeEventListener('canplay', handleCanPlay);
    };
  }, []);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      // Only handle shortcuts when there's a current episode and not typing in an input
      if (!state.currentEpisode || 
          event.target instanceof HTMLInputElement || 
          event.target instanceof HTMLTextAreaElement) {
        return;
      }

      switch (event.code) {
        case 'Space':
          event.preventDefault();
          togglePlayPause();
          break;
        case 'ArrowLeft':
          event.preventDefault();
          seekTo(Math.max(0, state.currentTime - 10)); // Seek back 10 seconds
          break;
        case 'ArrowRight':
          event.preventDefault();
          seekTo(Math.min(state.duration, state.currentTime + 10)); // Seek forward 10 seconds
          break;
        case 'ArrowUp':
          event.preventDefault();
          setVolume(Math.min(1, state.volume + 0.1)); // Volume up
          break;
        case 'ArrowDown':
          event.preventDefault();
          setVolume(Math.max(0, state.volume - 0.1)); // Volume down
          break;
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [state.currentEpisode, state.currentTime, state.duration, state.volume, togglePlayPause, seekTo, setVolume]);

  const contextValue: AudioPlayerContextType = {
    ...state,
    playEpisode,
    togglePlayPause,
    seekTo,
    setVolume,
    audioRef,
  };

  return (
    <AudioPlayerContext.Provider value={contextValue}>
      {children}
      <audio ref={audioRef} preload="metadata" />
    </AudioPlayerContext.Provider>
  );
}

export function useAudioPlayer() {
  const context = useContext(AudioPlayerContext);
  if (context === undefined) {
    throw new Error('useAudioPlayer must be used within an AudioPlayerProvider');
  }
  return context;
} 
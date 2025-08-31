import axios from 'axios';
import type { Feed, Episode } from '../types';

// Type for runtime configuration
interface AppConfig {
  API_BASE_URL: string;
}

// Extend window interface to include our app config
declare global {
  interface Window {
    __APP_CONFIG__?: AppConfig;
  }
}

// Get API URL from runtime config or fall back to environment variable
const getApiBaseUrl = (): string => {
  // Check if runtime config exists and has been properly replaced (not a placeholder)
  if (typeof window !== 'undefined' && 
      window.__APP_CONFIG__ && 
      window.__APP_CONFIG__.API_BASE_URL && 
      !window.__APP_CONFIG__.API_BASE_URL.includes('PLACEHOLDER')) {
    return window.__APP_CONFIG__.API_BASE_URL;
  }

  // Fall back to Vite environment variable (development or when runtime config is placeholder)
  return import.meta.env.VITE_API_URL || 'http://localhost:5002';
};

const API_BASE_URL = getApiBaseUrl();

const api = axios.create({
  baseURL: API_BASE_URL,
});

export const feedsApi = {
  getFeeds: async (): Promise<Feed[]> => {
    const response = await api.get('/feeds');
    return response.data;
  },

  getFeedPosts: async (feedId: number): Promise<Episode[]> => {
    const response = await api.get(`/api/feeds/${feedId}/posts`);
    return response.data;
  },

  addFeed: async (url: string): Promise<void> => {
    const formData = new FormData();
    formData.append('url', url);
    await api.post('/feed', formData);
  },

  deleteFeed: async (feedId: number): Promise<void> => {
    await api.delete(`/feed/${feedId}`);
  },

  togglePostWhitelist: async (guid: string, whitelisted: boolean): Promise<void> => {
    await api.post(`/api/posts/${guid}/whitelist`, { whitelisted });
  },

  toggleAllPostsWhitelist: async (feedId: number): Promise<{ message: string; whitelisted_count: number; total_count: number; all_whitelisted: boolean }> => {
    const response = await api.post(`/api/feeds/${feedId}/toggle-whitelist-all`);
    return response.data;
  },

  // New post processing methods
  processPost: async (guid: string): Promise<{ status: string; job_id?: string; message: string; download_url?: string }> => {
    const response = await api.post(`/api/posts/${guid}/process`);
    return response.data;
  },

  getPostStatus: async (guid: string): Promise<{
    status: string;
    step: number;
    step_name: string;
    total_steps: number;
    message: string;
    download_url?: string;
    error?: string;
  }> => {
    const response = await api.get(`/api/posts/${guid}/status`);
    return response.data;
  },

  // Get audio URL for post
  getPostAudioUrl: (guid: string): string => {
    return `${API_BASE_URL}/api/posts/${guid}/audio`;
  },

  // Get download URL for processed post
  getPostDownloadUrl: (guid: string): string => {
    return `${API_BASE_URL}/api/posts/${guid}/download`;
  },

  // Get download URL for original post
  getPostOriginalDownloadUrl: (guid: string): string => {
    return `${API_BASE_URL}/api/posts/${guid}/download/original`;
  },

  // Download processed post
  downloadPost: async (guid: string): Promise<void> => {
    const response = await api.get(`/api/posts/${guid}/download`, {
      responseType: 'blob',
    });

    const blob = new Blob([response.data], { type: 'audio/mpeg' });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${guid}.mp3`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(url);
  },

  // Download original post
  downloadOriginalPost: async (guid: string): Promise<void> => {
    const response = await api.get(`/api/posts/${guid}/download/original`, {
      responseType: 'blob',
    });

    const blob = new Blob([response.data], { type: 'audio/mpeg' });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${guid}_original.mp3`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(url);
  },

  // Get processing stats for post
  getPostStats: async (guid: string): Promise<{
    post: {
      guid: string;
      title: string;
      duration: number | null;
      release_date: string | null;
      whitelisted: boolean;
      has_processed_audio: boolean;
    };
    processing_stats: {
      total_segments: number;
      total_model_calls: number;
      total_identifications: number;
      content_segments: number;
      ad_segments_count: number;
      ad_percentage: number;
      estimated_ad_time_seconds: number;
      model_call_statuses: Record<string, number>;
      model_types: Record<string, number>;
    };
    model_calls: Array<{
      id: number;
      model_name: string;
      status: string;
      segment_range: string;
      first_segment_sequence_num: number;
      last_segment_sequence_num: number;
      timestamp: string | null;
      retry_attempts: number;
      error_message: string | null;
      prompt: string | null;
      response: string | null;
    }>;
    transcript_segments: Array<{
      id: number;
      sequence_num: number;
      start_time: number;
      end_time: number;
      text: string;
      primary_label: 'ad' | 'content';
      identifications: Array<{
        id: number;
        label: string;
        confidence: number | null;
        model_call_id: number;
      }>;
    }>;
    identifications: Array<{
      id: number;
      transcript_segment_id: number;
      label: string;
      confidence: number | null;
      model_call_id: number;
      segment_sequence_num: number;
      segment_start_time: number;
      segment_end_time: number;
      segment_text: string;
    }>;
  }> => {
    const response = await api.get(`/api/posts/${guid}/stats`);
    return response.data;
  },

  // Legacy aliases for backward compatibility
  getFeedEpisodes: async (feedId: number): Promise<Episode[]> => {
    return feedsApi.getFeedPosts(feedId);
  },

  toggleEpisodeWhitelist: async (guid: string, whitelisted: boolean): Promise<void> => {
    return feedsApi.togglePostWhitelist(guid, whitelisted);
  },

  toggleAllEpisodesWhitelist: async (feedId: number): Promise<{ message: string; whitelisted_count: number; total_count: number; all_whitelisted: boolean }> => {
    return feedsApi.toggleAllPostsWhitelist(feedId);
  },

  processEpisode: async (guid: string): Promise<{ status: string; job_id?: string; message: string; download_url?: string }> => {
    return feedsApi.processPost(guid);
  },

  getEpisodeStatus: async (guid: string): Promise<{
    status: string;
    step: number;
    step_name: string;
    total_steps: number;
    message: string;
    download_url?: string;
    error?: string;
  }> => {
    return feedsApi.getPostStatus(guid);
  },

  getEpisodeAudioUrl: (guid: string): string => {
    return feedsApi.getPostAudioUrl(guid);
  },

  getEpisodeStats: async (guid: string): Promise<{
    post: {
      guid: string;
      title: string;
      duration: number | null;
      release_date: string | null;
      whitelisted: boolean;
      has_processed_audio: boolean;
    };
    processing_stats: {
      total_segments: number;
      total_model_calls: number;
      total_identifications: number;
      content_segments: number;
      ad_segments_count: number;
      ad_percentage: number;
      estimated_ad_time_seconds: number;
      model_call_statuses: Record<string, number>;
      model_types: Record<string, number>;
    };
    model_calls: Array<{
      id: number;
      model_name: string;
      status: string;
      segment_range: string;
      first_segment_sequence_num: number;
      last_segment_sequence_num: number;
      timestamp: string | null;
      retry_attempts: number;
      error_message: string | null;
      prompt: string | null;
      response: string | null;
    }>;
    transcript_segments: Array<{
      id: number;
      sequence_num: number;
      start_time: number;
      end_time: number;
      text: string;
      primary_label: 'ad' | 'content';
      identifications: Array<{
        id: number;
        label: string;
        confidence: number | null;
        model_call_id: number;
      }>;
    }>;
    identifications: Array<{
      id: number;
      transcript_segment_id: number;
      label: string;
      confidence: number | null;
      model_call_id: number;
      segment_sequence_num: number;
      segment_start_time: number;
      segment_end_time: number;
      segment_text: string;
    }>;
  }> => {
    return feedsApi.getPostStats(guid);
  },

  // Legacy download aliases
  downloadEpisode: async (guid: string): Promise<void> => {
    return feedsApi.downloadPost(guid);
  },

  downloadOriginalEpisode: async (guid: string): Promise<void> => {
    return feedsApi.downloadOriginalPost(guid);
  },

  getEpisodeDownloadUrl: (guid: string): string => {
    return feedsApi.getPostDownloadUrl(guid);
  },

  getEpisodeOriginalDownloadUrl: (guid: string): string => {
    return feedsApi.getPostOriginalDownloadUrl(guid);
  },
};

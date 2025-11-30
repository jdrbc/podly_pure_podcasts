import axios from 'axios';
import type {
  Feed,
  Episode,
  Job,
  JobManagerStatus,
  CleanupPreview,
  CleanupRunResult,
  CombinedConfig,
  LLMConfig,
  WhisperConfig,
  PodcastSearchResult,
  ConfigResponse,
  CreditBalanceResponse,
  CreditLedgerResponse,
} from '../types';

const API_BASE_URL = '';

const api = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
});

const buildAbsoluteUrl = (path: string): string => {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }

  const origin = API_BASE_URL || window.location.origin;
  if (path.startsWith('/')) {
    return `${origin}${path}`;
  }
  return `${origin}/${path}`;
};

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

  refreshFeed: async (
    feedId: number
  ): Promise<{ status: string; message?: string }> => {
    const response = await api.post(`/api/feeds/${feedId}/refresh`);
    return response.data;
  },

  refreshAllFeeds: async (): Promise<{
    status: string;
    feeds_refreshed: number;
    jobs_enqueued: number;
  }> => {
    const response = await api.post('/api/feeds/refresh-all');
    return response.data;
  },

  togglePostWhitelist: async (guid: string, whitelisted: boolean): Promise<void> => {
    await api.post(`/api/posts/${guid}/whitelist`, { whitelisted });
  },

  toggleAllPostsWhitelist: async (feedId: number): Promise<{ message: string; whitelisted_count: number; total_count: number; all_whitelisted: boolean }> => {
    const response = await api.post(`/api/feeds/${feedId}/toggle-whitelist-all`);
    return response.data;
  },

  sponsorFeed: async (feedId: number): Promise<Feed> => {
    const response = await api.post(`/api/feeds/${feedId}/sponsor`);
    return response.data;
  },

  searchFeeds: async (
    term: string
  ): Promise<{
    results: PodcastSearchResult[];
    total: number;
  }> => {
    const response = await api.get('/api/feeds/search', {
      params: { term },
    });
    return response.data;
  },

  // New post processing methods
  processPost: async (guid: string): Promise<{ status: string; job_id?: string; message: string; download_url?: string }> => {
    const response = await api.post(`/api/posts/${guid}/process`);
    return response.data;
  },

  reprocessPost: async (guid: string): Promise<{ status: string; job_id?: string; message: string; download_url?: string }> => {
    const response = await api.post(`/api/posts/${guid}/reprocess`);
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
    return buildAbsoluteUrl(`/api/posts/${guid}/audio`);
  },

  // Get download URL for processed post
  getPostDownloadUrl: (guid: string): string => {
    return buildAbsoluteUrl(`/api/posts/${guid}/download`);
  },

  // Get download URL for original post
  getPostOriginalDownloadUrl: (guid: string): string => {
    return buildAbsoluteUrl(`/api/posts/${guid}/download/original`);
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

  createProtectedFeedShareLink: async (
    feedId: number
  ): Promise<{ url: string; feed_token: string; feed_secret: string; feed_id: number }> => {
    const response = await api.post(`/api/feeds/${feedId}/share-link`);
    return response.data;
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

export const authApi = {
  getStatus: async (): Promise<{ require_auth: boolean }> => {
    const response = await api.get('/api/auth/status');
    return response.data;
  },

  login: async (username: string, password: string): Promise<{ user: { id: number; username: string; role: string } }> => {
    const response = await api.post('/api/auth/login', { username, password });
    return response.data;
  },

  logout: async (): Promise<void> => {
    await api.post('/api/auth/logout');
  },

  getCurrentUser: async (): Promise<{ user: { id: number; username: string; role: string } }> => {
    const response = await api.get('/api/auth/me');
    return response.data;
  },

  changePassword: async (payload: { current_password: string; new_password: string }): Promise<{ status: string }> => {
    const response = await api.post('/api/auth/change-password', payload);
    return response.data;
  },

  listUsers: async (): Promise<{ users: Array<{ id: number; username: string; role: string; created_at: string; updated_at: string; credits_balance?: string }> }> => {
    const response = await api.get('/api/auth/users');
    return response.data;
  },

  createUser: async (payload: { username: string; password: string; role: string }): Promise<{ user: { id: number; username: string; role: string; created_at: string; updated_at: string } }> => {
    const response = await api.post('/api/auth/users', payload);
    return response.data;
  },

  updateUser: async (username: string, payload: { password?: string; role?: string }): Promise<{ status: string }> => {
    const response = await api.patch(`/api/auth/users/${username}`, payload);
    return response.data;
  },

  deleteUser: async (username: string): Promise<{ status: string }> => {
    const response = await api.delete(`/api/auth/users/${username}`);
    return response.data;
  },
};

export const discordApi = {
  getStatus: async (): Promise<{ enabled: boolean }> => {
    const response = await api.get('/api/auth/discord/status');
    return response.data;
  },

  getLoginUrl: async (): Promise<{ authorization_url: string }> => {
    const response = await api.get('/api/auth/discord/login');
    return response.data;
  },

  getConfig: async (): Promise<{
    config: {
      enabled: boolean;
      client_id: string | null;
      client_secret_preview: string | null;
      redirect_uri: string | null;
      guild_ids: string;
      allow_registration: boolean;
    };
    env_overrides: Record<string, { env_var: string; value?: string; is_secret?: boolean }>;
  }> => {
    const response = await api.get('/api/auth/discord/config');
    return response.data;
  },

  updateConfig: async (payload: {
    client_id?: string;
    client_secret?: string;
    redirect_uri?: string;
    guild_ids?: string;
    allow_registration?: boolean;
  }): Promise<{
    status: string;
    config: {
      enabled: boolean;
      client_id: string | null;
      client_secret_preview: string | null;
      redirect_uri: string | null;
      guild_ids: string;
      allow_registration: boolean;
    };
  }> => {
    const response = await api.put('/api/auth/discord/config', payload);
    return response.data;
  },
};

export const creditsApi = {
  getBalance: async (): Promise<CreditBalanceResponse> => {
    const response = await api.get('/api/credits/balance');
    return response.data;
  },
  getLedger: async (limit = 20, allUsers = false): Promise<CreditLedgerResponse> => {
    const response = await api.get('/api/credits/ledger', { params: { limit, all: allUsers ? 'true' : undefined } });
    return response.data;
  },
  manualAdjust: async (user_id: number, amount: string, note?: string) => {
    const response = await api.post('/api/credits/manual-adjust', { user_id, amount, note });
    return response.data as {
      transaction: { id: number; amount: string; type: string; note?: string | null; created_at?: string | null };
      user_id: number;
      balance: string;
      updated_by?: string | null;
    };
  },
};

export const configApi = {
  getConfig: async (): Promise<ConfigResponse> => {
    const response = await api.get('/api/config');
    return response.data;
  },
  isConfigured: async (): Promise<{ configured: boolean }> => {
    const response = await api.get('/api/config/api_configured_check');
    return { configured: !!response.data?.configured };
  },
  updateConfig: async (payload: Partial<CombinedConfig>): Promise<CombinedConfig> => {
    const response = await api.put('/api/config', payload);
    return response.data;
  },
  testLLM: async (
    payload: Partial<{ llm: LLMConfig }>
  ): Promise<{ ok: boolean; message?: string; error?: string }> => {
    const response = await api.post('/api/config/test-llm', payload ?? {});
    return response.data;
  },
  testWhisper: async (
    payload: Partial<{ whisper: WhisperConfig }>
  ): Promise<{ ok: boolean; message?: string; error?: string }> => {
    const response = await api.post('/api/config/test-whisper', payload ?? {});
    return response.data;
  },
  getWhisperCapabilities: async (): Promise<{ local_available: boolean }> => {
    const response = await api.get('/api/config/whisper-capabilities');
    const local_available = !!response.data?.local_available;
    return { local_available };
  },
};

export const jobsApi = {
  getActiveJobs: async (limit: number = 100): Promise<Job[]> => {
    const response = await api.get('/api/jobs/active', { params: { limit } });
    return response.data;
  },
  getAllJobs: async (limit: number = 200): Promise<Job[]> => {
    const response = await api.get('/api/jobs/all', { params: { limit } });
    return response.data;
  },
  cancelJob: async (jobId: string): Promise<{ status: string; job_id: string; message: string }> => {
    const response = await api.post(`/api/jobs/${jobId}/cancel`);
    return response.data;
  },
  getJobManagerStatus: async (): Promise<JobManagerStatus> => {
    const response = await api.get('/api/job-manager/status');
    return response.data;
  },
  getCleanupPreview: async (): Promise<CleanupPreview> => {
    const response = await api.get('/api/jobs/cleanup/preview');
    return response.data;
  },
  runCleanupJob: async (): Promise<CleanupRunResult> => {
    const response = await api.post('/api/jobs/cleanup/run');
    return response.data;
  }
};

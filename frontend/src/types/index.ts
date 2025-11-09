export interface Feed {
  id: number;
  rss_url: string;
  title: string;
  description?: string;
  author?: string;
  image_url?: string;
  posts_count: number;
}

export interface Episode {
  id: number;
  guid: string;
  title: string;
  description: string;
  release_date: string | null;
  duration: number | null;
  whitelisted: boolean;
  has_processed_audio: boolean;
  has_unprocessed_audio: boolean;
  download_url: string;
  image_url: string | null;
  download_count: number;
} 

export interface Job {
  job_id: string;
  post_guid: string;
  post_title: string | null;
  feed_title: string | null;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'skipped' | string;
  priority: number;
  step: number;
  step_name: string | null;
  total_steps: number;
  progress_percentage: number;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
}

export interface JobManagerRun {
  id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | string;
  trigger: string;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string | null;
  total_jobs: number;
  queued_jobs: number;
  running_jobs: number;
  completed_jobs: number;
  failed_jobs: number;
  skipped_jobs: number;
  context?: Record<string, unknown> | null;
  counters_reset_at: string | null;
  progress_percentage: number;
}

export interface JobManagerStatus {
  run: JobManagerRun | null;
}

// ----- Configuration Types -----

export interface LLMConfig {
  llm_api_key?: string | null;
  llm_api_key_preview?: string | null;
  llm_model: string;
  openai_base_url?: string | null;
  openai_timeout: number;
  openai_max_tokens: number;
  llm_max_concurrent_calls: number;
  llm_max_retry_attempts: number;
  llm_max_input_tokens_per_call?: number | null;
  llm_enable_token_rate_limiting: boolean;
  llm_max_input_tokens_per_minute?: number | null;
}

export type WhisperConfig =
  | { whisper_type: 'local'; model: string }
  | {
      whisper_type: 'remote';
      model: string;
      api_key?: string | null;
      api_key_preview?: string | null;
      base_url?: string;
      language: string;
      timeout_sec: number;
      chunksize_mb: number;
    }
  | {
      whisper_type: 'groq';
      api_key?: string | null;
      api_key_preview?: string | null;
      model: string;
      language: string;
      max_retries: number;
    }
  | { whisper_type: 'test' };

export interface ProcessingConfigUI {
  num_segments_to_input_to_prompt: number;
}

export interface OutputConfigUI {
  fade_ms: number;
  // Note the intentional spelling to match backend
  min_ad_segement_separation_seconds: number;
  min_ad_segment_length_seconds: number;
  min_confidence: number;
}

export interface AppConfigUI {
  background_update_interval_minute: number | null;
  automatically_whitelist_new_episodes: boolean;
  post_cleanup_retention_days: number | null;
  number_of_episodes_to_whitelist_from_archive_of_new_feed: number;
}

export interface CombinedConfig {
  llm: LLMConfig;
  whisper: WhisperConfig;
  processing: ProcessingConfigUI;
  output: OutputConfigUI;
  app: AppConfigUI;
}

export interface EnvOverrideEntry {
  env_var: string;
  value?: string;
  value_preview?: string | null;
  is_secret?: boolean;
}

export type EnvOverrideMap = Record<string, EnvOverrideEntry>;

export interface ConfigResponse {
  config: CombinedConfig;
  env_overrides?: EnvOverrideMap;
}

export interface PodcastSearchResult {
  title: string;
  author: string;
  feedUrl: string;
  artworkUrl: string;
  description: string;
  genres: string[];
}

export interface AuthUser {
  id: number;
  username: string;
  role: 'admin' | 'user' | string;
}

export interface ManagedUser extends AuthUser {
  created_at: string;
  updated_at: string;
}

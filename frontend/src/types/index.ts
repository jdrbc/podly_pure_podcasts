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
} 

export interface Job {
  job_id: string;
  post_guid: string;
  post_title: string | null;
  feed_title: string | null;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | string;
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
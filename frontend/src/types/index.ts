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
import { useQuery } from '@tanstack/react-query';
import { feedsApi } from '../services/api';
import ChapterProcessingStats from './ChapterProcessingStats';
import LLMProcessingStats from './LLMProcessingStats';

interface ProcessingStatsButtonProps {
  episodeGuid: string;
  hasProcessedAudio: boolean;
  className?: string;
}

export default function ProcessingStatsButton({
  episodeGuid,
  hasProcessedAudio,
  className = ''
}: ProcessingStatsButtonProps) {
  const { data: stats } = useQuery({
    queryKey: ['episode-stats', episodeGuid],
    queryFn: () => feedsApi.getPostStats(episodeGuid),
    enabled: false,
    staleTime: 0,
  });

  if (!hasProcessedAudio) {
    return null;
  }

  if (stats?.ad_detection_strategy === 'chapter') {
    return <ChapterProcessingStats episodeGuid={episodeGuid} hasProcessedAudio={hasProcessedAudio} className={className} />;
  }

  return <LLMProcessingStats episodeGuid={episodeGuid} hasProcessedAudio={hasProcessedAudio} className={className} />;
}

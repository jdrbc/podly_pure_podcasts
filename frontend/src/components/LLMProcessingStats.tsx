import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { feedsApi } from '../services/api';

interface LLMProcessingStatsProps {
  episodeGuid: string;
  hasProcessedAudio: boolean;
  className?: string;
}

type TabId = 'overview' | 'model-calls' | 'transcript' | 'identifications';

export default function LLMProcessingStats({
  episodeGuid,
  hasProcessedAudio,
  className = ''
}: LLMProcessingStatsProps) {
  const [showModal, setShowModal] = useState(false);
  const [activeTab, setActiveTab] = useState<TabId>('overview');
  const [expandedModelCalls, setExpandedModelCalls] = useState<Set<number>>(new Set());

  const { data: stats, isLoading, error } = useQuery({
    queryKey: ['episode-stats', episodeGuid],
    queryFn: () => feedsApi.getPostStats(episodeGuid),
    enabled: showModal && hasProcessedAudio,
  });

  const formatDuration = (seconds: number) => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.round(seconds % 60);

    if (hours > 0) {
      return `${hours}h ${minutes}m ${secs}s`;
    }
    return `${minutes}m ${secs}s`;
  };

  const formatTimelineLabel = (seconds: number) => {
    const totalSeconds = Math.max(0, Math.round(seconds));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const secs = totalSeconds % 60;

    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }
    return `${minutes}:${secs.toString().padStart(2, '0')}`;
  };

  const formatTimestamp = (timestamp: string | null) => {
    if (!timestamp) return 'N/A';
    return new Date(timestamp).toLocaleString();
  };

  const toggleModelCallDetails = (callId: number) => {
    const newExpanded = new Set(expandedModelCalls);
    if (newExpanded.has(callId)) {
      newExpanded.delete(callId);
    } else {
      newExpanded.add(callId);
    }
    setExpandedModelCalls(newExpanded);
  };

  if (!hasProcessedAudio) {
    return null;
  }

  return (
    <>
      <button
        onClick={() => setShowModal(true)}
        className={`px-3 py-1 text-xs rounded font-medium transition-colors border bg-white text-gray-700 border-gray-300 hover:bg-gray-50 hover:border-gray-400 hover:text-gray-900 flex items-center gap-1 ${className}`}
      >
        Stats
      </button>

      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-6xl w-full max-h-[90vh] overflow-hidden">
            <div className="flex items-center justify-between p-6 border-b">
              <h2 className="text-xl font-bold text-gray-900 text-left">Processing Statistics & Debug</h2>
              <button
                onClick={() => setShowModal(false)}
                className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="border-b">
              <nav className="flex space-x-8 px-6">
                {[
                  { id: 'overview', label: 'Overview' },
                  { id: 'model-calls', label: 'Model Calls' },
                  { id: 'transcript', label: 'Transcript Segments' },
                  { id: 'identifications', label: 'Identifications' }
                ].map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id as TabId)}
                    className={`py-4 px-1 border-b-2 font-medium text-sm ${
                      activeTab === tab.id
                        ? 'border-blue-500 text-blue-600'
                        : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                    }`}
                  >
                    {tab.label}
                    {stats && tab.id === 'model-calls' && stats.model_calls && ` (${stats.model_calls.length})`}
                    {stats && tab.id === 'transcript' && stats.transcript_segments && ` (${stats.transcript_segments.length})`}
                    {stats && tab.id === 'identifications' && stats.identifications && ` (${stats.identifications.length})`}
                  </button>
                ))}
              </nav>
            </div>

            <div className="p-6 overflow-y-auto max-h-[calc(90vh-200px)]">
              {isLoading ? (
                <div className="flex items-center justify-center py-12">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
                  <span className="ml-3 text-gray-600">Loading stats...</span>
                </div>
              ) : error ? (
                <div className="text-center py-12">
                  <p className="text-red-600">Failed to load processing statistics</p>
                </div>
              ) : stats ? (
                <>
                  {activeTab === 'overview' && (
                    <div className="space-y-6">
                      <div className="bg-gray-50 rounded-lg p-4">
                        <h3 className="font-semibold text-gray-900 mb-2 text-left">Episode Information</h3>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                          <div className="text-left">
                            <span className="font-medium text-gray-700">Title:</span>
                            <span className="ml-2 text-gray-600">{stats.post?.title || 'Unknown'}</span>
                          </div>
                          <div className="text-left">
                            <span className="font-medium text-gray-700">Duration:</span>
                            <span className="ml-2 text-gray-600">
                              {stats.post?.duration ? formatDuration(stats.post.duration) : 'Unknown'}
                            </span>
                          </div>
                          <div className="text-left">
                            <span className="font-medium text-gray-700">Detection Method:</span>
                            <span className="ml-2 px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">
                              LLM Transcription
                            </span>
                          </div>
                        </div>
                      </div>

                      <div>
                        <h3 className="font-semibold text-gray-900 mb-4 text-left">Key Metrics</h3>
                        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                          <div className="bg-gradient-to-br from-blue-50 to-blue-100 rounded-lg p-4 text-center">
                            <div className="text-2xl font-bold text-blue-600">
                              {stats.processing_stats?.total_segments || 0}
                            </div>
                            <div className="text-sm text-blue-800">Transcript Segments</div>
                          </div>

                          <div className="bg-gradient-to-br from-green-50 to-green-100 rounded-lg p-4 text-center">
                            <div className="text-2xl font-bold text-green-600">
                              {stats.processing_stats?.content_segments || 0}
                            </div>
                            <div className="text-sm text-green-800">Content Segments</div>
                          </div>

                          <div className="bg-gradient-to-br from-red-50 to-red-100 rounded-lg p-4 text-center">
                            <div className="text-2xl font-bold text-red-600">
                              {stats.processing_stats?.ad_segments_count || 0}
                            </div>
                            <div className="text-sm text-red-800">Ad Segments Removed</div>
                          </div>
                        </div>
                      </div>

                      {(() => {
                        const durationSeconds = stats.post?.duration
                          ?? (stats.transcript_segments?.length
                            ? Math.max(...stats.transcript_segments.map((segment) => segment.end_time))
                            : 0);
                        const fallbackAdBlocks = (() => {
                          const adSegments = (stats.transcript_segments || [])
                            .filter((segment) => segment.primary_label === 'ad')
                            .map((segment) => ({ start: segment.start_time, end: segment.end_time }))
                            .sort((a, b) => a.start - b.start);

                          if (!adSegments.length) return [];

                          const merged: Array<{ start: number; end: number }> = [];
                          let current = { ...adSegments[0] };
                          const gapSeconds = 1;
                          for (const segment of adSegments.slice(1)) {
                            if (segment.start <= current.end + gapSeconds) {
                              current.end = Math.max(current.end, segment.end);
                            } else {
                              merged.push(current);
                              current = { ...segment };
                            }
                          }
                          merged.push(current);
                          return merged;
                        })();

                        const apiAdBlocks = (stats.processing_stats?.ad_blocks || []).map((block) => ({
                          start: block.start_time,
                          end: block.end_time,
                        }));
                        const adBlocks = apiAdBlocks.length ? apiAdBlocks : fallbackAdBlocks;
                        const adTimeSeconds = stats.processing_stats?.estimated_ad_time_seconds
                          ?? adBlocks.reduce((sum, block) => sum + Math.max(0, block.end - block.start), 0);
                        const adPercent = durationSeconds > 0
                          ? (adTimeSeconds / durationSeconds) * 100
                          : 0;
                        const cleanSeconds = Math.max(0, durationSeconds - adTimeSeconds);
                        const timelineTicks = [0, 0.25, 0.5, 0.75, 1];

                        return (
                          <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
                            <h3 className="font-semibold text-gray-900 mb-4 text-left">Advertisement Removal Summary</h3>
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-center">
                              <div>
                                <div className="text-2xl font-bold text-blue-600">{adBlocks.length}</div>
                                <div className="text-sm text-gray-600">Ad Blocks</div>
                              </div>
                              <div>
                                <div className="text-2xl font-bold text-blue-600">{formatDuration(adTimeSeconds)}</div>
                                <div className="text-sm text-gray-600">Time Removed</div>
                              </div>
                              <div>
                                <div className="text-2xl font-bold text-rose-600">{adPercent.toFixed(1)}%</div>
                                <div className="text-sm text-gray-600">Episode Reduced</div>
                              </div>
                            </div>

                            <div className="mt-5 space-y-3">
                              <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-gray-600">
                                <div className="flex items-center gap-2">
                                  <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-white text-gray-500 border border-gray-200">
                                    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                                    </svg>
                                  </span>
                                  Episode Timeline
                                </div>
                                <div className="text-gray-600">
                                  {formatDuration(cleanSeconds)} clean
                                  <span className="text-rose-600 ml-2">
                                    {formatDuration(adTimeSeconds)} removed ({adPercent.toFixed(1)}%)
                                  </span>
                                </div>
                              </div>

                              <div className="relative h-3 w-full rounded-full bg-gray-200 overflow-hidden">
                                <div className="absolute inset-0 bg-gradient-to-r from-blue-500/20 via-blue-400/15 to-blue-500/20" />
                                {durationSeconds > 0 && adBlocks.map((block, index) => {
                                  const left = Math.max(0, (block.start / durationSeconds) * 100);
                                  const width = Math.max(0.5, ((block.end - block.start) / durationSeconds) * 100);
                                  return (
                                    <div
                                      key={`${block.start}-${block.end}-${index}`}
                                      className="absolute top-0 h-full rounded-full bg-rose-500/70"
                                      style={{ left: `${left}%`, width: `${width}%` }}
                                    />
                                  );
                                })}
                              </div>

                              <div className="flex justify-between text-xs text-gray-500">
                                {timelineTicks.map((tick) => (
                                  <span key={tick}>{formatTimelineLabel(durationSeconds * tick)}</span>
                                ))}
                              </div>

                              <div className="flex items-center gap-4 text-xs text-gray-500">
                                <span className="flex items-center gap-2">
                                  <span className="h-2 w-2 rounded-full bg-blue-500" />
                                  Content
                                </span>
                                <span className="flex items-center gap-2">
                                  <span className="h-2 w-2 rounded-full bg-rose-500" />
                                  Ads removed
                                </span>
                              </div>
                            </div>
                          </div>
                        );
                      })()}

                      <div>
                        <h3 className="font-semibold text-gray-900 mb-4 text-left">AI Model Performance</h3>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                          <div className="bg-white border rounded-lg p-4">
                            <h4 className="font-medium text-gray-900 mb-3 text-left">Processing Status</h4>
                            <div className="space-y-2">
                              {Object.entries(stats.processing_stats?.model_call_statuses || {}).map(([status, count]) => (
                                <div key={status} className="flex justify-between items-center">
                                  <span className="text-sm text-gray-600 capitalize">{status}</span>
                                  <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                                    status === 'success' ? 'bg-green-100 text-green-800' :
                                    status === 'failed' ? 'bg-red-100 text-red-800' :
                                    'bg-gray-100 text-gray-800'
                                  }`}>
                                    {count}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>

                          <div className="bg-white border rounded-lg p-4">
                            <h4 className="font-medium text-gray-900 mb-3 text-left">Models Used</h4>
                            <div className="space-y-2">
                              {Object.entries(stats.processing_stats?.model_types || {}).map(([model, count]) => (
                                <div key={model} className="flex justify-between items-center">
                                  <span className="text-sm text-gray-600">{model}</span>
                                  <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-xs font-medium">
                                    {count} calls
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {activeTab === 'model-calls' && (
                    <div>
                      <h3 className="font-semibold text-gray-900 mb-4 text-left">Model Calls ({stats.model_calls?.length || 0})</h3>
                      <div className="bg-white border rounded-lg overflow-hidden">
                        <div className="overflow-x-auto">
                          <table className="min-w-full divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                              <tr>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">ID</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Model</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Segment Range</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Timestamp</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Retries</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                              </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-200">
                              {(stats.model_calls || []).map((call) => (
                                <>
                                  <tr key={call.id} className="hover:bg-gray-50">
                                    <td className="px-4 py-3 text-sm text-gray-900">{call.id}</td>
                                    <td className="px-4 py-3 text-sm text-gray-900">{call.model_name}</td>
                                    <td className="px-4 py-3 text-sm text-gray-600">{call.segment_range}</td>
                                    <td className="px-4 py-3">
                                      <span className={`inline-flex px-2 py-1 text-xs font-medium rounded-full ${
                                        call.status === 'success' ? 'bg-green-100 text-green-800' :
                                        call.status === 'failed' ? 'bg-red-100 text-red-800' :
                                        'bg-yellow-100 text-yellow-800'
                                      }`}>
                                        {call.status}
                                      </span>
                                    </td>
                                    <td className="px-4 py-3 text-sm text-gray-600">{formatTimestamp(call.timestamp)}</td>
                                    <td className="px-4 py-3 text-sm text-gray-600">{call.retry_attempts}</td>
                                    <td className="px-4 py-3">
                                      <button
                                        onClick={() => toggleModelCallDetails(call.id)}
                                        className="text-blue-600 hover:text-blue-800 text-sm font-medium"
                                      >
                                        {expandedModelCalls.has(call.id) ? 'Hide' : 'Details'}
                                      </button>
                                    </td>
                                  </tr>
                                  {expandedModelCalls.has(call.id) && (
                                    <tr className="bg-gray-50">
                                      <td colSpan={7} className="px-4 py-4">
                                        <div className="space-y-4">
                                          {call.prompt && (
                                            <div>
                                              <h5 className="font-medium text-gray-900 mb-2 text-left">Prompt:</h5>
                                              <div className="bg-gray-100 p-3 rounded text-sm font-mono whitespace-pre-wrap max-h-40 overflow-y-auto text-left">
                                                {call.prompt}
                                              </div>
                                            </div>
                                          )}
                                          {call.error_message && (
                                            <div>
                                              <h5 className="font-medium text-red-900 mb-2 text-left">Error Message:</h5>
                                              <div className="bg-red-50 p-3 rounded text-sm font-mono whitespace-pre-wrap text-left">
                                                {call.error_message}
                                              </div>
                                            </div>
                                          )}
                                          {call.response && (
                                            <div>
                                              <h5 className="font-medium text-gray-900 mb-2 text-left">Response:</h5>
                                              <div className="bg-gray-100 p-3 rounded text-sm font-mono whitespace-pre-wrap max-h-40 overflow-y-auto text-left">
                                                {call.response}
                                              </div>
                                            </div>
                                          )}
                                        </div>
                                      </td>
                                    </tr>
                                  )}
                                </>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    </div>
                  )}

                  {activeTab === 'transcript' && (
                    <div>
                      <h3 className="font-semibold text-gray-900 mb-4 text-left">Transcript Segments ({stats.transcript_segments?.length || 0})</h3>
                      <div className="bg-white border rounded-lg overflow-hidden">
                        <div className="overflow-x-auto">
                          <table className="min-w-full divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                              <tr>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Seq #</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Time Range</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Label</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Text</th>
                              </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-200">
                              {(stats.transcript_segments || []).map((segment) => (
                                <tr key={segment.id} className={`hover:bg-gray-50 ${
                                  segment.primary_label === 'ad' ? 'bg-red-50' : ''
                                }`}>
                                  <td className="px-4 py-3 text-sm text-gray-900">{segment.sequence_num}</td>
                                  <td className="px-4 py-3 text-sm text-gray-600">
                                    {segment.start_time}s - {segment.end_time}s
                                  </td>
                                  <td className="px-4 py-3">
                                    <span className={`inline-flex px-2 py-1 text-xs font-medium rounded-full ${
                                      segment.primary_label === 'ad'
                                        ? 'bg-red-100 text-red-800'
                                        : 'bg-green-100 text-green-800'
                                    }`}>
                                      {segment.primary_label === 'ad'
                                        ? (segment.mixed ? 'Ad (mixed)' : 'Ad')
                                        : 'Content'}
                                    </span>
                                  </td>
                                  <td className="px-4 py-3 text-sm text-gray-900 max-w-md">
                                    <div className="truncate text-left" title={segment.text}>
                                      {segment.text}
                                    </div>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    </div>
                  )}

                  {activeTab === 'identifications' && (
                    <div>
                      <h3 className="font-semibold text-gray-900 mb-4 text-left">Identifications ({stats.identifications?.length || 0})</h3>
                      <div className="bg-white border rounded-lg overflow-hidden">
                        <div className="overflow-x-auto">
                          <table className="min-w-full divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                              <tr>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">ID</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Segment ID</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Time Range</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Label</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Confidence</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Model Call</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Text</th>
                              </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-200">
                              {(stats.identifications || []).map((identification) => (
                                <tr key={identification.id} className={`hover:bg-gray-50 ${
                                  identification.label === 'ad' ? 'bg-red-50' : ''
                                }`}>
                                  <td className="px-4 py-3 text-sm text-gray-900">{identification.id}</td>
                                  <td className="px-4 py-3 text-sm text-gray-600">{identification.transcript_segment_id}</td>
                                  <td className="px-4 py-3 text-sm text-gray-600">
                                    {identification.segment_start_time}s - {identification.segment_end_time}s
                                  </td>
                                  <td className="px-4 py-3">
                                    <span className={`inline-flex px-2 py-1 text-xs font-medium rounded-full ${
                                      identification.label === 'ad'
                                        ? 'bg-red-100 text-red-800'
                                        : 'bg-green-100 text-green-800'
                                    }`}>
                                      {identification.label === 'ad'
                                        ? (identification.mixed ? 'ad (mixed)' : 'ad')
                                        : identification.label}
                                    </span>
                                  </td>
                                  <td className="px-4 py-3 text-sm text-gray-600">
                                    {identification.confidence ? identification.confidence.toFixed(2) : 'N/A'}
                                  </td>
                                  <td className="px-4 py-3 text-sm text-gray-600">{identification.model_call_id}</td>
                                  <td className="px-4 py-3 text-sm text-gray-900 max-w-md">
                                    <div className="truncate text-left" title={identification.segment_text}>
                                      {identification.segment_text}
                                    </div>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    </div>
                  )}
                </>
              ) : null}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

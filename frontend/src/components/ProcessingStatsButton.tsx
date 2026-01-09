import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { feedsApi } from '../services/api';

interface ProcessingStatsButtonProps {
  episodeGuid: string;
  hasProcessedAudio: boolean;
  className?: string;
}

type TabId = 'overview' | 'model-calls' | 'transcript' | 'identifications' | 'chapters';

export default function ProcessingStatsButton({
  episodeGuid,
  hasProcessedAudio,
  className = ''
}: ProcessingStatsButtonProps) {
  const [showModal, setShowModal] = useState(false);
  const [activeTab, setActiveTab] = useState<TabId>('overview');
  const [expandedModelCalls, setExpandedModelCalls] = useState<Set<number>>(new Set());

  const { data: stats, isLoading, error } = useQuery({
    queryKey: ['episode-stats', episodeGuid],
    queryFn: () => feedsApi.getPostStats(episodeGuid),
    enabled: showModal && hasProcessedAudio, // Only fetch when modal is open and episode is processed
  });

  const formatDuration = (seconds: number) => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.round(seconds % 60); // Round to nearest whole second

    if (hours > 0) {
      return `${hours}h ${minutes}m ${secs}s`;
    }
    return `${minutes}m ${secs}s`;
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

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg max-w-6xl w-full max-h-[90vh] overflow-hidden">
            {/* Header */}
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

            {/* Tabs */}
            <div className="border-b">
              <nav className="flex space-x-8 px-6">
                {(stats?.ad_detection_strategy === 'chapter' ? [
                  { id: 'overview', label: 'Overview' },
                  { id: 'chapters', label: 'Chapters' }
                ] : [
                  { id: 'overview', label: 'Overview' },
                  { id: 'model-calls', label: 'Model Calls' },
                  { id: 'transcript', label: 'Transcript Segments' },
                  { id: 'identifications', label: 'Identifications' }
                ]).map((tab) => (
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
                    {stats && tab.id === 'chapters' && stats.chapters && ` (${stats.chapters.chapters?.length || 0})`}
                  </button>
                ))}
              </nav>
            </div>

            {/* Content */}
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
                  {/* Overview Tab */}
                  {activeTab === 'overview' && (
                    <div className="space-y-6">
                      {/* Episode Info */}
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
                            <span className={`ml-2 px-2 py-0.5 rounded text-xs font-medium ${
                              stats.ad_detection_strategy === 'chapter'
                                ? 'bg-purple-100 text-purple-800'
                                : 'bg-blue-100 text-blue-800'
                            }`}>
                              {stats.ad_detection_strategy === 'chapter' ? 'Chapter-based' : 'LLM Transcription'}
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Key Metrics - Different display for chapter vs LLM */}
                      <div>
                        <h3 className="font-semibold text-gray-900 mb-4 text-left">Key Metrics</h3>
                        {stats.ad_detection_strategy === 'chapter' ? (
                          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                            <div className="bg-gradient-to-br from-purple-50 to-purple-100 rounded-lg p-4 text-center">
                              <div className="text-2xl font-bold text-purple-600">
                                {stats.chapters?.total_chapters || 0}
                              </div>
                              <div className="text-sm text-purple-800">Total Chapters</div>
                            </div>

                            <div className="bg-gradient-to-br from-green-50 to-green-100 rounded-lg p-4 text-center">
                              <div className="text-2xl font-bold text-green-600">
                                {stats.chapters?.chapters_kept || 0}
                              </div>
                              <div className="text-sm text-green-800">Chapters Kept</div>
                            </div>

                            <div className="bg-gradient-to-br from-red-50 to-red-100 rounded-lg p-4 text-center">
                              <div className="text-2xl font-bold text-red-600">
                                {stats.chapters?.chapters_removed || 0}
                              </div>
                              <div className="text-sm text-red-800">Chapters Removed</div>
                            </div>
                          </div>
                        ) : (
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
                        )}
                      </div>

                      {/* Chapter Filter Strings - Only for chapter strategy */}
                      {stats.ad_detection_strategy === 'chapter' && stats.chapters?.filter_strings && (
                        <div>
                          <h3 className="font-semibold text-gray-900 mb-4 text-left">Filter Strings</h3>
                          <div className="bg-white border rounded-lg p-4">
                            <div className="flex flex-wrap gap-2">
                              {stats.chapters.filter_strings.map((filter: string, idx: number) => (
                                <span key={idx} className="px-3 py-1 bg-gray-100 text-gray-700 rounded-full text-sm">
                                  {filter}
                                </span>
                              ))}
                            </div>
                          </div>
                        </div>
                      )}

                      {/* Model Performance - Only for LLM strategy */}
                      {stats.ad_detection_strategy !== 'chapter' && (
                        <div>
                          <h3 className="font-semibold text-gray-900 mb-4 text-left">AI Model Performance</h3>
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            {/* Model Call Status */}
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

                            {/* Model Types */}
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
                      )}
                    </div>
                  )}

                  {/* Model Calls Tab */}
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

                  {/* Transcript Segments Tab */}
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
                                      {segment.primary_label === 'ad' ? 'Ad' : 'Content'}
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

                  {/* Identifications Tab */}
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
                                      {identification.label}
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

                  {/* Chapters Tab */}
                  {activeTab === 'chapters' && (
                    <div>
                      <h3 className="font-semibold text-gray-900 mb-4 text-left">Chapters ({stats.chapters?.chapters?.length || 0})</h3>
                      <div className="bg-white border rounded-lg overflow-hidden">
                        <div className="overflow-x-auto">
                          <table className="min-w-full divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                              <tr>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">#</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Title</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Time Range</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Duration</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                              </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-200">
                              {(stats.chapters?.chapters || []).map((chapter: { title: string; start_time: number; end_time: number; label: string }, idx: number) => (
                                <tr key={idx} className={`hover:bg-gray-50 ${
                                  chapter.label === 'ad' ? 'bg-red-50' : ''
                                }`}>
                                  <td className="px-4 py-3 text-sm text-gray-900">{idx + 1}</td>
                                  <td className="px-4 py-3 text-sm text-gray-900 font-medium">{chapter.title}</td>
                                  <td className="px-4 py-3 text-sm text-gray-600">
                                    {chapter.start_time}s - {chapter.end_time}s
                                  </td>
                                  <td className="px-4 py-3 text-sm text-gray-600">
                                    {Math.round(chapter.end_time - chapter.start_time)}s
                                  </td>
                                  <td className="px-4 py-3">
                                    <span className={`inline-flex px-2 py-1 text-xs font-medium rounded-full ${
                                      chapter.label === 'ad'
                                        ? 'bg-red-100 text-red-800'
                                        : 'bg-green-100 text-green-800'
                                    }`}>
                                      {chapter.label === 'ad' ? 'Removed' : 'Kept'}
                                    </span>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                      {stats.chapters?.note && (
                        <div className="mt-4 p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-800">
                          Note: {stats.chapters.note}
                        </div>
                      )}
                      {(!stats.chapters?.chapters || stats.chapters.chapters.length === 0) && (
                        <div className="text-center py-8 text-gray-500">
                          No chapter data available.
                        </div>
                      )}
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

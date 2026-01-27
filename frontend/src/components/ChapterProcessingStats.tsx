import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { feedsApi } from '../services/api';

interface ChapterProcessingStatsProps {
  episodeGuid: string;
  hasProcessedAudio: boolean;
  className?: string;
}

type TabId = 'overview' | 'chapters';

export default function ChapterProcessingStats({
  episodeGuid,
  hasProcessedAudio,
  className = ''
}: ChapterProcessingStatsProps) {
  const [showModal, setShowModal] = useState(false);
  const [activeTab, setActiveTab] = useState<TabId>('overview');

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
                  { id: 'chapters', label: 'Chapters' }
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
                    {stats && tab.id === 'chapters' && stats.chapters && ` (${stats.chapters.chapters?.length || 0})`}
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
                            <span className="ml-2 px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-800">
                              Chapter-based
                            </span>
                          </div>
                        </div>
                      </div>

                      <div>
                        <h3 className="font-semibold text-gray-900 mb-4 text-left">Key Metrics</h3>
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
                      </div>

                      {stats.chapters?.filter_strings && (
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
                    </div>
                  )}

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

import { useState } from 'react';
import { feedsApi } from '../services/api';

interface AddFeedFormProps {
  onSuccess: () => void;
}

export default function AddFeedForm({ onSuccess }: AddFeedFormProps) {
  const [url, setUrl] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return;

    setIsSubmitting(true);
    setError('');

    try {
      await feedsApi.addFeed(url.trim());
      setUrl('');
      onSuccess();
    } catch (err) {
      console.error('Failed to add feed:', err);
      setError('Failed to add feed. Please check the URL and try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="bg-white rounded-lg border p-4">
      <h3 className="text-lg font-medium text-gray-900 mb-4">Add New Podcast Feed</h3>
      
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="feed-url" className="block text-sm font-medium text-gray-700 mb-1">
            RSS Feed URL
          </label>
          <input
            type="url"
            id="feed-url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://example.com/podcast/feed.xml"
            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            required
          />
        </div>

        {error && (
          <div className="text-red-600 text-sm">{error}</div>
        )}

        <div className="flex justify-end space-x-3">
          <button
            type="submit"
            disabled={isSubmitting || !url.trim()}
            className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white px-4 py-2 rounded-md font-medium transition-colors"
          >
            {isSubmitting ? 'Adding...' : 'Add Feed'}
          </button>
        </div>
      </form>
    </div>
  );
} 
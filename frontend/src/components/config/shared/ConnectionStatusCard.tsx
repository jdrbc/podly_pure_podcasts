interface ConnectionStatusCardProps {
  title: string;
  status: 'loading' | 'ok' | 'error';
  message: string;
  error?: string;
  onRetry: () => void;
}

export default function ConnectionStatusCard({
  title,
  status,
  message,
  error,
  onRetry,
}: ConnectionStatusCardProps) {
  const statusColor =
    status === 'ok'
      ? 'text-green-700'
      : status === 'error'
      ? 'text-red-700'
      : 'text-gray-600';

  const displayMessage =
    status === 'loading'
      ? 'Testing...'
      : status === 'ok'
      ? message || `${title} connection OK`
      : error || `${title} connection failed`;

  return (
    <div className="flex items-start justify-between border rounded p-3">
      <div>
        <div className="text-sm font-medium text-gray-900">{title}</div>
        <div className={`text-xs ${statusColor}`}>{displayMessage}</div>
      </div>
      <button
        type="button"
        className="text-xs text-indigo-600 hover:underline"
        onClick={onRetry}
      >
        Retry
      </button>
    </div>
  );
}

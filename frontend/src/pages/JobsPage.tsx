import { useCallback, useEffect, useRef, useState } from 'react';
import { jobsApi } from '../services/api';
import type { CleanupPreview, Job, JobManagerRun, JobManagerStatus } from '../types';

function getStatusColor(status: string) {
  switch (status) {
    case 'running':
      return 'bg-green-100 text-green-800';
    case 'pending':
      return 'bg-yellow-100 text-yellow-800';
    case 'failed':
      return 'bg-red-100 text-red-800';
    case 'completed':
      return 'bg-blue-100 text-blue-800';
    case 'skipped':
      return 'bg-purple-100 text-purple-800';
    case 'cancelled':
      return 'bg-gray-100 text-gray-800';
    default:
      return 'bg-gray-100 text-gray-800';
  }
}

function StatusBadge({ status }: { status: string }) {
  const color = getStatusColor(status);
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${color}`}>
      {status}
    </span>
  );
}

function ProgressBar({ value }: { value: number }) {
  const clamped = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div className="w-full bg-gray-200 rounded h-2">
      <div
        className="bg-indigo-600 h-2 rounded"
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}

function RunStat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-gray-500">{label}</div>
      <div className="mt-1 text-lg font-semibold text-gray-900">{value}</div>
    </div>
  );
}

function formatDateTime(value: string | null): string {
  if (!value) {
    return '—';
  }
  try {
    return new Date(value).toLocaleString();
  } catch (err) {
    console.error('Failed to format date', err);
    return value;
  }
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [managerStatus, setManagerStatus] = useState<JobManagerStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<'active' | 'all'>('active');
  const [cancellingJobs, setCancellingJobs] = useState<Set<string>>(new Set());
  const previousHasActiveWork = useRef<boolean>(false);
  const [cleanupPreview, setCleanupPreview] = useState<CleanupPreview | null>(null);
  const [cleanupLoading, setCleanupLoading] = useState(false);
  const [cleanupError, setCleanupError] = useState<string | null>(null);
  const [cleanupRunning, setCleanupRunning] = useState(false);
  const [cleanupMessage, setCleanupMessage] = useState<string | null>(null);

  const loadStatus = useCallback(async () => {
    try {
      const data = await jobsApi.getJobManagerStatus();
      setManagerStatus(data);
      setStatusError(null);
    } catch (e) {
      console.error('Failed to load job manager status:', e);
      setStatusError('Failed to load manager status');
    }
  }, []);

  const loadActive = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await jobsApi.getActiveJobs(100);
      setJobs(data);
    } catch (e) {
      console.error('Failed to load active jobs:', e);
      setError('Failed to load jobs');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await jobsApi.getAllJobs(200);
      setJobs(data);
    } catch (e) {
      console.error('Failed to load all jobs:', e);
      setError('Failed to load jobs');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadCleanupPreview = useCallback(async () => {
    setCleanupLoading(true);
    try {
      const data = await jobsApi.getCleanupPreview();
      setCleanupPreview(data);
      setCleanupError(null);
    } catch (e) {
      console.error('Failed to load cleanup preview:', e);
      setCleanupError('Failed to load cleanup preview');
    } finally {
      setCleanupLoading(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    await loadStatus();
    if (mode === 'active') {
      await loadActive();
    } else {
      await loadAll();
    }
    await loadCleanupPreview();
  }, [mode, loadActive, loadAll, loadStatus, loadCleanupPreview]);

  const cancelJob = useCallback(
    async (jobId: string) => {
      setCancellingJobs(prev => new Set(prev).add(jobId));
      try {
        await jobsApi.cancelJob(jobId);
        await refresh();
      } catch (e) {
        setError(`Failed to cancel job: ${e instanceof Error ? e.message : 'Unknown error'}`);
      } finally {
        setCancellingJobs(prev => {
          const newSet = new Set(prev);
          newSet.delete(jobId);
          return newSet;
        });
      }
    },
    [refresh]
  );

  const runCleanupNow = useCallback(async () => {
    setCleanupRunning(true);
    setCleanupError(null);
    setCleanupMessage(null);
    try {
      const result = await jobsApi.runCleanupJob();
      if (result.status === 'disabled') {
        setCleanupMessage(result.message ?? 'Cleanup is disabled.');
        return;
      }
      if (result.status !== 'ok') {
        setCleanupError(result.message ?? 'Cleanup job failed');
        return;
      }
      const removed = result.removed_posts ?? 0;
      const remaining = result.remaining_candidates ?? 0;
      const removedText = `Cleanup removed ${removed} episode${removed === 1 ? '' : 's'}.`;
      const remainingText =
        remaining > 0
          ? ` ${remaining} episode${remaining === 1 ? '' : 's'} still eligible.`
          : '';
      setCleanupMessage(`${removedText}${remainingText}`);
      await refresh();
    } catch (e) {
      console.error('Failed to run cleanup job:', e);
      setCleanupError('Failed to run cleanup job');
    } finally {
      setCleanupRunning(false);
    }
  }, [refresh]);

  useEffect(() => {
    void loadStatus();
    void loadActive();
    void loadCleanupPreview();
  }, [loadActive, loadStatus, loadCleanupPreview]);

  useEffect(() => {
    const queued = managerStatus?.run?.queued_jobs ?? 0;
    const running = managerStatus?.run?.running_jobs ?? 0;
    const hasActiveWork = queued + running > 0;
    if (!hasActiveWork) {
      return undefined;
    }

    // Poll every 15 seconds when jobs are active to reduce database contention
    const interval = setInterval(() => {
      void loadStatus();
    }, 15000);

    return () => clearInterval(interval);
  }, [managerStatus?.run?.queued_jobs, managerStatus?.run?.running_jobs, loadStatus]);

  useEffect(() => {
    const queued = managerStatus?.run?.queued_jobs ?? 0;
    const running = managerStatus?.run?.running_jobs ?? 0;
    const hasActiveWork = queued + running > 0;
    if (!hasActiveWork && previousHasActiveWork.current) {
      void refresh();
    }
    previousHasActiveWork.current = hasActiveWork;
  }, [managerStatus?.run?.queued_jobs, managerStatus?.run?.running_jobs, refresh]);

  const run: JobManagerRun | null = managerStatus?.run ?? null;
  const hasActiveWork = run ? run.queued_jobs + run.running_jobs > 0 : false;
  const retentionDays = cleanupPreview?.retention_days ?? null;
  const cleanupDisabled = retentionDays === null || retentionDays <= 0;
  const cleanupEligibleCount = cleanupPreview?.count ?? 0;

  return (
    <div className="space-y-4">
      <div className="rounded border border-gray-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-gray-900">Jobs Manager</h2>
            <p className="text-xs text-gray-600">
              {run
                ? hasActiveWork
                  ? `Processing · Last update ${formatDateTime(run.updated_at)}`
                  : `Idle · Last activity ${formatDateTime(run.updated_at)}`
                : 'Jobs Manager has not started yet.'}
            </p>
          </div>
          {run ? (
            <StatusBadge status={run.status} />
          ) : (
            <span className="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-800">
              idle
            </span>
          )}
        </div>

        {statusError && (
          <div className="mt-2 text-xs text-red-600">{statusError}</div>
        )}

        {run ? (
          <>
            <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
              <RunStat label="Queued" value={run.queued_jobs} />
              <RunStat label="Running" value={run.running_jobs} />
              <RunStat label="Completed" value={run.completed_jobs} />
              <RunStat label="Skipped" value={run.skipped_jobs} />
              <RunStat label="Failed" value={run.failed_jobs} />
            </div>
            <div className="mt-4 space-y-1">
              <ProgressBar value={run.progress_percentage} />
              <div className="text-xs text-gray-500">
                {run.completed_jobs} completed · {run.skipped_jobs} skipped · {run.failed_jobs} failed of {run.total_jobs} jobs
              </div>
            </div>
            <div className="mt-3 text-xs text-gray-500">
              Trigger: <span className="font-medium text-gray-700">{run.trigger}</span>
            </div>
            {run.counters_reset_at ? (
              <div className="mt-1 text-xs text-gray-500">
                Stats since {formatDateTime(run.counters_reset_at)}
              </div>
            ) : null}
          </>
        ) : null}
      </div>

      <div className="rounded border border-gray-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-base font-semibold text-gray-900">Post Cleanup</h3>
            <p className="text-xs text-gray-600">
              {cleanupDisabled
                ? 'Cleanup is disabled while retention days are unset or zero.'
                : `Episodes older than ${retentionDays} day${retentionDays === 1 ? '' : 's'} will be removed.`}
            </p>
          </div>
          <div className="text-right">
            <div className="text-xs uppercase tracking-wide text-gray-500">Eligible</div>
            <div className="text-lg font-semibold text-gray-900">
              {cleanupLoading ? '…' : cleanupEligibleCount}
            </div>
          </div>
        </div>

        {cleanupError && (
          <div className="mt-2 text-xs text-red-600">{cleanupError}</div>
        )}
        {cleanupMessage && (
          <div className="mt-2 text-xs text-green-700">{cleanupMessage}</div>
        )}

        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <div className="text-xs uppercase tracking-wide text-gray-500">Retention</div>
            <div className="text-sm font-medium text-gray-900">
              {cleanupDisabled ? 'Disabled' : `${retentionDays} day${retentionDays === 1 ? '' : 's'}`}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-wide text-gray-500">Eligible episodes</div>
            <div className="text-sm font-medium text-gray-900">
              {cleanupLoading ? 'Loading…' : cleanupEligibleCount}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-wide text-gray-500">Cutoff date</div>
            <div className="text-sm font-medium text-gray-900">
              {cleanupPreview?.cutoff_utc ? formatDateTime(cleanupPreview.cutoff_utc) : '—'}
            </div>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <div className="text-xs text-gray-500">
            Includes completed jobs and non-whitelisted episodes with release dates older than the retention window.
          </div>
          <button
            onClick={() => { void runCleanupNow(); }}
            disabled={cleanupRunning || cleanupDisabled || cleanupLoading}
            className="inline-flex items-center rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:bg-gray-300 disabled:text-gray-500 disabled:cursor-not-allowed"
          >
            {cleanupRunning ? 'Running cleanup…' : 'Run cleanup now'}
          </button>
        </div>
      </div>

      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-xl font-semibold text-gray-900">{mode === 'active' ? 'Active Jobs' : 'All Jobs'}</h3>
          <p className="text-sm text-gray-600">
            {mode === 'active'
              ? 'Queued and running jobs, ordered by priority.'
              : 'All jobs ordered by priority (running/pending first).'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => { void refresh(); }}
            className="inline-flex items-center rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            disabled={loading}
          >
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
          {mode === 'active' ? (
            <button
              onClick={async () => { setMode('all'); await loadStatus(); await loadAll(); await loadCleanupPreview(); }}
              className="inline-flex items-center rounded-md bg-gray-200 px-3 py-1.5 text-sm font-medium text-gray-800 hover:bg-gray-300 focus:outline-none focus:ring-2 focus:ring-gray-400"
              disabled={loading}
            >
              Load all jobs
            </button>
          ) : (
            <button
              onClick={async () => { setMode('active'); await loadStatus(); await loadActive(); await loadCleanupPreview(); }}
              className="inline-flex items-center rounded-md bg-gray-200 px-3 py-1.5 text-sm font-medium text-gray-800 hover:bg-gray-300 focus:outline-none focus:ring-2 focus:ring-gray-400"
              disabled={loading}
            >
              Show active only
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</div>
      )}

      {jobs.length === 0 && !loading ? (
        <div className="text-sm text-gray-600">No jobs to display.</div>
      ) : null}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {jobs.map((job) => (
          <div key={job.job_id} className="bg-white border rounded shadow-sm p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="text-sm font-medium text-gray-900 truncate">
                {job.post_title || 'Untitled episode'}
              </div>
              <StatusBadge status={job.status} />
            </div>
            <div className="text-xs text-gray-600 truncate">{job.feed_title || 'Unknown feed'}</div>

            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs text-gray-700">
                <span>Priority</span>
                <span className="font-medium">{job.priority}</span>
              </div>
              <div className="flex items-center justify-between text-xs text-gray-700">
                <span>Step</span>
                <span className="font-medium">{job.step}/{job.total_steps} {job.step_name ? `· ${job.step_name}` : ''}</span>
              </div>
              <div className="space-y-1">
                <div className="flex items-center justify-between text-xs text-gray-700">
                  <span>Progress</span>
                  <span className="font-medium">{Math.round(job.progress_percentage)}%</span>
                </div>
                <ProgressBar value={job.progress_percentage} />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2 text-xs text-gray-600">
              <div>
                <div className="text-gray-500">Job ID</div>
                <div className="truncate" title={job.job_id}>{job.job_id}</div>
              </div>
              <div>
                <div className="text-gray-500">Post GUID</div>
                <div className="truncate" title={job.post_guid}>{job.post_guid}</div>
              </div>
              <div>
                <div className="text-gray-500">Created</div>
                <div>{job.created_at ? formatDateTime(job.created_at) : '—'}</div>
              </div>
              <div>
                <div className="text-gray-500">Started</div>
                <div>{job.started_at ? formatDateTime(job.started_at) : '—'}</div>
              </div>
              {job.error_message ? (
                <div className="col-span-2">
                  <div className="text-gray-500">Message</div>
                  <div className="text-red-700 truncate" title={job.error_message}>{job.error_message}</div>
                </div>
              ) : null}
            </div>

            {(job.status === 'pending' || job.status === 'running') && (
              <div className="mt-3 pt-3 border-t border-gray-200">
                <button
                  onClick={() => { void cancelJob(job.job_id); }}
                  disabled={cancellingJobs.has(job.job_id)}
                  className="w-full inline-flex items-center justify-center rounded-md bg-red-600 px-3 py-2 text-sm font-medium text-white hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 disabled:bg-gray-400 disabled:cursor-not-allowed"
                >
                  {cancellingJobs.has(job.job_id) ? 'Cancelling...' : 'Cancel Job'}
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

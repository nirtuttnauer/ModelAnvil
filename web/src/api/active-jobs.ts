import { apiPage } from './client.ts';
import { allResources } from './resources.ts';

export interface ActiveJob {
  job_id: string; name: string; status: string; desired_action: string; created_at: string;
  payload?: { type?: string }; progress: number | null;
}

export function activeJobDisplayName(name: string) {
  const managed = name.match(/^(?:full_sft|lora_adapter|scratch_pretraining): ([0-9a-f]{8})-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);
  return managed ? `Model training · ${managed[1]}` : name || 'Untitled job';
}

export async function loadActiveJobs(token: string, signal?: AbortSignal): Promise<ActiveJob[]> {
  const jobs = (await allResources<Omit<ActiveJob, 'progress'>>('/api/v1/jobs/', token, signal))
    .filter(job => job.status === 'running' || job.status === 'queued')
    .sort((a, b) => Number(b.status === 'running') - Number(a.status === 'running') || Date.parse(a.created_at) - Date.parse(b.created_at));
  return Promise.all(jobs.map(async job => {
    if (job.status !== 'running') return { ...job, progress: null };
    try {
      const page = await apiPage<{ job_id: string; progress: number; status: string }>(`/api/v1/job-attempts/?job_id=${encodeURIComponent(job.job_id)}`, token, signal);
      const attempt = page.results.find(value => value.job_id === job.job_id);
      return { ...job, progress: attempt?.status === 'running' && Number.isFinite(attempt.progress) ? Math.round(Math.max(0, Math.min(1, attempt.progress)) * 100) : null };
    } catch (error) {
      if (signal?.aborted) throw error;
      return { ...job, progress: null };
    }
  }));
}

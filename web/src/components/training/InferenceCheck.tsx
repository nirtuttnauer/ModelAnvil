import { useState } from 'react';
import { Play, RefreshCw } from 'lucide-react';
import { Button, Field, KeyValueList, Notice, StatusBadge } from '../ui';
import { Identifier } from '../Identifier';
import { apiRequest, errorMessage } from '../../api/client';
import type { InferResult } from '../../api/training';

/** Load exported weights in the server CPU runtime and decode a short completion. */
export function InferenceCheck({ runId, token, enabled }: { runId: string; token: string; enabled: boolean }) {
  const [prompt, setPrompt] = useState('ModelAnvil text fine-tuning candidate evaluation');
  const [maxTokens, setMaxTokens] = useState('8');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<InferResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function run() {
    setBusy(true); setError(null); setResult(null);
    try { setResult(await apiRequest<InferResult>(`/api/v1/training-runs/${runId}/infer/`, token, { method: 'POST', body: JSON.stringify({ prompt, max_tokens: Number(maxTokens) }) })); }
    catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  return <div className="training-inference">
    <p className="muted">Decodes with the exported weights in the server CPU runtime. GPU inference runs on the worker host.</p>
    <div className="training-inference-controls">
      <Field type="text" aria-label="Inference test prompt" placeholder="Enter test prompt…" value={prompt} onChange={e => setPrompt(e.target.value)} />
      <Field type="number" min="1" max="32" aria-label="Maximum generated tokens" value={maxTokens} onChange={e => setMaxTokens(e.target.value)} />
      <Button type="button" variant="secondary" disabled={busy || !prompt.trim() || !enabled} onClick={() => void run()}>{busy ? <RefreshCw size={14} aria-hidden="true" /> : <Play size={14} aria-hidden="true" />} Run inference</Button>
    </div>
    {error && <Notice tone="error" role="alert">{error}</Notice>}
    {result && <div className="training-inference-result">
      <div data-ui="actions"><StatusBadge status={result.verification.is_loadable ? 'passed' : 'failed'} label={`CPU load ${result.verification.is_loadable ? 'passed' : 'failed'}`} /><span className="muted">{result.verification.format} · {result.verification.num_tensors} tensors · independent runtime unverified</span></div>
      <KeyValueList items={[
        { label: 'Weights SHA-256', value: <Identifier value={result.verification.weights_sha256} label="Verified weights SHA-256" display="code" /> },
        { label: 'Prompt', value: <code>{result.inference.prompt}</code> },
        { label: 'Completion', value: <code>{result.inference.completion}</code> },
      ]} />
    </div>}
  </div>;
}

import { Fragment, useEffect, useRef, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { Button, Notice, Select, TextControl } from './ui';
import { Identifier } from './Identifier';

type Revision = { id: number; revision_id: string; dataset_name?: string; revision_no: number; metadata?: { preparation_kind?: string } };
type Corpus = { id: number; revision_id: string; manifest_digest: string; split_counts: Record<string, number> };

export function ContinuedCorpusBuilder({ token, revisions, onPublished }: { token: string; revisions: Revision[]; onPublished: (id: number) => void }) {
  const [name, setName] = useState('');
  const [seed, setSeed] = useState('0');
  const [count, setCount] = useState('12');
  const [components, setComponents] = useState([{ revision_id: '', weight: '1' }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [published, setPublished] = useState<Corpus | null>(null);
  const generation = useRef(0);
  useEffect(() => { generation.current += 1; setBusy(false); setError(''); setPublished(null); }, [token]);
  useEffect(() => () => { generation.current += 1; }, []);
  const sources = revisions.filter(revision => revision.metadata?.preparation_kind !== 'modelanvil.continued-corpus.v1');
  function change(index: number, field: 'revision_id' | 'weight', value: string) {
    setComponents(current => current.map((row, i) => i === index ? { ...row, [field]: value } : row));
  }
  async function publish() {
    const request = ++generation.current;
    setBusy(true); setError(''); setPublished(null);
    try {
      const result = await apiRequest<Corpus>('/api/v1/pretraining-corpora/', token, { method: 'POST', body: JSON.stringify({ name, components, train_samples: Number(count), seed }) });
      if (request === generation.current) { setPublished(result); onPublished(result.id); }
    } catch (e) { if (request === generation.current) setError(errorMessage(e)); }
    finally { if (request === generation.current) setBusy(false); }
  }
  const invalid = !token || !name.trim() || !seed.trim() || !Number.isInteger(Number(count)) || Number(count) < 1 || Number(count) > 1000 || components.some(row => !row.revision_id || !Number.isFinite(Number(row.weight)) || Number(row.weight) <= 0);
  return <div data-ui="form">
    <p className="muted">Combine up to four prepared source revisions. Original validation and test splits stay protected. Training rows are selected once using your weights and seed, then keep the same order.</p>
    <div data-ui="field-grid">
      <TextControl label="Corpus name" value={name} maxLength={180} disabled={busy} onChange={event => setName(event.target.value)} />
      <TextControl label="Training rows" type="number" min="1" max="1000" value={count} disabled={busy} onChange={event => setCount(event.target.value)} />
      <TextControl label="Selection seed" value={seed} maxLength={128} disabled={busy} onChange={event => setSeed(event.target.value)} />
      {components.map((component, index) => <Fragment key={index}>
        <Select label={`Source revision ${index + 1}`} value={component.revision_id} disabled={busy} onChange={event => change(index, 'revision_id', event.target.value)}>
          <option value="">Select a prepared text source</option>
          {sources.map(revision => <option key={revision.revision_id} value={revision.revision_id} disabled={components.some((row, i) => i !== index && row.revision_id === revision.revision_id)}>{revision.dataset_name || 'Dataset'} · r{revision.revision_no}</option>)}
        </Select>
        <TextControl label={`Relative weight ${index + 1}`} type="number" min="0.001" max="1000" step="0.001" value={component.weight} disabled={busy} onChange={event => change(index, 'weight', event.target.value)} />
      </Fragment>)}
    </div>
    <div data-ui="actions">
      <Button type="button" disabled={busy || components.length >= 4} onClick={() => setComponents(current => [...current, { revision_id: '', weight: '1' }])}>Add source</Button>
      <Button type="button" disabled={busy || components.length <= 1} onClick={() => setComponents(current => current.slice(0, -1))}>Remove last source</Button>
      <Button type="button" variant="primary" disabled={busy || invalid} onClick={() => void publish()}>{busy ? 'Publishing corpus…' : 'Publish and select corpus'}</Button>
    </div>
    <p className="muted">Each source must have enough training rows for its weight. Overlapping content or source groups across protected splits are refused. Publishing saves a new corpus revision; training starts after a separate preflight review.</p>
    {error && <Notice tone="error" role="alert">{error}</Notice>}
    {published && <Notice tone="success" role="status">Corpus selected: {published.split_counts.train} training, {published.split_counts.validation} validation and {published.split_counts.test} test rows. <Identifier value={published.manifest_digest} label="Corpus manifest digest" /></Notice>}
  </div>;
}

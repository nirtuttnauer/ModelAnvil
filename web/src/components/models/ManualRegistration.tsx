import { useId, useState } from 'react';
import { Button, Disclosure, MultilineField, Select, TextControl } from '../ui';
import { apiRequest, errorMessage } from '../../api/client';
import { parseTasks, type ModelVersion } from '../../api/models';
import { ModelCapabilities } from '../ModelCapabilities';

type Form = 'model' | 'cpu' | null;

/** Hand registration and the untrained CPU base, folded away under "Advanced". */
export function ManualRegistration({ token, versions, onRegistered, onRegisterTokenizer, onRegisterModelVersion }: {
  token: string; versions: ModelVersion[]; onRegistered(message: string): void; onRegisterTokenizer(): void; onRegisterModelVersion(): void;
}) {
  const descriptionId = useId();
  const [form, setForm] = useState<Form>(null);
  const [name, setName] = useState('');
  const [tasks, setTasks] = useState('text_generation, reasoning');
  const [description, setDescription] = useState('');
  const [cpuName, setCpuName] = useState('');
  const [cpuSeed, setCpuSeed] = useState('42');
  const [cpuProfile, setCpuProfile] = useState('cpu-character');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const ready = !!token.trim() && !submitting;
  function toggle(next: Form) { setForm(current => current === next ? null : next); setError(''); }
  async function registerModel(event: React.FormEvent) {
    event.preventDefault(); setSubmitting(true); setError('');
    try {
      await apiRequest('/api/v1/models/', token, { method: 'POST', body: JSON.stringify({ name: name.trim(), description: description.trim(), intended_tasks: parseTasks(tasks) }) });
      onRegistered(`Model “${name.trim()}” registered.`); setForm(null); setName(''); setDescription('');
    } catch (e) { setError(errorMessage(e)); } finally { setSubmitting(false); }
  }
  async function initializeCpu(event: React.FormEvent) {
    event.preventDefault(); setSubmitting(true); setError('');
    try {
      const initialized = await apiRequest<{ execution_evidence?: { level: string } }>('/api/v1/model-versions/initialize-cpu/', token, { method: 'POST', body: JSON.stringify({ name: cpuName.trim(), seed: Number(cpuSeed), profile: cpuProfile }) });
      onRegistered(initialized.execution_evidence?.level === 'fixture' ? `Demo CPU base “${cpuName.trim()}” registered in this Storybook session.` : `Untrained CPU base “${cpuName.trim()}” initialized with real pinned weights and its compatible tokenizer.`);
      setForm(null); setCpuName('');
    } catch (e) { setError(errorMessage(e)); } finally { setSubmitting(false); }
  }
  return <Disclosure summary="Advanced" variant="card" className="models-advanced">
    <p className="muted">Register metadata by hand, or create an untrained CPU base for local experiments.</p>
    <div data-ui="actions">
      <Button type="button" disabled={!ready} aria-expanded={form === 'model'} onClick={() => toggle('model')}>Register model</Button>
      <Button type="button" disabled={!ready} onClick={onRegisterTokenizer}>Register tokenizer</Button>
      <Button type="button" disabled={!ready} onClick={onRegisterModelVersion}>Register model version</Button>
      <Button type="button" disabled={!ready} aria-expanded={form === 'cpu'} onClick={() => toggle('cpu')}>Initialize CPU base</Button>
    </div>
    {error && <p className="error-text" role="alert">{error}</p>}
    {form === 'model' && <form data-ui="form" onSubmit={registerModel}>
      <div data-ui="field-grid">
        <TextControl label="Model name" required maxLength={200} value={name} onChange={event => setName(event.target.value)} autoFocus />
        <TextControl label="Intended tasks" hint="Comma-separated, for example text_generation, reasoning." value={tasks} onChange={event => setTasks(event.target.value)} />
        <div data-ui="control" data-span="full"><label data-ui="control-label" htmlFor={descriptionId}>Description</label><MultilineField id={descriptionId} rows={3} value={description} onChange={event => setDescription(event.target.value)} /></div>
      </div>
      <div data-ui="actions">
        <Button variant="primary" disabled={submitting || !name.trim()}>{submitting ? 'Registering…' : 'Save model'}</Button>
        <Button type="button" disabled={submitting} onClick={() => setForm(null)}>Cancel</Button>
      </div>
    </form>}
    {form === 'cpu' && <form data-ui="form" onSubmit={initializeCpu}>
      <div data-ui="field-grid">
        <TextControl label="CPU base model name" required maxLength={180} value={cpuName} onChange={event => setCpuName(event.target.value)} autoFocus />
        <Select label="CPU runtime profile" value={cpuProfile} onChange={event => setCpuProfile(event.target.value)}
          options={[{ value: 'cpu-character', label: 'CPU character SFT' }, { value: 'cpu-transformer', label: 'Small CPU transformer SFT' }]} />
        <TextControl label="Initialization seed" required type="number" min="0" max="2147483647" value={cpuSeed} onChange={event => setCpuSeed(event.target.value)} />
      </div>
      <p className="muted">Creates untrained weights and a matching character or byte tokenizer for a bounded CPU run.</p>
      <div data-ui="actions">
        <Button variant="primary" disabled={submitting || !cpuName.trim()}>{submitting ? 'Initializing…' : 'Create pinned CPU base'}</Button>
        <Button type="button" disabled={submitting} onClick={() => setForm(null)}>Cancel</Button>
      </div>
    </form>}
    <Disclosure summary="Model runtime compatibility" variant="quiet"><ModelCapabilities versions={versions} /></Disclosure>
  </Disclosure>;
}

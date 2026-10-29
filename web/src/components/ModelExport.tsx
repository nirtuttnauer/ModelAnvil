import { Button } from './ui';
import { useEffect, useRef, useState } from 'react';
import { Download, XCircle } from 'lucide-react';
import { errorMessage } from '../api/client';
import { downloadModelExport, exportBytes, type ExportProgress, type ModelExportOption } from '../api/model-export';
import './model-export.css';

export function ModelExport({ runId, options, token, checkpointStep, synthetic = false, evaluationRun }: {
  runId: string; options: ModelExportOption[]; token: string; checkpointStep?: number; synthetic?: boolean; evaluationRun?: string;
}) {
  const [format, setFormat] = useState(options[0]?.format || 'json');
  const choice = options.find(option => option.format === format) || options[0];
  const [progress, setProgress] = useState<ExportProgress | null>(null);
  const [error, setError] = useState(''), [notice, setNotice] = useState('');
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => { request.current?.abort(); request.current = null; }, [runId, token]);
  const busy = progress !== null && progress.phase !== 'complete';
  const percent = progress?.total ? Math.min(progress.phase === 'complete' ? 100 : 99, Math.floor(progress.received / progress.total * 100)) : null;
  async function download() {
    if (!choice || request.current) return;
    const controller = new AbortController(); request.current = controller; setError(''); setNotice('');
    try {
      const saved = await downloadModelExport(runId, choice, token, controller.signal, value => { if (request.current === controller) setProgress(value); }, evaluationRun);
      if (request.current === controller) setNotice(saved === 'saved' ? 'Export saved to your chosen file.' : 'Export transferred. Check your browser’s downloads to finish saving.');
    } catch (e) {
      if (request.current !== controller) return;
      setProgress(null);
      if (controller.signal.aborted || e instanceof DOMException && e.name === 'AbortError') setNotice('Download cancelled. You can start again.');
      else setError(errorMessage(e));
    } finally { if (request.current === controller) request.current = null; }
  }
  return <section className="model-export" aria-label="Model export">
    <header><Download size={20} aria-hidden="true" /><div><h2>Export your trained model</h2><p>{checkpointStep == null ? 'Download the selected candidate checkpoint.' : `Exports selected candidate checkpoint · step ${checkpointStep}.`}</p></div></header>
    {synthetic && <p className="muted">This is a synthetic run. Its reference export is fixture data.</p>}
    <div className="model-export-controls"><label>Export format<select value={choice?.format || ''} disabled={busy || !options.length} onChange={event => { setFormat(event.target.value as ModelExportOption['format']); setProgress(null); setError(''); setNotice(''); }}>{options.length ? options.map(option => <option key={option.format} value={option.format}>{option.label}</option>) : <option value="">No supported formats reported</option>}</select></label>
      <Button className="primary" type="button" disabled={busy || !choice} onClick={() => void download()}><Download size={16} aria-hidden="true" />{busy ? 'Exporting…' : error ? 'Retry export' : 'Download export'}</Button>
      {busy && <Button type="button" onClick={() => request.current?.abort()}><XCircle size={16} aria-hidden="true" />Cancel download</Button>}
    </div>
    {choice && <p>{choice.description}</p>}
    {evaluationRun && <p>The bundle includes this comparison, its recorded decision, checksums and loading instructions.</p>}
    <p className="muted">GGUF conversion and merging adapter weights are not available here.</p>
    {progress && <div className="model-export-progress">
      <p role="status">{progress.phase === 'choosing' ? 'Choose where to save your export…' : progress.phase === 'preparing' ? 'Preparing and verifying export files…' : progress.phase === 'complete' ? 'Transfer complete' : `Downloading${percent === null ? '' : ` · ${percent}%`}`}</p>
      {progress.phase !== 'choosing' && <progress aria-label="Model export download" {...(progress.phase === 'complete' ? { value: 100, max: 100 } : percent === null ? {} : { value: percent, max: 100 })} />}
      {(progress.phase === 'downloading' || progress.phase === 'complete') && <span>{exportBytes(progress.received)} received{progress.total === null ? ' · total size not reported' : ` / ${exportBytes(progress.total)}`}</span>}
    </div>}
    {error && <p className="error-text" role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
  </section>;
}

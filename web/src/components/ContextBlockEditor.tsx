import { MultilineField } from './ui';
import { useId } from 'react';
import { dataLabel, TextContent } from './DataInspector';
import { ObjectFields } from './FormEditors';
import { readFieldState, writeFieldState, type FieldState } from './form-data';
import './workbench-components.css';

export interface ContextBlock {
  key: string; label?: string; content: string; role?: string; essential?: boolean;
  status?: 'Included' | 'Omitted' | 'Saved template'; tokenCount?: number;
  override?: boolean;
}
export function ContextBlockEditor({ blocks, onChange, onOverride, disabled, title = 'Context blocks' }: {
  blocks: ContextBlock[]; onChange?: (key: string, content: string) => void; disabled?: boolean; title?: string;
  onOverride?: (key: string, enabled: boolean) => void;
}) {
  const id = useId();
  return <fieldset className="context-block-editor full-width" disabled={disabled}><legend>{title}</legend>
    {!blocks.length && <p className="wb-empty">No context blocks recorded.</p>}
    <div className="context-editor-grid">{blocks.map((block, index) => <section className={`context-editor-card ${block.status === 'Omitted' ? 'context-omitted' : ''}`} key={block.key} aria-label={`${block.label || dataLabel(block.key)} block`}>
      <div className="wb-row"><strong>{block.label || dataLabel(block.key)}</strong>{block.status && <span className="wb-status">{block.status}</span>}</div>
      <p className="wb-muted">{block.role && <>Role: {block.role} · </>}{block.essential == null ? 'Retention priority not reported' : block.essential ? 'Essential · retained on overflow' : 'Optional · eligible for omission on overflow'}</p>
      {onOverride && <label className="checkbox-label"><input type="checkbox" checked={!!block.override} onChange={e => onOverride(block.key, e.target.checked)} />Override {block.label || dataLabel(block.key)}</label>}
      {onChange ? <><label htmlFor={`${id}-${index}`}>{block.label || dataLabel(block.key)}{onOverride ? ' override' : ''}</label><MultilineField id={`${id}-${index}`} aria-label={`${block.label || dataLabel(block.key)}${onOverride ? ' override' : ''}`} rows={4} disabled={onOverride && !block.override} required={!onOverride && block.essential} value={block.content} onChange={e => onChange(block.key, e.target.value)} /></> : <TextContent text={block.content} />}
      {block.tokenCount != null && <p className="wb-muted wb-number">Estimated tokens: {block.tokenCount.toLocaleString()}</p>}
      {block.status === 'Omitted' && <p className="wb-warning">This block was omitted by the compiler.</p>}
    </section>)}</div>
  </fieldset>;
}

export function ContextBlockInputs({ blocks, value, onChange, disabled }: { blocks: ContextBlock[]; value: string; onChange(value: string): void; disabled?: boolean }) {
  let state: FieldState;
  try { state = readFieldState(value); } catch { return <ObjectFields title="Runtime block inputs" value={value} disabled={disabled} onChange={onChange} />; }
  const unsupported = state.fields.some(field => blocks.some(block => block.key === field.name) && field.kind !== 'text');
  function setOverride(key: string, text?: string) {
    const fields = state.fields.filter(field => field.name !== key);
    if (text !== undefined) fields.push({ id: crypto.randomUUID(), name: key, kind: 'text', text, children: [] });
    onChange(writeFieldState({ ...state, fields }));
  }
  return <div className="full-width">
    {unsupported ? <p className="wb-warning">A saved block override uses a structured value. Edit it in the runtime inputs below; its value is retained.</p> : <ContextBlockEditor title="Runtime block overrides" disabled={disabled}
      blocks={blocks.map(block => { const field = state.fields.find(field => field.name === block.key); return { ...block, override: !!field, content: field?.text ?? block.content }; })}
      onOverride={(key, enabled) => setOverride(key, enabled ? blocks.find(block => block.key === key)?.content || '' : undefined)}
      onChange={(key, text) => setOverride(key, text)} />}
    <details open={unsupported || undefined}><summary>Additional or structured runtime inputs</summary><ObjectFields title="Runtime block inputs" description="Saved extra fields and structured overrides remain editable here." value={value} disabled={disabled} nameLabel="Block key" valueLabel="Block content" suggestions={blocks.map(block => block.key)} onChange={onChange} /></details>
  </div>;
}

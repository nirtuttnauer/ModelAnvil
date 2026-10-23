import { Button, Field, MultilineField } from './ui';
import { useEffect, useId, useRef, useState, type InputHTMLAttributes } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { dataLabel } from './DataInspector';
import { readFieldState, readRecords, writeFieldState, type FieldNode, type FieldState, type FormField } from './form-data';
import './form-editors.css';

function FormInput({ label, multiline, error, help, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string; multiline?: boolean; error?: string; help?: string }) {
  const id = useId();
  const ref = useRef<HTMLInputElement | HTMLTextAreaElement>(null);
  const [blurred, setBlurred] = useState(false);
  const [nativeError, setNativeError] = useState('');
  useEffect(() => { ref.current?.setCustomValidity(error || ''); if (blurred) setNativeError(ref.current?.validationMessage || ''); }, [error, props.value, blurred]);
  const message = error || (blurred ? nativeError : '');
  const common = { id, 'aria-label': label, 'aria-describedby': `${id}-hint`, 'aria-invalid': message ? true : undefined, onBlur: () => { setBlurred(true); setNativeError(ref.current?.validationMessage || ''); } };
  return <label className={`editor-input ${multiline ? 'editor-wide' : ''}`} htmlFor={id}><span>{label}{props.required && <span className="editor-required" aria-hidden="true"> *</span>}</span>
    {multiline ? <MultilineField {...props as React.TextareaHTMLAttributes<HTMLTextAreaElement>} {...common} ref={el => { ref.current = el; }} rows={3} /> : <Field {...props} {...common} ref={el => { ref.current = el; }} />}
    <small id={`${id}-hint`} className={message ? 'editor-error' : 'editor-help'}>{message || help}</small>
  </label>;
}

function RestoreError({ onReset }: { onReset(): void }) {
  return <div className="editor-restore-error" role="alert"><p>Saved fields could not be restored. Your saved text is retained until you clear it.</p><Button type="button" onClick={onReset}>Clear saved fields</Button></div>;
}

const typeNames = { text: 'Text', number: 'Number', boolean: 'Yes / No', empty: 'No value', object: 'Field group', array: 'List' };
function newField(name = ''): FieldNode { return { id: crypto.randomUUID(), name, kind: 'text', text: '', children: [] }; }

function Fields({ state, onChange, textOnly, nameLabel, valueLabel, suggestions, defaultKind = 'text' }: {
  state: FieldState; onChange(state: FieldState): void; textOnly?: boolean; nameLabel: string; valueLabel: string; suggestions?: string[]; defaultKind?: FieldNode['kind'];
}) {
  const listId = useId();
  function update(index: number, changes: Partial<FieldNode>) { onChange({ ...state, fields: state.fields.map((field, i) => i === index ? { ...field, ...changes } : field) }); }
  return <div className="editor-field-list">
    {suggestions?.length ? <datalist id={listId}>{suggestions.map(name => <option key={name} value={name}>{dataLabel(name)}</option>)}</datalist> : null}
    {state.fields.map((field, index) => <div className="editor-field-row" key={field.id}>
      <div className="editor-field-controls">
        {state.kind === 'object' ? <FormInput label={nameLabel} required value={field.name} list={listId} error={field.name && state.fields.some((other, i) => i !== index && other.name === field.name) ? 'Choose a unique field name.' : undefined} onChange={e => update(index, { name: e.target.value })} /> : <strong className="editor-item-label">Item {index + 1}</strong>}
        {!textOnly && <label className="editor-input"><span>Value type</span><select value={field.kind} onChange={e => update(index, { kind: e.target.value as FieldNode['kind'], text: e.target.value === 'boolean' ? 'false' : field.text })}>{Object.entries(typeNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>}
        <Button className="editor-remove" type="button" aria-label={`Remove ${state.kind === 'object' ? field.name || 'field ' + (index + 1) : 'item ' + (index + 1)}`} onClick={() => onChange({ ...state, fields: state.fields.filter((_, i) => i !== index) })}><Trash2 size={16} aria-hidden="true" /></Button>
      </div>
      {(field.kind === 'object' || field.kind === 'array') ? <div className="editor-nested"><Fields state={{ kind: field.kind, fields: field.children }} onChange={next => update(index, { children: next.fields })} nameLabel="Field name" valueLabel="Value" /></div>
        : field.kind === 'boolean' ? <label className="editor-input"><span>{valueLabel}</span><select value={field.text} onChange={e => update(index, { text: e.target.value })}><option value="true">Yes</option><option value="false">No</option></select></label>
        : field.kind === 'empty' ? <p className="editor-help">The field is included with no value.</p>
        : <FormInput label={valueLabel} multiline={field.kind === 'text'} type={field.kind === 'number' ? 'number' : 'text'} step="any" required={field.kind === 'number'} value={field.text} onChange={e => update(index, { text: e.target.value })} />}
    </div>)}
    {!state.fields.length && <p className="editor-empty">{state.kind === 'array' ? 'No items added yet.' : 'No custom fields. Saved or default values will be used where available.'}</p>}
    <Button className="editor-add" type="button" onClick={() => onChange({ ...state, fields: [...state.fields, { ...newField(), kind: defaultKind }] })}><Plus size={16} aria-hidden="true" />{state.kind === 'array' ? 'Add item' : 'Add field'}</Button>
  </div>;
}

export function ObjectFields({ value, onChange, title, description, disabled, textOnly, nameLabel = 'Field name', valueLabel = 'Value', suggestions, rootKind = 'object', defaultKind }: {
  value: string; onChange(value: string): void; title: string; description?: string; disabled?: boolean;
  textOnly?: boolean; nameLabel?: string; valueLabel?: string; suggestions?: string[]; rootKind?: 'object' | 'array'; defaultKind?: FieldNode['kind'];
}) {
  let state: FieldState;
  try { state = readFieldState(value, rootKind); } catch { return <fieldset className="structured-form full-width" disabled={disabled}><legend>{title}</legend><RestoreError onReset={() => onChange(rootKind === 'array' ? '[]' : '{}')} /></fieldset>; }
  return <fieldset className="structured-form full-width" disabled={disabled}><legend>{title}</legend>{description && <p className="editor-help">{description}</p>}
    <Fields state={state} onChange={next => onChange(writeFieldState(next))} textOnly={textOnly} nameLabel={nameLabel} valueLabel={valueLabel} suggestions={suggestions} defaultKind={defaultKind} />
  </fieldset>;
}

export function ConfigFields({ value, onChange, fields, title, disabled }: { value: string; onChange(value: string): void; fields: FormField[]; title: string; disabled?: boolean }) {
  let state: FieldState;
  try { state = readFieldState(value); if (state.kind !== 'object') throw new Error(); } catch { return <fieldset className="structured-form full-width" disabled={disabled}><legend>{title}</legend><RestoreError onReset={() => onChange('{}')} /></fieldset>; }
  const extra = state.fields.filter(node => !fields.some(field => field.key === node.name) && node.name !== 'budget_policy_id');
  return <fieldset className="structured-form full-width" disabled={disabled}><legend>{title}</legend><div className="editor-grid">
    {fields.map(field => {
      const existing = state.fields.find(node => node.name === field.key);
      return <FormInput key={field.key} label={field.label} type={field.kind === 'number' ? 'number' : 'text'} step={field.step ?? 'any'} min={field.min} max={field.max} value={existing?.text ?? ''} placeholder={field.defaultValue} required={field.required} help={field.help || (field.defaultValue ? `Default: ${field.defaultValue}. Leave blank to use it.` : undefined)} onChange={e => {
        const remaining = state.fields.filter(node => node.name !== field.key);
        onChange(writeFieldState({ ...state, fields: e.target.value === '' ? remaining : [...remaining, { ...(existing || newField(field.key)), kind: field.kind === 'number' ? 'number' : 'text', text: e.target.value }] }));
      }} />;
    })}
  </div>{extra.length > 0 && <div className="editor-nested"><p className="editor-help">Additional saved settings. Remove incompatible settings before submitting.</p><Fields state={{ kind: 'object', fields: extra }} onChange={next => onChange(writeFieldState({ ...state, fields: [...state.fields.filter(node => !extra.includes(node)), ...next.fields] }))} nameLabel="Setting name" valueLabel="Value" /></div>}</fieldset>;
}

export function VerifierFields({ value, onChange, disabled, allowSubstring = true }: { value: string; onChange(value: string): void; disabled?: boolean; allowSubstring?: boolean }) {
  let state: FieldState;
  try { state = readFieldState(value); if (state.kind !== 'object') throw new Error(); } catch { return <ObjectFields title="Verifier settings" value={value} onChange={onChange} disabled={disabled} />; }
  const type = state.fields.find(field => field.name === 'type')?.text || 'exact_match';
  const tolerance = state.fields.find(field => field.name === 'tolerance');
  const extra = state.fields.filter(field => !['type', 'tolerance'].includes(field.name));
  return <fieldset className="structured-form full-width" disabled={disabled}><legend>Verifier settings</legend><div className="editor-grid">
    <label className="editor-input"><span>Verification method</span><select value={type} onChange={e => onChange(writeFieldState({ ...state, fields: [...state.fields.filter(field => field.name !== 'type'), { ...newField('type'), text: e.target.value }] }))}><option value="exact_match">Exact match</option>{allowSubstring && <option value="substring">Expected text appears in the response</option>}<option value="numeric_tolerance">Numeric tolerance</option>{!['exact_match', ...(allowSubstring ? ['substring'] : []), 'numeric_tolerance'].includes(type) && <option value={type}>Unsupported saved method: {type}</option>}</select></label>
    <FormInput label="Numeric tolerance" type="number" min={0} max={1000000} step="any" value={tolerance?.text || ''} placeholder="0.0001" help="Used for numeric scoring. Leave blank to use 0.0001." onChange={e => onChange(writeFieldState({ ...state, fields: [...state.fields.filter(field => field.name !== 'tolerance'), ...(e.target.value === '' ? [] : [{ ...newField('tolerance'), kind: 'number' as const, text: e.target.value }])] }))} />
  </div>{extra.length > 0 && <div className="editor-nested"><p className="editor-help">Remove unsupported saved verifier fields before submitting.</p><Fields state={{ kind: 'object', fields: extra }} onChange={next => onChange(writeFieldState({ ...state, fields: [...state.fields.filter(field => !extra.includes(field)), ...next.fields] }))} nameLabel="Setting name" valueLabel="Value" /></div>}</fieldset>;
}

export function RecordListEditor({ value, onChange, fields, title, itemName, maximum = Infinity, uniqueKey, disabled, description }: {
  value: string; onChange(value: string): void; fields: FormField[]; title: string; itemName: string;
  maximum?: number; uniqueKey?: string; disabled?: boolean; description?: string;
}) {
  let rows: Record<string, unknown>[];
  try { rows = readRecords(value); } catch { return <fieldset className="structured-form full-width" disabled={disabled}><legend>{title}</legend><RestoreError onReset={() => onChange('[]')} /></fieldset>; }
  function change(index: number, key: string, next: unknown) {
    onChange(JSON.stringify(rows.map((row, i) => {
      if (i !== index) return row;
      const updated = { ...row, [key]: next };
      if (next === '' && !fields.find(field => field.key === key)?.required) delete updated[key];
      return updated;
    })));
  }
  return <fieldset className="structured-form full-width" disabled={disabled}><legend>{title} <span className="editor-count">{rows.length}{Number.isFinite(maximum) ? ` / ${maximum}` : ' added'}</span></legend>{description && <p className="editor-help">{description}</p>}
    <div className="editor-record-list">{rows.map((row, index) => <fieldset className="editor-record" key={index}><legend>{itemName} {index + 1}</legend>
      <div className="editor-record-heading"><span className="editor-help">{uniqueKey ? String(row[uniqueKey] || 'New record') : `${itemName} ${index + 1}`}</span><Button type="button" className="editor-remove" aria-label={`Remove ${itemName.toLowerCase()} ${index + 1}`} onClick={() => onChange(JSON.stringify(rows.filter((_, i) => i !== index)))}><Trash2 size={16} aria-hidden="true" /></Button></div>
      <div className="editor-grid">{fields.map(field => {
        const current = row[field.key];
        if (field.kind === 'object') return current === undefined ? <Button key={field.key} type="button" className="editor-add" onClick={() => change(index, field.key, '{}')}>Add {field.label.toLowerCase()}</Button> : <ObjectFields key={field.key} title={field.label} value={typeof current === 'string' ? current : JSON.stringify(current)} onChange={next => change(index, field.key, next)} />;
        return <FormInput key={field.key} label={field.label} multiline={field.multiline} required={field.required && !field.allowEmpty} maxLength={field.maxLength} type={field.kind === 'number' ? 'number' : 'text'} min={field.min} max={field.max} step={field.step ?? 'any'} help={field.help} value={current === undefined ? '' : String(current)} error={field.key === uniqueKey && current && rows.some((other, i) => i !== index && other[field.key] === current) ? 'Choose a unique ID.' : undefined} onChange={e => change(index, field.key, e.target.value)} />;
      })}</div>
    </fieldset>)}</div>
    {!rows.length && <p className="editor-empty">Add your first {itemName.toLowerCase()} to get started.</p>}
    <Button className="editor-add" type="button" disabled={rows.length >= maximum} onClick={() => {
      const next: Record<string, unknown> = Object.fromEntries(fields.filter(field => field.defaultValue !== undefined).map(field => [field.key, field.defaultValue]));
      if (uniqueKey) { let number = rows.length + 1; while (rows.some(row => row[uniqueKey] === `${itemName.toLowerCase().replaceAll(' ', '-')}-${number}`)) number++; next[uniqueKey] = `${itemName.toLowerCase().replaceAll(' ', '-')}-${number}`; }
      onChange(JSON.stringify([...rows, next]));
    }}><Plus size={16} aria-hidden="true" />Add {itemName.toLowerCase()}</Button>
  </fieldset>;
}

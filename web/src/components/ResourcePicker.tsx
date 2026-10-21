import { Identifier } from './Identifier';
import { Field } from './ui';
import { useEffect, useId, useRef, useState } from 'react';
import { Search } from 'lucide-react';
import './workbench-components.css';

export interface ResourceOption {
  value: string; id: string; name: string; revision?: number; state?: string;
  description?: string; unavailable?: string; href?: string;
}

export function VersionChip({ name, revision, id, href, state }: Omit<ResourceOption, 'value'>) {
  return <div className="version-chip">
    <div className="wb-row">{href ? <a href={href}>{name}</a> : <strong>{name}</strong>}{revision != null && <span className="wb-revision">r{revision}</span>}{state && <span className="wb-muted">{state}</span>}<Identifier value={id} label={`ID for ${name}`} /></div>
  </div>;
}

export function ResourcePicker({ label, value, onChange, options, required, disabled, loading = false, placeholder = 'Select an exact revision', action }: {
  label: string; value: string; onChange(value: string): void; options: ResourceOption[];
  required?: boolean; disabled?: boolean; loading?: boolean; placeholder?: string; action?: React.ReactNode;
}) {
  const id = useId(), select = useRef<HTMLSelectElement>(null);
  const [query, setQuery] = useState('');
  const selected = options.find(option => option.value === value);
  const error = !loading && value ? selected?.unavailable || (!selected ? 'This saved resource is unavailable in the loaded inventory. Choose an available revision.' : '') : '';
  useEffect(() => { select.current?.setCustomValidity(error); }, [error]);
  const matches = options.filter(option => `${option.name} ${option.id} ${option.revision != null ? `r${option.revision}` : ''} ${option.description ?? ''}`.toLowerCase().includes(query.toLowerCase().trim()));
  const visible = selected && !matches.includes(selected) ? [selected, ...matches] : matches;
  return <div className="resource-picker">
    <label htmlFor={id}>{label}</label>
    <label className="wb-search"><Search size={16} aria-hidden="true" /><Field type="search" aria-label={`Search ${label.toLowerCase()}`} value={query} disabled={disabled || loading} onChange={e => setQuery(e.target.value)} placeholder="Search name, revision or ID" /></label>
    <div className="wb-row"><select ref={select} id={id} aria-label={label} aria-describedby={`${id}-help`} aria-invalid={error ? true : undefined} required={required} disabled={disabled || loading} value={value} onChange={e => onChange(e.target.value)}>
      <option value="">{placeholder}</option>
      {value && !selected && <option value={value} disabled>{loading ? 'Loading saved resource…' : 'Saved resource unavailable'}</option>}
      {visible.map(option => <option key={option.value} value={option.value} disabled={!!option.unavailable}>{option.name}{option.revision != null ? ` · r${option.revision}` : ''}{option.state ? ` · ${option.state}` : ''}{option.unavailable ? ' · unavailable' : ''}</option>)}
    </select>{action}</div>
    <p className={error ? 'wb-error' : 'wb-muted'} id={`${id}-help`} role={loading ? 'status' : undefined}>{loading ? 'Loading resources… Your saved selection is retained.' : error || (query ? `${matches.length} matching resources. Your selection is retained while searching.` : `${options.length} resources in the loaded inventory.`)}</p>
    {selected && <><VersionChip {...selected} />{selected.description && <p className="wb-muted">{selected.description}</p>}</>}
    {!!matches.filter(option => option.unavailable).length && <details><summary>Unavailable choices and reasons</summary><ul>{matches.filter(option => option.unavailable).map(option => <li key={option.value}><strong>{option.name}{option.revision != null ? ` · r${option.revision}` : ''}</strong>: {option.unavailable}</li>)}</ul></details>}
  </div>;
}

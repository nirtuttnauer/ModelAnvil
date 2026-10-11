import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, Search, X } from 'lucide-react';

export function WorkspaceSearch({ pages, onNavigate }: { pages: string[]; onNavigate: (page: string) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  function openSearch() { setQuery(''); dialog.current?.showModal(); input.current?.focus(); }
  const [query, setQuery] = useState('');
  useEffect(() => {
    function keydown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        openSearch();
      }
    }
    window.addEventListener('keydown', keydown);
    return () => window.removeEventListener('keydown', keydown);
  }, []);
  const matches = pages.filter(p => p.toLowerCase().includes(query.toLowerCase()));
  function choose(page: string) { onNavigate(page); dialog.current?.close(); }
  return <><button type="button" className="workspace-search" aria-label="Search workspace screens (Command or Control K)" onClick={openSearch}><Search size={16} aria-hidden="true" /><span>Go to a workspace screen…</span><kbd>⌘ / Ctrl K</kbd></button>
    <dialog className="workspace-search-dialog" ref={dialog} aria-labelledby="workspace-search-title"><div className="dialog-title"><h2 id="workspace-search-title">Go to a screen</h2><button className="icon-button" aria-label="Close screen search" onClick={() => dialog.current?.close()}><X size={18} /></button></div>
      <label className="search-input"><Search size={18} aria-hidden="true" /><input ref={input} autoFocus aria-label="Find a workspace screen" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search datasets, training, evaluation…" onKeyDown={e => { if (e.key === 'Enter' && matches.length) { e.preventDefault(); choose(matches[0]); } }} /></label>
      <div className="search-results">{matches.map(page => <button type="button" key={page} onClick={() => choose(page)}><span>{page}</span><ArrowUpRight size={15} aria-hidden="true" /></button>)}{!matches.length && <p className="muted">No screen matches “{query}”.</p>}</div><p className="search-hint">Enter opens the first match. Tab moves through the results. Escape closes this window.</p>
    </dialog></>;
}

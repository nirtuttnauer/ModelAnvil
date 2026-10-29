import { Button, Field } from './ui';
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
  return <><Button type="button" className="workspace-search" title="Go to a page (⌘ or Ctrl K)" onClick={openSearch}><Search size={16} aria-hidden="true" /><span>Go to…</span><kbd aria-hidden="true">⌘K</kbd></Button>
    <dialog data-ui="dialog" ref={dialog} aria-labelledby="workspace-search-title">
      <header><div><h2 id="workspace-search-title">Go to a page</h2></div><Button type="button" variant="quiet" icon aria-label="Close page search" onClick={() => dialog.current?.close()}><X size={18} aria-hidden="true" /></Button></header>
      <div data-ui="dialog-body">
        <label className="search-input"><Search size={18} aria-hidden="true" /><Field ref={input} autoFocus aria-label="Find a page" value={query} onChange={e => setQuery(e.target.value)} placeholder="Type a page name" onKeyDown={e => { if (e.key === 'Enter' && matches.length) { e.preventDefault(); choose(matches[0]); } }} /></label>
        <div className="search-results">{matches.map(page => <Button type="button" key={page} onClick={() => choose(page)}><span>{page}</span><ArrowUpRight size={15} aria-hidden="true" /></Button>)}{!matches.length && <p className="muted">No page matches “{query}”.</p>}</div>
        <p className="search-hint">Enter opens the first match. Tab moves through the results. Escape closes this window.</p>
      </div>
    </dialog></>;
}

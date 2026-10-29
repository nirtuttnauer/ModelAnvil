import { useState } from 'react';
import { ArrowRight, Circle, CircleCheck, RefreshCw } from 'lucide-react';
import { Button, Notice } from './ui';
import type { Project } from '../api/resources';
import { setupItems, type SetupItem } from '../api/setup-readiness';
import { useSetupReadiness } from './useSetupReadiness';

/** Setup: every prerequisite on one row, with a single next action. */
export function OnboardingChecklist({ token, refreshKey, activeProject, onNavigate, onOpenConnection, onCreateProject }: {
  token: string; refreshKey: number; activeProject: Project | null;
  onNavigate: (page: string) => void; onOpenConnection: () => void; onCreateProject: () => void;
  onProjectCreated?: (project: Project) => void; onPrerequisiteAdded?: () => void;
}) {
  const { state, loading, error, reload } = useSetupReadiness(token, refreshKey, activeProject);
  const [collapsed, setCollapsed] = useState<boolean>(() => localStorage.getItem('modelanvil_onboarding_collapsed') === 'true');
  const toggle = () => setCollapsed(previous => { const next = !previous; localStorage.setItem('modelanvil_onboarding_collapsed', String(next)); return next; });
  const items = setupItems(state, activeProject, token.trim().length > 0);
  const act = (item: SetupItem) => item.action.kind === 'connection' ? onOpenConnection() : item.action.kind === 'project' ? onCreateProject() : onNavigate(item.action.page ?? 'Training');
  const readyCount = items.filter(item => item.ready).length;
  const next = items.find(item => !item.ready);
  const allReady = !loading && !error && !next;
  return <section data-ui="section" className="setup" aria-labelledby="onboarding-heading">
    <header data-ui="section-header">
      <div><h2 id="onboarding-heading">Setup</h2><p>{loading ? 'Checking your workspace…' : allReady ? 'Everything your first training run needs is in place.' : `${readyCount} of ${items.length} ready.`}</p></div>
      <div data-ui="actions">
        <Button type="button" variant="quiet" icon aria-label="Refresh prerequisites" title="Refresh prerequisites" disabled={loading} onClick={reload}><RefreshCw size={16} aria-hidden="true" /></Button>
        <Button type="button" variant="quiet" onClick={toggle} aria-expanded={!collapsed} aria-controls="onboarding-checklist-body">{collapsed ? 'Show all' : 'Hide details'}</Button>
      </div>
    </header>
    {error && <Notice tone="error" role="alert"><span>{error}</span><Button type="button" onClick={reload}>Retry</Button></Notice>}
    {allReady
      ? <Notice tone="success"><span><strong>Ready to train</strong></span><Button type="button" variant="primary" onClick={() => onNavigate('Training')}>Start training <ArrowRight size={14} aria-hidden="true" /></Button></Notice>
      : !loading && next && <Notice tone="info"><span className="setup-next"><strong>Next action: {next.title}</strong><small>{next.detail}</small></span><Button type="button" variant="primary" onClick={() => act(next)}>{next.action.label} <ArrowRight size={14} aria-hidden="true" /></Button></Notice>}
    {!collapsed && <ul id="onboarding-checklist-body" className="setup-rows" aria-label="Workspace prerequisites">
      {items.map(item => <li key={item.id}>
        {item.ready ? <CircleCheck size={18} aria-hidden="true" className="setup-ready" /> : <Circle size={18} aria-hidden="true" className="setup-missing" />}
        <div><strong>{item.title}</strong><small>{loading ? 'Checking…' : item.detail}</small></div>
        {!loading && !item.ready && item !== next && <Button type="button" variant="quiet" size="sm" onClick={() => act(item)}>{item.action.label}</Button>}
      </li>)}
    </ul>}
  </section>;
}

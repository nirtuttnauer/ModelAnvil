import { Button, Field, NavigationItem, Notice, WorkspaceHeader } from './components/ui';
import { Welcome } from './components/Welcome';
import { parseResourceRoute } from './api/resource-routes';
import { DraftScope } from './components/Draft';
import { ScreenBoundary } from './components/ScreenBoundary';
import React from 'react';
import { createRoot } from 'react-dom/client';
import {
  Activity,
  Bot,
  Building2,
  FolderGit2,
  ChevronRight,
  ArrowUpRight,
  RefreshCw,
  KeyRound,
  Settings2,
  X,
  CircleDollarSign,
  Compass,
  Database,
  FileCode,
  Flame,
  Layers3,
  Library,
  Rocket,
  Workflow,
  Tags,
  CheckCheck,
  Server,
  Scale,
} from 'lucide-react';
import './design-system/tokens.css';
import './style.css';
import './premium.css';
import './workspace-ui.css';
import './design-system/components.css';
import { WorkspaceSearch } from './components/WorkspaceSearch';
import { ActiveJobs } from './components/ActiveJobs';
import { startActivation } from './api/activation';
import { BuildIdentity } from './components/BuildIdentity';
import { ThemeControl } from './components/ThemeControl';
import { apiPage, apiRequest, errorMessage, setActiveProjectId } from './api/client';
import { CreateProjectModal } from './components/PrerequisiteModals';
import { allResources } from './api/resources';
import type { Project } from './api/resources';
import { parseRunRoute } from './api/runs';

const ResourceDetailPage = React.lazy(() => import('./pages/ResourceDetailPage').then(module => ({ default: module.ResourceDetailPage })));
const DatasetsPage = React.lazy(() => import('./pages/DatasetsPage').then(module => ({ default: module.DatasetsPage })));
const DatasetBankPage = React.lazy(() => import('./pages/DatasetBankPage').then(module => ({ default: module.DatasetBankPage })));
const WorkflowsPage = React.lazy(() => import('./pages/WorkflowsPage').then(module => ({ default: module.WorkflowsPage })));
const BudgetsPage = React.lazy(() => import('./pages/BudgetsPage').then(module => ({ default: module.BudgetsPage })));
const ModelsPage = React.lazy(() => import('./pages/ModelsPage').then(module => ({ default: module.ModelsPage })));
const ChatPage = React.lazy(() => import('./pages/ChatPage').then(module => ({ default: module.ChatPage })));
const SpecialistsPage = React.lazy(() => import('./pages/SpecialistsPage').then(module => ({ default: module.SpecialistsPage })));
const RecipesPage = React.lazy(() => import('./pages/RecipesPage').then(module => ({ default: module.RecipesPage })));
const TrainingPage = React.lazy(() => import('./pages/TrainingPage').then(module => ({ default: module.TrainingPage })));
const ClusterExplorerPage = React.lazy(() => import('./pages/ClusterExplorerPage').then(module => ({ default: module.ClusterExplorerPage })));
const ContextLabPage = React.lazy(() => import('./pages/ContextLabPage').then(module => ({ default: module.ContextLabPage })));
const ReleasesPage = React.lazy(() => import('./pages/ReleasesPage').then(module => ({ default: module.ReleasesPage })));
const OverviewPage = React.lazy(() => import('./pages/OverviewPage').then(module => ({ default: module.OverviewPage })));
const AuditPage = React.lazy(() => import('./pages/AuditPage').then(module => ({ default: module.AuditPage })));
const AnnotationPage = React.lazy(() => import('./pages/AnnotationPage').then(module => ({ default: module.AnnotationPage })));
const EvaluationPage = React.lazy(() => import('./pages/EvaluationPage').then(module => ({ default: module.EvaluationPage })));
const AlignmentPage = React.lazy(() => import('./pages/AlignmentPage').then(module => ({ default: module.AlignmentPage })));
const InfrastructurePage = React.lazy(() => import('./pages/InfrastructurePage').then(module => ({ default: module.InfrastructurePage })));
const RunDetailPage = React.lazy(() => import('./pages/RunDetailPage').then(module => ({ default: module.RunDetailPage })));



type Page =
  | 'Overview'
  | 'Dataset Bank'
  | 'Datasets'
  | 'Annotation'
  | 'Evaluation'
  | 'Alignment'
  | 'Infrastructure'
  | 'Models'
  | 'Chat'
  | 'Specialists'
  | 'Recipes'
  | 'Training'
  | 'Workflows'
  | 'RAG'
  | 'Context Lab'
  | 'Releases'
  | 'Budgets'
  | 'Audit'
  | 'Run Detail'
  | 'Resource Detail';

const pages: { name: Page; icon: React.ElementType; endpoint: string; slug?: string }[] = [
  { name: 'Overview', icon: Activity, endpoint: '/api/v1/health/' },
  { name: 'Dataset Bank', icon: Library, endpoint: '/api/v1/dataset-bank/sources/' },
  { name: 'Datasets', icon: Database, endpoint: '/api/v1/datasets/' },
  { name: 'Annotation', icon: Tags, endpoint: '/api/v1/labeling-campaigns/' },
  { name: 'Models', icon: Bot, endpoint: '/api/v1/models/' },
  { name: 'Chat', icon: Bot, endpoint: '/api/v1/inference/models/' },
  { name: 'Specialists', icon: FileCode, endpoint: '/api/v1/specialists/' },
  { name: 'Recipes', icon: Workflow, endpoint: '/api/v1/recipes/' },
  { name: 'Training', icon: Flame, endpoint: '/api/v1/training-runs/' },
  { name: 'Alignment', icon: Scale, endpoint: '/api/v1/alignment-runs/' },
  { name: 'Evaluation', icon: CheckCheck, endpoint: '/api/v1/evaluation-runs/' },
  { name: 'Workflows', icon: Workflow, endpoint: '/api/v1/jobs/' },
  { name: 'RAG', icon: Compass, endpoint: '/api/v1/knowledge-bases/' },
  { name: 'Context Lab', icon: FileCode, endpoint: '/api/v1/context-recipes/' },
  { name: 'Releases', icon: Rocket, endpoint: '/api/v1/serving-endpoints/' },
  { name: 'Infrastructure', icon: Server, endpoint: '/api/v1/worker-pools/' },
  { name: 'Budgets', icon: CircleDollarSign, endpoint: '/api/v1/budget-policies/' },
  { name: 'Audit', icon: Layers3, endpoint: '/api/v1/audit/' },
  // Reached only through a run deep link; it renders in no navigation group.
  { name: 'Resource Detail', icon: Database, endpoint: '/api/v1/model-versions/', slug: 'resources' },
  { name: 'Run Detail', icon: Workflow, endpoint: '/api/v1/jobs/', slug: 'runs' },
];

function slugFor(name: Page): string {
  return pages.find((page) => page.name === name)?.slug ?? name.toLowerCase().replaceAll(' ', '-');
}

const primaryNavigation: { label: string; names: Page[] }[] = [
  { label: 'Workspace', names: ['Overview', 'Training', 'Chat', 'Evaluation', 'Datasets'] },
];
const advancedNavigation: { label: string; names: Page[] }[] = [
  { label: 'Data', names: ['Dataset Bank', 'Annotation', 'Recipes'] },
  { label: 'Develop', names: ['Models', 'Specialists', 'Alignment'] },
  { label: 'Context & release', names: ['RAG', 'Context Lab', 'Releases'] },
  { label: 'Operations', names: ['Workflows', 'Infrastructure', 'Budgets', 'Audit'] },
];
const navigationGroups = [...primaryNavigation, ...advancedNavigation];

const descriptions: Record<Page, string> = {
  Overview: 'Your data, experiments, and next decisions. All in one workspace.',
  'Dataset Bank': 'Find source data and inspect its license and readiness.',
  Datasets: 'Prepare reproducible data, inspect splits, and publish immutable versions.',
  Annotation: 'Review samples, refine labels, and build approved training snapshots.',
  Models: 'Keep model versions and their evaluation evidence together.',
  Chat: 'Run local models, save conversations and compare actual responses.',
  Specialists: 'Read image text and evaluate structured decisions with pinned local models.',
  Recipes: 'Compose typed transformations, preview actual generation and publish recoverable dataset runs.',
  Training: 'Fine-tune a pretrained model with your own examples.',
  Alignment: 'Configure preference learning and inspect recorded outcomes.',
  Evaluation: 'Compare pinned versions, inspect failures, and review the evidence.',
  Workflows: 'Follow execution, inspect attempts, and recover interrupted work.',
  RAG: 'Explore knowledge sources and inspect retrieved evidence.',
  'Context Lab': 'Compile exact inputs and inspect how your token budget is allocated.',
  Releases: 'Inspect release versions, serving endpoints, and software provenance.',
  Infrastructure: 'Inspect worker pools, capabilities, and recorded availability.',
  Budgets: 'Understand measured usage, reservations, and spending policies.',
  Audit: 'Trace changes and inspect the events behind your workspace.',
  'Resource Detail': 'Inspect an exact authorized revision, its evidence and compatible next actions.',
  'Run Detail':
    'Follow one run end to end: observed state, desired state, attempts, evidence and recovery blockers.',
};

function currentPage(): Page {
  const slug = window.location.hash.slice(1).split('?')[0].split('/')[0];
  return pages.find((p) => (p.slug ?? p.name.toLowerCase().replaceAll(' ', '-')) === slug)?.name || 'Overview';
}

interface Organization {
  tenant_id: string;
  name: string;
}

interface OrganizationConnection {
  organization: Organization;
  token: string;
}

export function App() {
  const [active, setActive] = React.useState<Page>(currentPage);
  const [resourceRoute, setResourceRoute] = React.useState(() => parseResourceRoute(window.location.hash));
  const [runRoute, setRunRoute] = React.useState(() => parseRunRoute(window.location.hash));
  const [token, setTokenState] = React.useState<string>(
    () => localStorage.getItem('modelanvil_token') ?? ''
  );
  const [draftToken, setDraftToken] = React.useState(token);
  const [datasetRefreshKey, setDatasetRefreshKey] = React.useState(0);
  const [refreshKey, setRefreshKey] = React.useState(0);
  const [apiStatus, setApiStatus] = React.useState('Checking API');

  // Organization connection state
  const [organizationConnection, setOrganizationConnection] =
    React.useState<OrganizationConnection | null>(null);
  const [organizationConnections, setOrganizationConnections] = React.useState<
    OrganizationConnection[]
  >([]);
  const [organizationLoading, setOrganizationLoading] = React.useState(true);
  const [connectionBusy, setConnectionBusy] = React.useState(false);
  const [connectionError, setConnectionError] = React.useState<string | null>(null);

  // Explicit project scope state
  const [projects, setProjects] = React.useState<Project[]>([]);
  const [activeProjectId, setActiveProjectIdState] = React.useState<string | null>(() =>
    localStorage.getItem('modelanvil_active_project')
  );
  const [projectLoading, setProjectLoading] = React.useState(true);
  const [showCreateProjectModal, setShowCreateProjectModal] = React.useState(false);

  const currentOrganization =
    organizationConnection?.token === token ? organizationConnection.organization : null;
  const tenantName =
    currentOrganization?.name ||
    (organizationLoading ? 'Loading organization…' : 'Organization unavailable');
  const activeProject = projects.find((p) => p.id === activeProjectId) || null;

  const [navigationOpen, setNavigationOpen] = React.useState(false);
  const [advancedOpen, setAdvancedOpen] = React.useState(() => advancedNavigation.some(group => group.names.includes(currentPage())));
  React.useEffect(() => {
    if (advancedNavigation.some(group => group.names.includes(active))) setAdvancedOpen(true);
  }, [active]);
  const [headerOptionsOpen, setHeaderOptionsOpen] = React.useState(false);
  const menuButton = React.useRef<HTMLButtonElement>(null);
  const connectionDialog = React.useRef<HTMLDialogElement>(null);
  const connectionRequest = React.useRef<AbortController | null>(null);

  React.useEffect(() => () => connectionRequest.current?.abort(), []);

  React.useEffect(() => {
    if (!token || !activeProjectId || !currentOrganization || projectLoading || organizationLoading) return;
    return startActivation(token, activeProjectId);
  }, [token, activeProjectId, currentOrganization?.tenant_id, projectLoading, organizationLoading]);

  React.useEffect(() => {
    if (!navigationOpen) return;
    document.querySelector<HTMLButtonElement>('.navigation-rail [aria-current="page"]')?.focus();
    const close = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setNavigationOpen(false); menuButton.current?.focus(); }
    };
    const media = window.matchMedia('(min-width: 1025px)');
    const resized = () => { if (media.matches) setNavigationOpen(false); };
    window.addEventListener('keydown', close);
    media.addEventListener('change', resized);
    return () => { window.removeEventListener('keydown', close); media.removeEventListener('change', resized); };
  }, [navigationOpen]);

  // Fetch organization for the active token
  React.useEffect(() => {
    const controller = new AbortController();
    if (!token) { setOrganizationLoading(false); setOrganizationConnection(null); return; }
    setOrganizationLoading(true);
    apiPage<Organization>('/api/v1/tenants/', token, controller.signal)
      .then((page) => {
        if (controller.signal.aborted) return;
        const organization = page.results[0];
        if (!organization) throw new Error('No organization is available for this API key.');
        const connection = { organization, token };
        setOrganizationConnection(connection);
        setOrganizationConnections((current) => [
          ...current.filter((c) => c.organization.tenant_id !== organization.tenant_id),
          connection,
        ]);
      })
      .catch(() => {
        if (!controller.signal.aborted) setOrganizationConnection(null);
      })
      .finally(() => {
        if (!controller.signal.aborted) setOrganizationLoading(false);
      });
    return () => controller.abort();
  }, [token, refreshKey]);

  // Fetch projects for the active tenant
  React.useEffect(() => {
    const controller = new AbortController();
    if (!token) { setProjectLoading(false); setProjects([]); return; }
    setProjectLoading(true);
    allResources<Project>('/api/v1/projects/', token, controller.signal).then(results => ({ results }))
      .then((page) => {
        if (controller.signal.aborted) return;
        setProjects(page.results);
        const saved = localStorage.getItem('modelanvil_active_project');
        const matched = page.results.find((p) => p.id === saved);
        if (matched) {
          setActiveProjectIdState(matched.id);
          setActiveProjectId(matched.id);
        } else if (page.results.length > 0) {
          setActiveProjectIdState(page.results[0].id);
          setActiveProjectId(page.results[0].id);
          localStorage.setItem('modelanvil_active_project', page.results[0].id);
        } else {
          setActiveProjectIdState(null);
          setActiveProjectId(null);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setProjects([]);
          setActiveProjectIdState(null);
          setActiveProjectId(null);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setProjectLoading(false);
      });
    return () => controller.abort();
  }, [token, refreshKey]);

  React.useEffect(() => {
    const onHashChange = () => {
      setRunRoute(parseRunRoute(window.location.hash));
      setResourceRoute(parseResourceRoute(window.location.hash));
      setActive(currentPage());
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  React.useEffect(() => {
    document.title = active === 'Run Detail' && runRoute
      ? `Run details · ModelAnvil`
      : `${active} · ModelAnvil`;
  }, [active, runRoute]);

  React.useEffect(() => {
    const controller = new AbortController();
    fetch('/api/v1/health/', { signal: controller.signal })
      .then(async (response) => {
        const body = await response.json();
        if (!controller.signal.aborted)
          setApiStatus(response.ok && body.status === 'ok' ? 'API connected' : 'API unavailable');
      })
      .catch(() => {
        if (!controller.signal.aborted) setApiStatus('API unavailable');
      });
    return () => controller.abort();
  }, [refreshKey]);

  function load(page: Page) {
    setActive(page);
    setNavigationOpen(false);
    if (navigationOpen) document.getElementById('workspace-content')?.focus();
    window.scrollTo(0, 0);
    window.location.hash = slugFor(page);
    if (page === 'Datasets') setDatasetRefreshKey((value) => value + 1);
  }

  function refresh() {
    setRefreshKey((value) => value + 1);
    setDatasetRefreshKey((value) => value + 1);
  }

  function openConnection(newOrganization = false) {
    setDraftToken(newOrganization ? '' : token);
    setConnectionError(null);
    connectionDialog.current?.showModal();
  }

  function cancelConnectionRequest() {
    connectionRequest.current?.abort();
    connectionRequest.current = null;
    setConnectionBusy(false);
    setConnectionError(null);
  }

  async function applyConnection(candidateToken: string, expectedOrganization?: string) {
    connectionRequest.current?.abort();
    const controller = new AbortController();
    connectionRequest.current = controller;
    setConnectionBusy(true);
    setConnectionError(null);
    try {
      const page = await apiPage<Organization>(
        '/api/v1/tenants/',
        candidateToken,
        controller.signal
      );
      if (controller.signal.aborted) return;
      const organization = page.results[0];
      if (!organization) throw new Error('No organization is available for this API key.');
      if (expectedOrganization && organization.tenant_id !== expectedOrganization)
        throw new Error(
          'This key no longer matches the selected organization. Connect with a current key.'
        );
      const connection = { organization, token: candidateToken };
      setOrganizationConnections((current) => [
        ...current.filter((c) => c.organization.tenant_id !== organization.tenant_id),
        connection,
      ]);
      setOrganizationConnection(connection);
      setTokenState(candidateToken);
      setDraftToken(candidateToken);
      localStorage.setItem('modelanvil_token', candidateToken);
      refresh();
      connectionDialog.current?.close();
    } catch (error) {
      if (!controller.signal.aborted) setConnectionError(errorMessage(error));
    } finally {
      if (connectionRequest.current === controller) {
        connectionRequest.current = null;
        setConnectionBusy(false);
      }
    }
  }

  function connect(e: React.FormEvent) {
    e.preventDefault();
    void applyConnection(draftToken.trim());
  }

  function selectOrganization(id: string) {
    if (id === 'connect-organization') {
      openConnection(true);
      return;
    }
    const connection = organizationConnections.find((c) => c.organization.tenant_id === id);
    if (connection && connection.token !== token) void applyConnection(connection.token, id);
  }

  function selectProject(id: string) {
    if (id === 'create-project') {
      setShowCreateProjectModal(true);
      return;
    }
    setActiveProjectIdState(id);
    setActiveProjectId(id);
    localStorage.setItem('modelanvil_active_project', id);
    refresh();
  }

  function welcomeConnected(value: string) {
    setActiveProjectId(null);
    setActiveProjectIdState(null);
    localStorage.removeItem('modelanvil_active_project');
    localStorage.setItem('modelanvil_token', value);
    setTokenState(value); setDraftToken(value);
    load('Training'); refresh();
  }

  async function signOut() {
    try { await apiRequest('/api/v1/accounts/signout/', token, { method: 'POST', body: '{}' }); }
    catch (e) { setConnectionError(errorMessage(e)); return; }
    localStorage.removeItem('modelanvil_token'); localStorage.removeItem('modelanvil_active_project');
    setActiveProjectId(null); setActiveProjectIdState(null); setTokenState(''); setDraftToken('');
  }

  if (!token || (!organizationLoading && !currentOrganization)) return <Welcome onConnected={welcomeConnected} />;

  const selectedNavigation = active === 'Resource Detail' ? resourceRoute?.kind === 'model-version' ? 'Models' : 'Datasets' : active === 'Run Detail'
    ? runRoute?.kind === 'training' ? 'Training' : runRoute?.kind === 'evaluation' ? 'Evaluation' : 'Workflows'
    : active;

  return (
    <div className={`layout ${navigationOpen ? 'navigation-open' : ''}`}>
      <a
        className="skip-link"
        href="#workspace-content"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById('workspace-content')?.focus();
        }}
      >
        Skip to content
      </a>
      <aside className="navigation-rail" id="workspace-navigation" aria-label="Workspace navigation">
        <a className="brand" href="#overview" aria-label="ModelAnvil Model Workspace overview">
          <img className="brand-logo" src={`${import.meta.env.BASE_URL}brand/modelanvil-logo-reversed.svg`} alt="" width="1088" height="240" />
          <img className="brand-icon" src={`${import.meta.env.BASE_URL}brand/modelanvil-icon.svg`} alt="" width="256" height="256" />
          <span className="brand-subtitle">MODEL WORKSPACE</span>
        </a>
        <div
          className="workspace"
          title="Workspace is scoped to the connected API key and active project"
        >
          <span className="workspace-avatar">{tenantName.charAt(0).toUpperCase()}</span>
          <div>
            <strong>{tenantName}</strong>
            <small>{activeProject ? activeProject.name : 'Tenant workspace'}</small>
          </div>
        </div>
        <nav aria-label="Main navigation">
          {primaryNavigation.map((group) => (
            <div className="nav-group" key={group.label}>
              <p className="nav-label">{group.label}</p>
              {pages
                .filter((page) => group.names.includes(page.name))
                .map(({ name, icon: Icon }) => (
                  <NavigationItem
                    key={name}
                    title={name}
                    selected={selectedNavigation === name}
                    icon={<Icon size={18} aria-hidden="true" />}
                    aria-label={name}
                    onClick={() => load(name)}
                  >
                    {name}
                  </NavigationItem>
                ))}
            </div>
          ))}
          <details className="nav-advanced" open={advancedOpen} onToggle={event => setAdvancedOpen(event.currentTarget.open)}>
            <summary>Advanced</summary>
            {advancedNavigation.map((group) => (
              <div className="nav-group" key={group.label}>
                <p className="nav-label">{group.label}</p>
                {pages.filter((page) => group.names.includes(page.name)).map(({ name, icon: Icon }) => (
                  <NavigationItem key={name} title={name} selected={selectedNavigation === name}
                    icon={<Icon size={18} aria-hidden="true" />} aria-label={name} onClick={() => load(name)}>
                    {name}
                  </NavigationItem>
                ))}
              </div>
            ))}
          </details>
        </nav>
        <div className="sidebar-bottom">
          <span
            className={`status-dot ${
              apiStatus === 'API unavailable'
                ? 'offline'
                : apiStatus === 'Checking API'
                ? 'checking'
                : ''
            }`}
          />
          <span>
            {apiStatus}
            <small>Control plane</small>
          </span>
        </div>
      </aside>
      <main>
        <WorkspaceHeader className={headerOptionsOpen ? 'options-open' : undefined}>
          <div className="compact-title">
            <a className="compact-product" href="#overview">ModelAnvil</a>
            <span className="compact-page">{active}</span>
            <Button type="button" className="icon-button" aria-label="Workspace options" aria-expanded={headerOptionsOpen} aria-controls="workspace-context workspace-actions" onClick={() => setHeaderOptionsOpen(value => !value)}>
              <Settings2 size={17} aria-hidden="true" />
            </Button>
            <Button type="button" ref={menuButton} variant="quiet" aria-label="Toggle navigation" aria-expanded={navigationOpen} aria-controls="workspace-navigation" onClick={() => setNavigationOpen(value => !value)}>Menu</Button>
          </div>
          <div className="breadcrumbs" id="workspace-context">
            <label className="organization-select">
              <Building2 size={16} aria-hidden="true" />
              <select
                aria-label="Organization"
                value={currentOrganization?.tenant_id || ''}
                disabled={organizationLoading || connectionBusy}
                onChange={(e) => selectOrganization(e.target.value)}
              >
                {!currentOrganization && (
                  <option value="" disabled>
                    {tenantName}
                  </option>
                )}
                {organizationConnections.map(({ organization }) => (
                  <option key={organization.tenant_id} value={organization.tenant_id}>
                    {organization.name}
                  </option>
                ))}
                <option value="connect-organization">Connect organization…</option>
              </select>
            </label>
            <ChevronRight className="breadcrumb-divider" size={14} aria-hidden="true" />
            <label className="organization-select">
              <FolderGit2 size={16} aria-hidden="true" />
              <select
                aria-label="Project"
                value={activeProjectId || ''}
                disabled={organizationLoading || connectionBusy || projectLoading}
                onChange={(e) => selectProject(e.target.value)}
              >
                {!activeProject && (
                  <option value="" disabled>
                    {projectLoading ? 'Loading project…' : 'Select project…'}
                  </option>
                )}
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
                <option value="create-project">+ New project…</option>
              </select>
            </label>
            <ChevronRight className="breadcrumb-divider" size={14} aria-hidden="true" />
            <strong className="breadcrumb-page">{active}</strong>
          </div>
          <div className="header-actions" id="workspace-actions">
            <a className="mobile-brand" href="#overview" aria-label="ModelAnvil overview">
              <img src={`${import.meta.env.BASE_URL}brand/modelanvil-icon.svg`} alt="" width="32" height="32" />
            </a>
            <WorkspaceSearch pages={pages.filter(p => p.name !== 'Run Detail').map(p => p.name)} onNavigate={name => load(name as Page)} />
            <ThemeControl />
            {!projectLoading && !organizationLoading && token && <ActiveJobs key={`${token}-${activeProjectId}`} token={token} refreshKey={refreshKey} />}
            <Button
              className="icon-button"
              title="Refresh workspace"
              aria-label="Refresh workspace"
              onClick={refresh}
            >
              <RefreshCw size={16} />
            </Button>
            <Button
              className="connection-button"
              aria-label={token === 'session' ? 'Sign out' : 'Connection'}
              disabled={connectionBusy}
              onClick={() => token === 'session' ? void signOut() : openConnection()}
            >
              <KeyRound size={15} aria-hidden="true" />
              <span>{token === 'session' ? 'Sign out' : 'Connection'}</span>
            </Button>
          </div>
        </WorkspaceHeader>
        <dialog
          ref={connectionDialog}
          className="connection-dialog"
          aria-labelledby="connection-title"
          onCancel={cancelConnectionRequest}
          onClose={cancelConnectionRequest}
        >
          <div className="dialog-title">
            <h2 id="connection-title">Connect organization</h2>
            <Button
              className="icon-button"
              aria-label="Close connection settings"
              onClick={() => connectionDialog.current?.close()}
            >
              <X size={18} />
            </Button>
          </div>
          <p className="muted">
            Enter an organization’s API key to verify access and connect its workspace. Connected
            organizations appear in the dropdown for this browser session.
          </p>
          <form className="api-key" onSubmit={connect} aria-busy={connectionBusy}>
            {connectionError && (
              <Notice as="p" tone="error" className="notice error" role="alert">
                {connectionError}
              </Notice>
            )}
            <label htmlFor="api-key">API key</label>
            <Field
              id="api-key"
              required
              disabled={connectionBusy}
              type="password"
              placeholder="Bearer API key"
              value={draftToken}
              onChange={(e) => setDraftToken(e.target.value)}
            />
            <Button className="primary" type="submit" disabled={connectionBusy}>
              {connectionBusy ? 'Verifying access…' : 'Connect'}
            </Button>
          </form>
        </dialog>

        <CreateProjectModal
          token={token}
          isOpen={showCreateProjectModal}
          onClose={() => setShowCreateProjectModal(false)}
          onSuccess={(newProj) => {
            setProjects((curr) => [newProj, ...curr]);
            selectProject(newProj.id);
          }}
        />

        <div className="page-content" id="workspace-content" data-screen={slugFor(active)} tabIndex={-1}>
          {connectionError && (
            <Notice tone="error" className="notice error" role="alert">
              {connectionError}
              <Button onClick={() => openConnection()}>Review connection</Button>
            </Notice>
          )}
          <div className="page-heading">
            <div>
              <span className="eyebrow">
                {navigationGroups.find((group) => group.names.includes(active))?.label ?? 'Run'}
              </span>
              <h1>{active === 'Overview' ? 'Project overview' : active === 'RAG' ? 'Retrieval workbench' : active}</h1>
              <p>{descriptions[active]}</p>
            </div>
            {active === 'Overview' && (
              <Button onClick={() => load('Training')}>
                Start fine-tuning
                <ArrowUpRight size={16} aria-hidden="true" />
              </Button>
            )}
          </div>

          <DraftScope.Provider value={currentOrganization ? { organization: currentOrganization.tenant_id, project: activeProjectId } : null}>
          <ScreenBoundary key={`${token}-${activeProjectId}-${active}`}>
          {projectLoading || organizationLoading ? (<p role="status">Loading project scope…</p>) : active === 'Resource Detail' ? (resourceRoute ? <ResourceDetailPage key={`${token}-${activeProjectId}-${resourceRoute.kind}-${resourceRoute.id}`} token={token} kind={resourceRoute.kind} id={resourceRoute.id} refreshKey={refreshKey} /> : <p role="alert">This resource address is invalid. Open an exact revision from Models or Datasets.</p>) : active === 'Run Detail' ? (
            runRoute ? (
              <RunDetailPage
                key={`${token}-${activeProjectId}-${runRoute.kind}-${runRoute.id}`}
                token={token}
                refreshKey={refreshKey}
                kind={runRoute.kind}
                runId={runRoute.id}
              />
            ) : (
              <Notice className="notice">
                <span>
                  This address has no run identifier. Open a run from its list to load a durable run link.
                </span>
                <Button onClick={() => load('Workflows')}>Go to workflows</Button>
              </Notice>
            )
          ) : active === 'Dataset Bank' ? (
            <DatasetBankPage
              key={`${token}-${activeProjectId}`}
              token={token}
              refreshKey={refreshKey}
              onImportSuccess={() => setDatasetRefreshKey((v) => v + 1)}
            />
          ) : active === 'Datasets' ? (
            <DatasetsPage
              token={token}
              refreshKey={datasetRefreshKey}
              key={`${token}-${activeProjectId}`}
            />
          ) : active === 'Annotation' ? (
            <AnnotationPage
              key={`${token}-${activeProjectId}`}
              token={token}
              refreshKey={refreshKey}
            />
          ) : active === 'Evaluation' ? (
            <EvaluationPage
              key={`${token}-${activeProjectId}`}
              token={token}
              refreshKey={refreshKey}
            />
          ) : active === 'Alignment' ? (
            <AlignmentPage
              key={`${token}-${activeProjectId}`}
              token={token}
              refreshKey={refreshKey}
            />
          ) : active === 'Infrastructure' ? (
            <InfrastructurePage
              key={`${token}-${activeProjectId}`}
              token={token}
              refreshKey={refreshKey}
            />
          ) : active === 'Workflows' ? (
            <WorkflowsPage
              key={`${token}-${activeProjectId}`}
              token={token}
              refreshKey={refreshKey}
            />
          ) : active === 'Budgets' ? (
            <BudgetsPage
              key={`${token}-${activeProjectId}`}
              token={token}
              refreshKey={refreshKey}
            />
          ) : active === 'Models' ? (
            <ModelsPage key={`${token}-${activeProjectId}`} token={token} refreshKey={refreshKey} />
          ) : active === 'Chat' ? (
            <ChatPage key={`${token}-${activeProjectId}`} token={token} refreshKey={refreshKey} />
          ) : active === 'Recipes' ? (
            <RecipesPage key={`${token}-${activeProjectId}`} token={token} refreshKey={refreshKey} />
          ) : active === 'Specialists' ? (
            <SpecialistsPage key={`${token}-${activeProjectId}`} token={token} refreshKey={refreshKey} />
          ) : active === 'Training' ? (
            <TrainingPage
              key={`${token}-${activeProjectId}`}
              token={token}
              refreshKey={refreshKey}
            />
          ) : active === 'RAG' ? (
            <ClusterExplorerPage
              key={`${token}-${activeProjectId}`}
              token={token}
              refreshKey={refreshKey}
            />
          ) : active === 'Context Lab' ? (
            <ContextLabPage
              key={`${token}-${activeProjectId}`}
              token={token}
              refreshKey={refreshKey}
            />
          ) : active === 'Releases' ? (
            <ReleasesPage
              key={`${token}-${activeProjectId}`}
              token={token}
              refreshKey={refreshKey}
            />
          ) : active === 'Audit' ? (
            <AuditPage key={`${token}-${activeProjectId}`} token={token} refreshKey={refreshKey} />
          ) : (
            <OverviewPage
              key={`${token}-${activeProjectId}`}
              token={token}
              refreshKey={refreshKey}
              activeProject={activeProject}
              onNavigate={(page) => load(page as Page)}
              onOpenConnection={() => openConnection()}
              onProjectCreated={(p) => {
                setProjects((curr) => [p, ...curr]);
                selectProject(p.id);
              }}
              onPrerequisiteAdded={() => refresh()}
            />
          )}

          </ScreenBoundary>
          </DraftScope.Provider>
          <footer>
            <BuildIdentity token={token} refreshKey={refreshKey} />
            <span>
              <Activity size={14} /> Control plane
            </span>
          </footer>
        </div>
      </main>
    </div>
  );
}

// Storybook imports the real app without bootstrapping the production entry point.
const rootElement = document.getElementById('root');
if (rootElement) {
  const root =
    (import.meta.hot?.data.root as ReturnType<typeof createRoot> | undefined) ??
    createRoot(rootElement);
  if (import.meta.hot) import.meta.hot.data.root = root;
  root.render(<React.StrictMode><App /></React.StrictMode>);
}

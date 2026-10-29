import { Button, Dialog, Field, Notice, PageHeader, WorkspaceHeader } from './components/ui';
import { PrivacySettings } from './components/PrivacySettings';
import { LocalMeasurements } from './components/LocalMeasurements';
import { Welcome } from './components/Welcome';
import { ReviewAccess } from './components/Access';
import { parseResourceRoute } from './api/resource-routes';
import { DraftScope } from './components/Draft';
import { ScreenBoundary } from './components/ScreenBoundary';
import { NavigationRail } from './components/NavigationRail';
import { SettingsMenu } from './components/SettingsMenu';
import React from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, BookOpen, CheckCheck, ChevronRight, CircleDollarSign, Compass, Database, FileCode, Flame, Layers3, Library, Menu as MenuIcon, MessageSquare, Package, Rocket, Scale, ScanText, Server, Tags, Workflow, X, Mic } from 'lucide-react';
import './design-system/index.css';
import './app.css';
import { WorkspaceSearch } from './components/WorkspaceSearch';
import { ActiveJobs } from './components/ActiveJobs';
import { startActivation } from './api/activation';
import { BuildIdentity } from './components/BuildIdentity';
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
const AudioPage = React.lazy(() => import('./pages/AudioPage').then(module => ({ default: module.AudioPage })));
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
  | 'Audio'
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
  { name: 'Models', icon: Package, endpoint: '/api/v1/models/' },
  { name: 'Chat', icon: MessageSquare, endpoint: '/api/v1/inference/models/' },
  { name: 'Specialists', icon: ScanText, endpoint: '/api/v1/specialists/' },
  { name: 'Audio', icon: Mic, endpoint: '/api/v1/audio/' },
  { name: 'Recipes', icon: BookOpen, endpoint: '/api/v1/recipes/' },
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

const navigationGroups = [
  { label: 'Workspace', names: ['Overview', 'Datasets', 'Models', 'Training', 'Evaluation', 'Chat'] },
  { label: 'Data tools', names: ['Dataset Bank', 'Recipes', 'Annotation'] },
  { label: 'Develop', names: ['Specialists', 'Audio', 'Alignment'] },
  { label: 'Context & release', names: ['RAG', 'Context Lab', 'Releases'] },
  { label: 'Operations', names: ['Workflows', 'Infrastructure', 'Budgets', 'Audit'] },
];

const descriptions: Record<Page, string> = {
  Overview: 'Your next step, active work and latest results.',
  'Dataset Bank': 'Find source data and check its license and readiness.',
  Datasets: 'Prepare and publish dataset versions.',
  Annotation: 'Review samples and build approved label snapshots.',
  Models: 'Model versions and what they can do.',
  Chat: 'Run local models and compare responses.',
  Specialists: 'Read documents and make typed decisions with local models.',
  Audio: 'Train speech output heads and generate audio locally.',
  Recipes: 'Compose data recipes, preview them and publish runs.',
  Training: 'Fine-tune a model on your examples.',
  Alignment: 'Configure preference learning and inspect outcomes.',
  Evaluation: 'Compare model versions on held-out examples.',
  Workflows: 'Follow jobs from queue to outcome.',
  RAG: 'Explore knowledge sources and retrieved evidence.',
  'Context Lab': 'Compile exact inputs and see the token budget.',
  Releases: 'Release versions, serving endpoints and provenance.',
  Infrastructure: 'Worker pools, capabilities and availability.',
  Budgets: 'Usage, reservations and spending policies.',
  Audit: 'Trace the events behind your workspace.',
  'Resource Detail': 'One exact version, its evidence and next actions.',
  'Run Detail': 'One run end to end: state, attempts, evidence and recovery.',
};

/** The rail item that represents a route, including the URL-only detail routes. */
function navigationTarget(active: Page, runRoute: ReturnType<typeof parseRunRoute>, resourceRoute: ReturnType<typeof parseResourceRoute>): Page {
  if (active === 'Resource Detail') return resourceRoute?.kind === 'model-version' ? 'Models' : 'Datasets';
  if (active === 'Run Detail') return runRoute?.kind === 'training' ? 'Training' : runRoute?.kind === 'evaluation' ? 'Evaluation' : 'Workflows';
  return active;
}

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
  const selectedNavigation = navigationTarget(active, runRoute, resourceRoute);
  const [advancedNavigation, setAdvancedNavigation] = React.useState(() => !navigationGroups[0].names.includes(selectedNavigation));
  // The advanced groups open for their own pages and close again when the user returns to the workspace group.
  React.useEffect(() => { setAdvancedNavigation(!navigationGroups[0].names.includes(selectedNavigation)); }, [selectedNavigation]);
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
  const [workspaceSettingsOpen, setWorkspaceSettingsOpen] = React.useState(false);

  const currentOrganization =
    organizationConnection?.token === token ? organizationConnection.organization : null;
  const tenantName =
    currentOrganization?.name ||
    (organizationLoading ? 'Loading organization…' : 'Organization unavailable');
  const activeProject = projects.find((p) => p.id === activeProjectId) || null;

  const [navigationOpen, setNavigationOpen] = React.useState(false);
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

  const [access, setAccess] = React.useState<{ token: string; role: string } | null>(null);
  React.useEffect(() => {
    const c = new AbortController();
    if (token) apiRequest<{ role: string }>('/api/v1/accounts/access/', token, { signal: c.signal })
      .then(result => { if (!c.signal.aborted) setAccess({ token, role: result.role }); })
      .catch(() => { if (!c.signal.aborted) setAccess(null); });
    return () => c.abort();
  }, [token, refreshKey]);

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
      <NavigationRail
        groups={navigationGroups}
        pages={pages.filter((page) => !page.slug)}
        selected={selectedNavigation}
        advancedOpen={advancedNavigation}
        onAdvancedToggle={setAdvancedNavigation}
        onNavigate={(name) => load(name as Page)}
      />
      <main>
        <WorkspaceHeader>
          <Button type="button" ref={menuButton} variant="quiet" icon className="menu-button" aria-label="Menu — toggle navigation" aria-expanded={navigationOpen} aria-controls="workspace-navigation" onClick={() => setNavigationOpen((value) => !value)}>
            <MenuIcon size={20} aria-hidden="true" />
          </Button>
          <a className="brand-compact" href="#overview" aria-label="ModelAnvil overview">
            <img src={`${import.meta.env.BASE_URL}brand/modelanvil-icon.svg`} alt="" width="28" height="28" />
          </a>
          <div className="scope" id="workspace-context">
            <span className="scope-org" title={tenantName}>{tenantName}</span>
            <ChevronRight size={14} aria-hidden="true" />
            <label className="organization-select">
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
          </div>
          <div className="header-actions" id="workspace-actions">
            <WorkspaceSearch pages={navigationGroups.flatMap((group) => group.names)} onNavigate={(name) => load(name as Page)} />
            {!projectLoading && !organizationLoading && token && <ActiveJobs key={`${token}-${activeProjectId}`} token={token} refreshKey={refreshKey} />}
            <SettingsMenu
              tenantName={tenantName}
              organizations={organizationConnections.map((connection) => connection.organization)}
              currentOrganization={currentOrganization}
              organizationDisabled={organizationLoading || connectionBusy}
              onSelectOrganization={selectOrganization}
              onRefresh={refresh}
              isSession={token === 'session'}
              connectionBusy={connectionBusy}
              onConnection={() => openConnection()}
              onSignOut={() => void signOut()}
              apiStatus={apiStatus}
              onWorkspaceSettings={() => setWorkspaceSettingsOpen(true)}
              about={<BuildIdentity token={token} refreshKey={refreshKey} />}
            />
          </div>
        </WorkspaceHeader>
        <dialog
          ref={connectionDialog}
          data-ui="dialog"
          aria-labelledby="connection-title"
          onCancel={cancelConnectionRequest}
          onClose={cancelConnectionRequest}
        >
          <header>
            <div>
              <h2 id="connection-title">Connect organization</h2>
              <p>Enter an organization’s API key to verify access. Connected organizations stay available in this browser session.</p>
            </div>
            <Button type="button" variant="quiet" icon aria-label="Close connection settings" onClick={() => connectionDialog.current?.close()}>
              <X size={18} aria-hidden="true" />
            </Button>
          </header>
          <div data-ui="dialog-body">
            <form data-ui="form" onSubmit={connect} aria-busy={connectionBusy}>
              {connectionError && (
                <Notice as="p" tone="error" className="notice error" role="alert">
                  {connectionError}
                </Notice>
              )}
              <div data-ui="control"><label data-ui="control-label" htmlFor="api-key">API key</label>
              <Field
                id="api-key"
                required
                disabled={connectionBusy}
                type="password"
                placeholder="Bearer API key"
                value={draftToken}
                onChange={(e) => setDraftToken(e.target.value)}
              /></div>
              <div data-ui="actions"><Button variant="primary" type="submit" disabled={connectionBusy}>
                {connectionBusy ? 'Verifying access…' : 'Connect'}
              </Button></div>
            </form>
          </div>
        </dialog>

        <Dialog title="Workspace settings" description="Privacy policy and local measurements for this project." size="lg" open={workspaceSettingsOpen} onClose={() => setWorkspaceSettingsOpen(false)}>
          <PrivacySettings token={token} />
          <LocalMeasurements token={token} />
        </Dialog>

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
          <PageHeader
            title={active === 'Overview' ? 'Project overview' : active === 'RAG' ? 'Retrieval workbench' : active}
            description={descriptions[active]}
            actions={<div id="page-actions" data-ui="actions" />}
          />

          <DraftScope.Provider value={currentOrganization ? { organization: currentOrganization.tenant_id, project: activeProjectId } : null}>
          <ReviewAccess.Provider value={access?.token === token ? access.role : 'engineer'}><ScreenBoundary key={`${token}-${activeProjectId}-${active}`}>
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
          ) : active === 'Audio' ? (
            <AudioPage key={`${token}-${activeProjectId}`} token={token} refreshKey={refreshKey} />
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
              onCreateProject={() => setShowCreateProjectModal(true)}
            />
          )}

          </ScreenBoundary></ReviewAccess.Provider>
          </DraftScope.Provider>
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

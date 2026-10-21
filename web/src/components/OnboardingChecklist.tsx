import { Button, Card, Notice } from './ui';
import { useEffect, useState, useCallback, useRef } from 'react';
import {
  CheckCircle2,
  Circle,
  AlertCircle,
  KeyRound,
  FolderGit2,
  Database,
  BookOpen,
  Layers,
  Server,
  CircleDollarSign,
  ChevronDown,
  ChevronUp,
  ArrowRight,
  Sparkles,
  Rocket,
  RefreshCw,
} from 'lucide-react';
import { errorMessage } from '../api/client';
import {
  CreateProjectModal,
} from './PrerequisiteModals';
import { allResources } from '../api/resources';
import type { Project, TokenizerVersion } from '../api/resources';

import { setupReadiness, type SetupDataset, type SetupPool, type SetupBudget, type SetupWorker, type SetupRunner, type SetupModel } from '../api/setup-readiness';

export interface OnboardingState {
  hasConnection: boolean;
  activeProject: Project | null;
  datasetCount: number;
  tokenizerCount: number;
  modelVersionCount: number;
  workerPoolCount: number;
  budgetPolicyCount: number;
  firstTokenizerName?: string;
  firstModelName?: string;
}

export function OnboardingChecklist({
  token,
  refreshKey,
  activeProject,
  onNavigate,
  onOpenConnection,
  onProjectCreated,
}: {
  token: string;
  refreshKey: number;
  activeProject: Project | null;
  onNavigate: (page: string) => void;
  onOpenConnection: () => void;
  onProjectCreated: (project: Project) => void;
  onPrerequisiteAdded: () => void;
}) {
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    return localStorage.getItem('modelanvil_onboarding_collapsed') !== 'false';
  });

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const requestVersion = useRef(0);
  const savedConnection = useRef(token);
  const [savedState, setState] = useState<OnboardingState>({
    hasConnection: false,
    activeProject,
    datasetCount: 0,
    tokenizerCount: 0,
    modelVersionCount: 0,
    workerPoolCount: 0,
    budgetPolicyCount: 0,
  });

  const state = savedConnection.current === token && savedState.activeProject?.id === activeProject?.id ? savedState : {
    hasConnection: false, activeProject, datasetCount: 0, tokenizerCount: 0, modelVersionCount: 0, workerPoolCount: 0, budgetPolicyCount: 0,
  };

  // Modal open states
  const [showProjectModal, setShowProjectModal] = useState(false);

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem('modelanvil_onboarding_collapsed', String(next));
      return next;
    });
  };

  const loadPrerequisites = useCallback(async (signal?: AbortSignal) => {
    const version = ++requestVersion.current;
    savedConnection.current = token;
    setState({ hasConnection: false, activeProject, datasetCount: 0, tokenizerCount: 0, modelVersionCount: 0, workerPoolCount: 0, budgetPolicyCount: 0 });
    setError(null);
    if (!token.trim()) { setLoading(false); return; }
    setLoading(true);
    const results = await Promise.allSettled([
      allResources<SetupDataset>('/api/v1/dataset-revisions/', token, signal),
      allResources<TokenizerVersion>('/api/v1/tokenizers/', token, signal),
      allResources<SetupModel>('/api/v1/model-versions/', token, signal),
      allResources<SetupPool>('/api/v1/worker-pools/', token, signal),
      allResources<SetupBudget>('/api/v1/budget-policies/', token, signal),
      allResources<SetupWorker>('/api/v1/worker-inventory/', token, signal),
      allResources<SetupRunner>('/api/v1/runner-manifests/', token, signal),
    ]);
    if (signal?.aborted || version !== requestVersion.current) return;
    const [datasets, tokenizers, models, pools, budgets, workers, runners] = results.map(r => r.status === 'fulfilled' ? r.value : []);
    const failures = results.filter(r => r.status === 'rejected');
    if (failures.length) setError('Some prerequisites could not be verified. ' + errorMessage((failures[0] as PromiseRejectedResult).reason));
    setState({ hasConnection: results.some(r => r.status === 'fulfilled'), activeProject,
      ...setupReadiness({ datasets: datasets as SetupDataset[], tokenizers: tokenizers as TokenizerVersion[], models: models as SetupModel[],
        pools: pools as SetupPool[], budgets: budgets as SetupBudget[], workers: workers as SetupWorker[], runners: runners as SetupRunner[] }) });
    setLoading(false);
  }, [token, activeProject]);

  useEffect(() => {
    const controller = new AbortController();
    void loadPrerequisites(controller.signal);
    return () => controller.abort();
  }, [loadPrerequisites, refreshKey]);

  // Derived readiness criteria
  const items = [
    {
      id: 'connection',
      title: 'Tenant API connection',
      description: state.hasConnection ? 'Authorized key verified' : 'Connect and verify a workspace API key',
      isReady: state.hasConnection,
      icon: KeyRound,
      actionText: token.trim() ? 'Switch key' : 'Connect workspace',
      action: onOpenConnection,
    },
    {
      id: 'project',
      title: 'Project scope',
      description: activeProject
        ? `Scoped to ${activeProject.name} (${activeProject.slug})`
        : 'Select or create a project to scope resources',
      isReady: !!activeProject,
      icon: FolderGit2,
      actionText: activeProject ? 'New project' : '+ Create project',
      action: () => setShowProjectModal(true),
    },
    {
      id: 'data',
      title: 'Dataset readiness',
      description:
        state.datasetCount > 0
          ? `${state.datasetCount} published dataset revision(s) available`
          : 'Prepare a dataset version or import catalog source',
      isReady: state.datasetCount > 0,
      icon: Database,
      actionText: state.datasetCount > 0 ? 'View datasets' : 'Prepare dataset',
      action: () => onNavigate('Datasets'),
    },
    {
      id: 'tokenizer',
      title: 'Tokenizer registration',
      description:
        state.tokenizerCount > 0
          ? `${state.tokenizerCount} tokenizer(s) ready (${state.firstTokenizerName || 'active'})`
          : 'Import a model with its actual tokenizer or initialize a CPU base',
      isReady: state.tokenizerCount > 0,
      icon: BookOpen,
      actionText: 'Set up model and tokenizer',
      action: () => onNavigate('Models'),
    },
    {
      id: 'model',
      title: 'Base model version',
      description:
        state.modelVersionCount > 0
          ? `${state.modelVersionCount} model version(s) with recorded weights (${state.firstModelName || 'active'})`
          : 'Import pinned model weights or initialize a CPU base',
      isReady: state.modelVersionCount > 0,
      icon: Layers,
      actionText: 'Import or initialize model',
      action: () => onNavigate('Models'),
    },
    {
      id: 'workers',
      title: 'Worker pools & execution',
      description:
        state.workerPoolCount > 0
          ? `${state.workerPoolCount} active pool(s) with an available matching worker`
          : 'Register an available worker with matching runtime and memory',
      isReady: state.workerPoolCount > 0,
      icon: Server,
      actionText: 'Set up compute',
      action: () => onNavigate('Infrastructure'),
    },
    {
      id: 'budget',
      title: 'Spending policy & budgets',
      description:
        state.budgetPolicyCount > 0
          ? `${state.budgetPolicyCount} enabled training-step budget(s)`
          : 'Enable a training-step budget with a positive limit',
      isReady: state.budgetPolicyCount > 0,
      icon: CircleDollarSign,
      actionText: 'Set up budget policy',
      action: () => onNavigate('Budgets'),
    },
  ];

  const readyCount = items.filter((item) => item.isReady).length;
  const totalCount = items.length;
  const isAllReady = readyCount === totalCount;
  const isTrainingReady = !loading && !error && isAllReady;

  // Identify next suggested action
  const nextMissing = items.find((item) => !item.isReady);

  return (
    <Card
      className="panel onboarding-panel"
      aria-labelledby="onboarding-heading"
      style={{
        border: '1px solid var(--border)',
        background: 'var(--surface)',
        marginBottom: 'var(--space-24)',
      }}
    >
      <div
        className="panel-title"
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 'var(--space-12)',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-8)' }}>
            <Sparkles size={18} style={{ color: 'var(--primary-text)' }} aria-hidden="true" />
            <h2 id="onboarding-heading" style={{ margin: 0, fontSize: 'var(--type-20)' }}>
              Workspace Setup & Prerequisites
            </h2>
            <span
              className={`badge ${isAllReady ? 'state-completed' : ''}`}
              style={{ fontWeight: 600 }}
            >
              {loading ? 'Checking prerequisites…' : `${readyCount} of ${totalCount} recorded`}
            </span>
          </div>
          <p style={{ margin: 'var(--space-4) 0 0', color: 'var(--text-muted)', fontSize: 'var(--type-13)' }}>
            Your connected resources and the next setup step.
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-8)' }}>
          <Button
            type="button"
            className="icon-button"
            title="Refresh prerequisites"
            aria-label="Refresh prerequisites"
            onClick={() => void loadPrerequisites()}
            disabled={loading}
          >
            <RefreshCw size={15} className={loading ? 'spinning' : ''} />
          </Button>

          <Button
            type="button"
            className="text-button"
            onClick={toggleCollapsed}
            aria-expanded={!collapsed}
            aria-controls="onboarding-checklist-body"
            style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-4)' }}
          >
            {collapsed ? 'Expand checklist' : 'Minimize'}
            {collapsed ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
          </Button>
        </div>
      </div>

          {error && (
            <Notice tone="error" className="notice error" role="alert" style={{ marginBottom: 'var(--space-16)' }}>
              <AlertCircle size={16} />
              <span>{error}</span>
              <Button type="button" onClick={() => void loadPrerequisites()}>
                Retry
              </Button>
            </Notice>
          )}

      <div className="onboarding-journey" aria-label="Workspace prerequisites">
        {items.map(item => <Button type="button" className={`journey-step ${item.isReady ? 'ready' : ''}`} key={item.id} onClick={item.action}>
          {item.isReady ? <CheckCircle2 size={18} aria-hidden="true" /> : <Circle size={18} aria-hidden="true" />}
          <span>{item.title}<small>{loading ? 'Checking…' : item.isReady ? 'Resource present' : 'Needs setup'}</small></span>
        </Button>)}
      </div>

      {!collapsed && (
        <div id="onboarding-checklist-body" className="panel-body" style={{ paddingTop: 'var(--space-16)' }}>


          {/* Actionable highlight banner */}
          {isTrainingReady ? (
            <Notice tone="success"
              className="notice success"
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: 'var(--space-20)',
                padding: '14px var(--space-18)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-10)' }}>
                <Rocket size={20} />
                <div>
                  <strong>Ready for training preflight!</strong>
                  <p style={{ margin: '2px 0 0', fontSize: 'var(--type-12)' }}>
                    Published data, model/tokenizer, a matching worker and a step budget are recorded.
                    Preflight still verifies actual bytes, current runtime, device availability and remaining budget.
                  </p>
                </div>
              </div>
              <Button
                type="button"
                className="primary"
                onClick={() => onNavigate('Training')}
                style={{ whiteSpace: 'nowrap' }}
              >
                Launch Training Preflight <ArrowRight size={14} />
              </Button>
            </Notice>
          ) : (
            nextMissing && (
              <Notice
                className="notice"
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: 'var(--space-20)',
                  padding: 'var(--space-12) var(--space-18)',
                }}
              >
                <div>
                  <strong>Next action: {nextMissing.title}</strong>
                  <p style={{ margin: '2px 0 0', fontSize: 'var(--type-12)', color: 'var(--text-muted)' }}>
                    {nextMissing.description}
                  </p>
                </div>
                <Button
                  type="button"
                  className="primary"
                  onClick={nextMissing.action}
                  style={{ whiteSpace: 'nowrap' }}
                >
                  {nextMissing.actionText} <ArrowRight size={14} />
                </Button>
              </Notice>
            )
          )}

          {/* Progress bar */}
          <div style={{ marginBottom: 'var(--space-16)' }}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                fontSize: 'var(--type-12)',
                marginBottom: 'var(--space-6)',
                color: 'var(--text-muted)',
              }}
            >
              <span>Onboarding readiness</span>
              <span>{Math.round((readyCount / totalCount) * 100)}% complete</span>
            </div>
            <progress
              value={readyCount}
              max={totalCount}
              style={{ width: '100%', height: '8px' }}
              aria-label="Workspace readiness progress"
            />
          </div>

          {/* Steps checklist grid */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(310px, 1fr))',
              gap: 'var(--space-12)',
            }}
          >
            {items.map((item) => {
              const Icon = item.icon;
              return (
                <div
                  key={item.id}
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 'var(--space-12)',
                    padding: '14px',
                    borderRadius: 'var(--radius-8)',
                    border: item.isReady
                      ? '1px solid var(--border)'
                      : '1px solid var(--control-border)',
                    background: item.isReady ? 'var(--surface)' : 'var(--surface-subtle)',
                  }}
                >
                  <div style={{ marginTop: '2px' }}>
                    {item.isReady ? (
                      <CheckCircle2 size={18} style={{ color: 'var(--success)' }} />
                    ) : (
                      <Circle size={18} style={{ color: 'var(--text-muted)' }} />
                    )}
                  </div>

                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 'var(--space-6)',
                      }}
                    >
                      <strong
                        style={{
                          fontSize: 'var(--type-13)',
                          display: 'flex',
                          alignItems: 'center',
                          gap: 'var(--space-6)',
                        }}
                      >
                        <Icon size={14} style={{ color: 'var(--text-muted)' }} />
                        {item.title}
                      </strong>
                      <span
                        className={`badge ${item.isReady ? 'state-ready' : 'state-pending'}`}
                        style={{ fontSize: '10px', padding: '2px var(--space-6)' }}
                      >
                        {item.isReady ? 'Ready' : 'Missing'}
                      </span>
                    </div>

                    <p
                      style={{
                        margin: 'var(--space-4) 0 var(--space-10)',
                        fontSize: 'var(--type-12)',
                        color: 'var(--text-muted)',
                        lineHeight: 1.4,
                      }}
                    >
                      {item.description}
                    </p>

                    <Button
                      type="button"
                      className="text-button"
                      onClick={item.action}
                      style={{
                        fontSize: 'var(--type-12)',
                        minHeight: '26px',
                        padding: '0',
                        fontWeight: 600,
                      }}
                    >
                      {item.actionText} <ArrowRight size={12} />
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <CreateProjectModal
        token={token}
        isOpen={showProjectModal}
        onClose={() => setShowProjectModal(false)}
        onSuccess={(proj) => {
          onProjectCreated(proj);
          void loadPrerequisites();
        }}
      />
    </Card>
  );
}

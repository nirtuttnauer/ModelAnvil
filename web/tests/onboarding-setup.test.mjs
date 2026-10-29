import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  apiRequest,
  apiPage,
  setActiveProjectId,
  getActiveProjectId,
} from '../src/api/client.ts';

const token = 'test-bearer-token';
const originalFetch = globalThis.fetch;
const jsonResponse = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

async function withFetch(fetchImpl, fn) {
  globalThis.fetch = fetchImpl;
  try {
    await fn();
  } finally {
    globalThis.fetch = originalFetch;
    setActiveProjectId(null);
  }
}

test('project scoping attaches X-Project-ID header when active', async () => {
  const projectId = '56997120-befd-4a3f-ad13-5460c4dcbba4';
  let observedHeaders = null;

  await withFetch(
    async (url, init) => {
      observedHeaders = init.headers;
      return jsonResponse({ results: [], next: null });
    },
    async () => {
      setActiveProjectId(projectId);
      assert.equal(getActiveProjectId(), projectId);

      await apiPage('/api/v1/models/', token);
      assert.equal(observedHeaders.get('X-Project-ID'), projectId);
      assert.equal(observedHeaders.get('Authorization'), `Bearer ${token}`);

      // Cleared project scope drops header
      setActiveProjectId(null);
      assert.equal(getActiveProjectId(), null);

      await apiPage('/api/v1/models/', token);
      assert.equal(observedHeaders.has('X-Project-ID'), false);
    }
  );
});

test('project creation endpoint accepts team, name, and slug payload', async () => {
  const newProject = {
    id: 'f87a3120-befd-4a3f-ad13-5460c4dcbba9',
    team: 'abd3a80e-db78-40cc-9bce-b41cd843a199',
    slug: 'experimental-distill',
    name: 'Experimental Distill',
    description: 'Knowledge distillation experiments',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };

  await withFetch(
    async (url, init) => {
      assert.equal(url, '/api/v1/projects/');
      assert.equal(init.method, 'POST');
      const body = JSON.parse(init.body);
      assert.equal(body.name, 'Experimental Distill');
      assert.equal(body.slug, 'experimental-distill');
      assert.equal(body.team, 'abd3a80e-db78-40cc-9bce-b41cd843a199');
      return jsonResponse(newProject, 201);
    },
    async () => {
      const res = await apiRequest('/api/v1/projects/', token, {
        method: 'POST',
        body: JSON.stringify({
          name: 'Experimental Distill',
          slug: 'experimental-distill',
          team: 'abd3a80e-db78-40cc-9bce-b41cd843a199',
          description: 'Knowledge distillation experiments',
        }),
      });
      assert.deepEqual(res, newProject);
    }
  );
});

test('tokenizer registration endpoint accepts name, vocabulary size, and special tokens', async () => {
  const newTok = {
    id: 1,
    tokenizer_id: 'tok-llama-3',
    name: 'Llama-3-Tokenizer',
    vocabulary_size: 128256,
    revision_no: 1,
    special_tokens: { bos_token: '<|begin_of_text|>', eos_token: '<|end_of_text|>' },
    created_at: new Date().toISOString(),
  };

  await withFetch(
    async (url, init) => {
      assert.equal(url, '/api/v1/tokenizers/');
      assert.equal(init.method, 'POST');
      const body = JSON.parse(init.body);
      assert.equal(body.name, 'Llama-3-Tokenizer');
      assert.equal(body.vocabulary_size, 128256);
      assert.deepEqual(body.special_tokens, {
        bos_token: '<|begin_of_text|>',
        eos_token: '<|end_of_text|>',
      });
      return jsonResponse(newTok, 201);
    },
    async () => {
      const res = await apiRequest('/api/v1/tokenizers/', token, {
        method: 'POST',
        body: JSON.stringify({
          name: 'Llama-3-Tokenizer',
          vocabulary_size: 128256,
          special_tokens: {
            bos_token: '<|begin_of_text|>',
            eos_token: '<|end_of_text|>',
          },
        }),
      });
      assert.deepEqual(res, newTok);
    }
  );
});

test('model version registration endpoint accepts model, tokenizer, and architecture ref', async () => {
  const newVersion = {
    id: 1,
    model_version_id: 'mv-llama-8b-r1',
    model: 1,
    tokenizer: 1,
    revision_no: 1,
    architecture_ref: 'modelanvil/llama-3-8b',
    parameters_count: 8030000000,
    state: 'qualified',
    license_evidence: 'apache-2.0',
    created_at: new Date().toISOString(),
  };

  await withFetch(
    async (url, init) => {
      assert.equal(url, '/api/v1/model-versions/');
      assert.equal(init.method, 'POST');
      const body = JSON.parse(init.body);
      assert.equal(body.model, 1);
      assert.equal(body.tokenizer, 1);
      assert.equal(body.revision_no, 1);
      assert.equal(body.architecture_ref, 'modelanvil/llama-3-8b');
      return jsonResponse(newVersion, 201);
    },
    async () => {
      const res = await apiRequest('/api/v1/model-versions/', token, {
        method: 'POST',
        body: JSON.stringify({
          model: 1,
          tokenizer: 1,
          revision_no: 1,
          architecture_ref: 'modelanvil/llama-3-8b',
          parameters_count: 8030000000,
          state: 'qualified',
          license_evidence: 'apache-2.0',
        }),
      });
      assert.deepEqual(res, newVersion);
    }
  );
});

test('workspace topbar includes persistent project selector and scopes views', () => {
  const mainSource = readFileSync(new URL('../src/main.tsx', import.meta.url), 'utf8');

  // Breadcrumbs project selector
  assert.match(mainSource, /<select\s+aria-label="Project"/);
  assert.match(mainSource, /selectProject\(e\.target\.value\)/);
  assert.match(mainSource, /localStorage\.getItem\('modelanvil_active_project'\)/);
  assert.match(mainSource, /localStorage\.setItem\('modelanvil_active_project'/);

  // Switching project resets scoped data
  assert.match(mainSource, /key=\{`\$\{token\}-\$\{activeProjectId\}`\}/);

  // OverviewPage receives activeProject and modal triggers
  assert.match(mainSource, /<OverviewPage[^>]*activeProject=\{activeProject\}/);
  assert.match(mainSource, /onProjectCreated=/);
  assert.match(mainSource, /onPrerequisiteAdded=/);

  // Mounts CreateProjectModal
  assert.match(mainSource, /<CreateProjectModal/);
});

test('overview page mounts onboarding checklist with derived readiness and actionable next step', () => {
  const overviewSource = readFileSync(
    new URL('../src/pages/OverviewPage.tsx', import.meta.url),
    'utf8'
  );
  assert.match(
    overviewSource,
    /import\s+\{\s*OnboardingChecklist\s*\}\s+from\s+['"]\.\.\/components\/OnboardingChecklist['"]/
  );
  assert.match(overviewSource, /<OnboardingChecklist/);

  const checklistSource = readFileSync(
    new URL('../src/components/OnboardingChecklist.tsx', import.meta.url),
    'utf8'
  );
  const readinessSource = readFileSync(
    new URL('../src/components/useSetupReadiness.ts', import.meta.url),
    'utf8'
  );

  // Derives readiness from saved resources through the one shared readiness hook
  assert.match(checklistSource, /useSetupReadiness/);
  assert.match(readinessSource, /\/api\/v1\/dataset-revisions\//);
  assert.match(readinessSource, /\/api\/v1\/tokenizers\//);
  assert.match(readinessSource, /\/api\/v1\/model-versions\//);
  assert.match(readinessSource, /\/api\/v1\/worker-pools\//);
  assert.match(readinessSource, /\/api\/v1\/worker-inventory\//);
  assert.match(readinessSource, /\/api\/v1\/budget-policies\//);

  // Resumable state surviving refresh/reconnect
  assert.match(
    checklistSource,
    /localStorage\.getItem\('modelanvil_onboarding_collapsed'\)/
  );
  assert.match(
    checklistSource,
    /localStorage\.setItem\('modelanvil_onboarding_collapsed'/
  );

  // Keyboard navigation & accessibility
  assert.match(checklistSource, /aria-labelledby="onboarding-heading"/);
  assert.match(checklistSource, /aria-expanded=\{!collapsed\}/);
  assert.match(checklistSource, /aria-controls="onboarding-checklist-body"/);

  // Actionable next step and preflight launch
  assert.match(checklistSource, /Ready to train/);
  assert.match(checklistSource, /Start training/);
  assert.match(checklistSource, /Next action:/);
});

test('the models page provides in-product registration flows without API curl dead-ends', () => {
  const modelsSource = readFileSync(
    new URL('../src/pages/ModelsPage.tsx', import.meta.url),
    'utf8'
  );
  assert.match(modelsSource, /<RegisterTokenizerModal/);
  assert.match(modelsSource, /<RegisterModelVersionModal/);
});

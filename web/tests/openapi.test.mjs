import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const openApiPath = path.resolve(__dirname, '../../contracts/schemas/openapi.json');

test('OpenAPI contract JSON exists and parses valid OpenAPI 3.1', () => {
  assert.ok(fs.existsSync(openApiPath), 'contracts/schemas/openapi.json must exist');
  const raw = fs.readFileSync(openApiPath, 'utf-8');
  const doc = JSON.parse(raw);

  assert.equal(doc.openapi, '3.1.0');
  assert.equal(doc.info.title, 'ModelAnvil Control Plane REST API');
  assert.ok(doc.paths, 'must include paths');
  assert.ok(doc.components, 'must include components');
  assert.ok(doc.components.schemas, 'must include component schemas');
});

test('OpenAPI paths cover all public resource groups', () => {
  const doc = JSON.parse(fs.readFileSync(openApiPath, 'utf-8'));
  const paths = Object.keys(doc.paths);

  const requiredRoutes = [
    '/health/',
    '/ready/',
    '/openapi.json',
    '/tenants/',
    '/users/',
    '/api-keys/',
    '/memberships/',
    '/teams/',
    '/projects/',
    '/team-memberships/',
    '/project-memberships/',
    '/project-configs/',
    '/artifacts/',
    '/datasets/',
    '/datasets/{dataset_id}/prepare/',
    '/dataset-revisions/',
    '/jobs/',
    '/job-attempts/',
    '/budget-policies/',
    '/budget-reservations/',
    '/usage-events/',
    '/audit/',
  ];

  for (const route of requiredRoutes) {
    assert.ok(paths.includes(route), `Route ${route} must be declared in OpenAPI paths`);
  }
});

test('OpenAPI components declare core entity schemas matching client types', () => {
  const doc = JSON.parse(fs.readFileSync(openApiPath, 'utf-8'));
  const schemas = doc.components.schemas;

  const coreEntities = [
    'Tenant',
    'User',
    'ApiKey',
    'Membership',
    'Team',
    'Project',
    'TeamMembership',
    'ProjectMembership',
    'ProjectConfig',
    'Dataset',
    'DatasetRevision',
    'Artifact',
    'Job',
    'JobAttempt',
    'BudgetPolicy',
    'BudgetReservation',
    'UsageEvent',
    'AuditEvent',
    'ApiErrorEnvelope',
  ];

  for (const entity of coreEntities) {
    assert.ok(schemas[entity], `Schema ${entity} must exist in components.schemas`);
    assert.equal(schemas[entity].type, 'object', `${entity} schema must be an object`);
    assert.ok(Array.isArray(schemas[entity].required), `${entity} must declare required fields`);
  }
});

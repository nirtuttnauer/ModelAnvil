import test from 'node:test';
import assert from 'node:assert/strict';
import { evidenceTitle, productionTitle } from '../src/api/evidence-label.ts';

test('evidence labels use the ledger names and keep production closed by default', () => {
  assert.equal(evidenceTitle('integrated_execution'), 'Integrated execution');
  assert.equal(evidenceTitle('simulation'), 'Simulation');
  assert.equal(evidenceTitle('fixture'), 'Simulation');
  assert.equal(evidenceTitle('configuration_only'), 'Configuration only');
  assert.equal(evidenceTitle('hardware_qualified'), 'Hardware qualified');
  assert.equal(evidenceTitle('made-up'), 'Unknown evidence');
  assert.equal(productionTitle(false), 'Production qualification unavailable');
  assert.equal(productionTitle(undefined), 'Production qualification unavailable');
});

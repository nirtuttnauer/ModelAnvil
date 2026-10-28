import test from 'node:test';
import assert from 'node:assert/strict';
import { classificationLabels, classificationStarter, classificationStarterCsv } from '../src/api/classification-starter.ts';

test('classification starter has distinct source groups and balanced exact labels', () => {
  assert.equal(classificationStarter.length, 30);
  assert.equal(new Set(classificationStarter.map(row => row.group_id)).size, 30);
  assert.equal(new Set(classificationStarter.map(row => row.prompt)).size, 30);
  for (const label of classificationLabels) assert.equal(classificationStarter.filter(row => row.response === label).length, 10);
  assert.ok(classificationStarter.every(row => row.prompt.includes('Reply with exactly one label:')));
});

test('CSV quotes multiline prompts and preserves the importer column contract', () => {
  const csv = classificationStarterCsv();
  assert.ok(csv.startsWith('prompt,response,group_id\n"'));
  assert.ok(csv.includes('technical.\nRequest:'));
  assert.equal((csv.match(/"starter-/g) || []).length, 30);
});

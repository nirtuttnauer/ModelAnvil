import test from 'node:test';
import assert from 'node:assert/strict';
import { comparisonInput, matchedBaseModel, sharedOutputLimit, trainedChatModels } from '../src/api/chat-comparison.ts';
const base = { id: 'base', name: 'Base', format: 'cpu-reference', max_tokens: 32, context_limit: 64 };
const trained = { id: 'trained', name: 'Trained', format: 'cpu-reference', base_model_id: 'base', training_run_id: 'run', max_tokens: 256 };
test('base matching uses exact recorded lineage, not names or model order', () => {
  const unrelated = { ...base, id: 'other' };
  assert.equal(matchedBaseModel(trained, [unrelated, trained, base]), base);
  assert.equal(matchedBaseModel(trained, [unrelated, trained]), undefined);
  assert.equal(matchedBaseModel({ ...trained, base_model_id: 'trained' }, [trained]), undefined);
  assert.deepEqual(trainedChatModels([base, unrelated, trained]), [trained]);
  assert.deepEqual(trainedChatModels([{ ...trained, base_model_id: null }]).length, 1);
});
test('each named comparison uses one fresh prompt while ordinary chats keep their conversation', () => {
  const history = [{ role: 'user', content: 'Old prompt' }, { role: 'assistant', content: 'Previous trained answer' }, { role: 'user', content: 'Compare this prompt' }];
  assert.deepEqual(comparisonInput(history, true), [history[2]]);
  assert.equal(comparisonInput(history, false), history);
  assert.deepEqual(comparisonInput([], true), []);
});
test('shared token controls respect both models and their context limits', () => {
  assert.equal(sharedOutputLimit(trained, base), 32);
  assert.equal(sharedOutputLimit(trained, { ...base, max_tokens: 256, context_limit: 24 }), 16);
  assert.equal(sharedOutputLimit(undefined, undefined), 256);
});

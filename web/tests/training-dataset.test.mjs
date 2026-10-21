import test from 'node:test';
import assert from 'node:assert/strict';
import { columnMappingError, mappingFields } from '../src/api/training-dataset.ts';
test('column mapping blocks missing and repeated fields before preview', () => {
  const columns = ['question', 'answer', 'context', 'group'];
  assert.match(columnMappingError({ mode: 'prompt_response' }, columns), /every required/);
  assert.match(columnMappingError({ mode: 'prompt_response', prompt_field: 'question', response_field: 'question' }, columns), /different source column/);
  assert.match(columnMappingError({ mode: 'text', text_field: 'missing' }, columns), /missing from this file/);
  assert.equal(columnMappingError({ mode: 'prompt_response', prompt_field: 'question', response_field: 'answer', context_field: 'context', group_field: 'group' }, columns), null);
  assert.equal(columnMappingError({ mode: 'auto' }, columns), null);
  assert.equal(columnMappingError({ mode: 'text', text_field: 'question' }, columns), null);
});
test('mapping controls expose required targets and optional context/group fields', () => {
  assert.deepEqual(mappingFields('messages').map(field => field.key), ['messages_field', 'group_field']);
  assert.deepEqual(mappingFields('text').map(field => field.key), ['text_field', 'group_field']);
  assert.deepEqual(mappingFields('auto'), []);
  assert.equal(mappingFields('prompt_response').filter(field => field.required).length, 2);
});

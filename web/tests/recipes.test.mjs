import test from 'node:test';
import assert from 'node:assert/strict';
import { starterRecipe, newStep, importRecipe, graphErrors, uploadRecipeSource } from '../src/api/recipes.ts';

test('starter graphs expose typed dependencies and refuse missing or duplicate steps', () => {
  assert.deepEqual(graphErrors(starterRecipe()),[]);
  assert.deepEqual(graphErrors(starterRecipe(false)),[]);
  const graph=starterRecipe();graph.steps[1].input='output';assert.ok(graphErrors(graph).some(s => s.includes('later step')));
  graph.steps[1].id='source';assert.ok(graphErrors(graph).some(s => s.includes('unique')));
  assert.equal(newStep('generate','generate','template').output,'text');
});

test('recipe exports round-trip the definition without source bindings or credentials', () => {
  const recipe=starterRecipe();assert.deepEqual(importRecipe(JSON.stringify(recipe)),recipe);
  assert.throws(() => importRecipe('{"schema":"other","name":"bad","steps":[]}'));
  assert.throws(() => importRecipe('x'.repeat(64001)));
  assert.equal(Object.hasOwn(recipe,'sources'),false);
});

test('recipe source upload preserves bytes and chosen parser and refuses oversized files', async () => {
  const original=globalThis.fetch;const calls=[];
  globalThis.fetch=async (url,init) => {calls.push({url,init});return new Response(JSON.stringify({artifact_id:'source'}),{status:201});};
  try {
    const file=new File(['text\nEngineering note\n'],'notes.csv',{type:'text/csv'});const signal=new AbortController().signal;
    await uploadRecipeSource('token',file,'csv',signal);
    assert.equal(calls[0].url,'/api/v1/recipes/upload-source/');assert.equal(calls[0].init.signal,signal);
    assert.equal(calls[0].init.body.get('format'),'csv');assert.equal(await calls[0].init.body.get('file').text(),await file.text());
    await assert.rejects(uploadRecipeSource('token',new File([new Uint8Array(16*1024**2+1)],'large.json'),'json'));
    assert.equal(calls.length,1);
  } finally {globalThis.fetch=original;}
});

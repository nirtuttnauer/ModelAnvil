import test from 'node:test';
import assert from 'node:assert/strict';
import { comparisonBlockers } from '../src/api/run-comparison.ts';
function run() { return { recipe_type:'full_sft',runtime:{execution_mode:'worker',pins:{runtime:'cpu',contract_digest:'contract',build_digest:'build',dataset_digest:'dataset',tokenizer_digest:'tokenizer',config:{layers:1},validation:{interval:1,digest:'held-out'}}}}; }
test('only the same measured input and validation protocol share loss curves',()=>{
 assert.deepEqual(comparisonBlockers([run(),run()]),[]);
 for(const key of ['runtime','dataset_digest','tokenizer_digest','validation']){const other=run();other.runtime.pins[key]='different';assert.match(comparisonBlockers([run(),other]).join(' '),/differ/);}
 const fixture=run();fixture.runtime.execution_mode='simulation';assert.match(comparisonBlockers([run(),fixture])[0],/Synthetic/);
 const missing=run();delete missing.runtime.pins.validation;assert.match(comparisonBlockers([run(),missing]).join(' '),/unreported/);
});

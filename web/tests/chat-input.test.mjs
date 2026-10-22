import test from 'node:test';
import assert from 'node:assert/strict';
import { modelDisplayName, referenceInputError } from '../src/api/chat-input.ts';
test('guided candidates have readable names without changing other model names', () => {
 assert.equal(modelDisplayName('smollm2-gpu-sft-a83fc687-c592-44bf-a7ff-dc114baa4773'), 'SmolLM2 fine-tune · a83fc687');
 assert.equal(modelDisplayName('My custom model'), 'My custom model');
 assert.equal(modelDisplayName('smollm2-gpu-sft-custom'), 'smollm2-gpu-sft-custom');
 assert.equal(modelDisplayName('Managed SmolLM2-1.7B-Instruct · aae63eae-caeb-4ed2-8e56-f0df9888a766'), 'SmolLM2-1.7B Instruct');
 assert.equal(modelDisplayName('Managed SmolLM2-135M-Instruct · aae63eae-caeb-4ed2-8e56-f0df9888a766'), 'SmolLM2-135M Instruct');
 assert.equal(modelDisplayName('Managed custom model'), 'Managed custom model');
});
test('CPU character and UTF-8 byte context counts include BOS/EOS and output reserve',()=>{
 const model={format:'cpu-reference',tokenizer_kind:'character-v1',context_limit:8};
 assert.equal(referenceInputError(model,[{role:'user',content:'abc'}],3,0,'plain'),null);
 assert.match(referenceInputError(model,[{role:'user',content:'abc'}],4,0,'plain'),/5 tokens/);
 assert.equal(referenceInputError({...model,tokenizer_kind:'byte-v1'},[{role:'user',content:'é'}],4,0,'plain'),null);
 assert.match(referenceInputError({...model,tokenizer_kind:'byte-v1'},[{role:'user',content:'é'}],5,0,'plain'),/4 tokens/);
 assert.match(referenceInputError(model,[{role:'system',content:'rules'},{role:'user',content:'abc'}],1,0,'plain'),/one user prompt/);
 assert.match(referenceInputError(model,[{role:'user',content:'a'}],1,1,'plain'),/greedy/);
 assert.equal(referenceInputError({format:'safetensors'},[{role:'user',content:'text'}],128,0,'model'),null);
});

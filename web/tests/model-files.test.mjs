import test from 'node:test';
import assert from 'node:assert/strict';
import { savedModelFiles, validateModelFiles } from '../src/api/model-files.ts';
const ref={artifact_id:'11111111-1111-4111-8111-111111111111',sha256:'a'.repeat(64),byte_size:50};
test('verified model references restore without file contents or extra credential fields',()=>{
 assert.deepEqual(savedModelFiles(JSON.stringify({'model.gguf':ref})),{'model.gguf':ref});
 for(const value of ['{',JSON.stringify({'../model.gguf':ref}),JSON.stringify({'model.gguf':{...ref,credential:'secret'}})])assert.deepEqual(savedModelFiles(value),{});
});
test('model snapshots fail early on missing assets, duplicate names and oversized files',()=>{
 assert.doesNotThrow(()=>validateModelFiles([{name:'model.gguf',size:8}],{}));
 assert.doesNotThrow(()=>validateModelFiles([{name:'model.safetensors',size:8},{name:'config.json',size:8},{name:'tokenizer.json',size:8}],{}));
 assert.throws(()=>validateModelFiles([{name:'model.safetensors',size:8}],{}),/requires/);
 assert.throws(()=>validateModelFiles([{name:'model.gguf',size:8}],{'model.gguf':ref}),/already verified/);
 assert.throws(()=>validateModelFiles([{name:'model.gguf',size:9*1024**3}],{}),/GiB/);
});

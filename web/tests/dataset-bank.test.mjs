import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { build } from 'rolldown';
const bundle = await build({ input: fileURLToPath(new URL('../src/pages/DatasetBankPage.tsx', import.meta.url)), external: () => true, output: { format: 'cjs' }, write: false });
const compiled = bundle.output.find(item => item.type === 'chunk').code;
const source = { id:'qualified-source', name:'Verified source', category:'text', source_kind:'repository', description:'Actual source', source_url:'https://example.org', modalities:['text'], use_cases:['training'], license:'MIT', eligibility:'eligible', download_enabled:true, acquisition_available:true, pinned_revision:'abcdef', size_bytes:42, is_size_measured:true, acquisition_record_limit:2 };
const policy = { policy_id:'policy-1', name:'Records', unit:'bank_acquisition_records', currency:'', enabled:true };
const acquisition = { snapshot_id:'snapshot-1', source_id:source.id, source_revision:'abcdef', state:'failed', verified_records:1, planned_records:2, transferred_bytes:21, planned_bytes:42, revision_id:null, revision_no:null, row_count:null, failures:[], job:null };
const flush = () => new Promise(resolve => setImmediate(resolve));
function deferred() { let resolve; const promise = new Promise(done => { resolve=done; }); return {promise,resolve}; }
async function fixture({policies=[], policyId='', estimate='', existing=null, bankSource=source, downloadScope='sample', storageQuota='', consent=false, pending=false, budgetFailure=false}={}) {
  let stateIndex=0,refIndex=0,mounted=false,callbacks=0;
  const states=[],refs=[],effects=[],cleanups=[],calls=[];
  const draftValues={query:'',selectedModality:'all',selectedId:source.id,budgetPolicyId:policyId,estimatedAmount:estimate,shareAlikeSourceId:consent?source.id:'',downloadScope,storageQuota,recordLimit:''};
  const wait=deferred(); const jsx=(type,props)=>({type,props});
  const React={useState(initial){const i=stateIndex++;if(!(i in states))states[i]=initial;return [states[i],value=>{states[i]=typeof value==='function'?value(states[i]):value;}];},useRef(initial){const i=refIndex++;return refs[i]??=( {current:initial});},useEffect(fn){if(!mounted)effects.push(fn);},createElement:(type,props,...children)=>jsx(type,{...props,children})};
  const module={exports:{}};
  vm.runInNewContext(compiled,{module,exports:module.exports,AbortController,console,require(name){
    if(name==='react')return React;
    if(name==='react/jsx-runtime')return {jsx,jsxs:jsx};
    // This fixture tests acquisition behavior through the shared button boundary.
    if(name.endsWith('/components/ui'))return {Button:'button'};
    if(name.endsWith('/components/Draft'))return {useDraft:()=>({field:key=>[draftValues[key],value=>{draftValues[key]=typeof value==='function'?value(draftValues[key]):value;}],status:'empty',restore(){},discard(){}}),DraftStatus:'DraftStatus'};
    if(name.endsWith('/api/resource-routes'))return {resourceHash:(kind,id)=>`#resources/${kind}/${id}`};
    if(name.endsWith('/api/runs'))return {runHash:(kind,id)=>`#runs/${kind}/${id}`};
    if(name.endsWith('/api/resources'))return {allResources(path){if(path.includes('budget')&&budgetFailure)return Promise.reject(new Error('Budget query failed'));return Promise.resolve(path.includes('budget')?policies:existing?[existing]:[]);}};
    if(name.endsWith('/api/client'))return {errorMessage:e=>e.message,apiRequest(path,token,init={}){calls.push({path,token,init});
      if(path.endsWith('/sources/'))return Promise.resolve({sources:[bankSource]});
      if(path.includes('/preview/'))return Promise.resolve({samples:[{text:'real source fixture'}],source_revision:'abcdef'});
      if(path.endsWith(`/sources/${source.id}/`))return Promise.resolve({obligations:{retain_notices:true}});
      if(path.includes('/preflight/'))return pending?wait.promise:Promise.resolve({status:'approved'});
      if(path.includes('/acquisitions/'))return Promise.resolve({...acquisition,state:'ingesting'});
      throw new Error(path);
    }};
    return new Proxy({}, {get:(_,key)=>key});
  }});
  function render(){stateIndex=0;refIndex=0;return module.exports.DatasetBankPage({token:'credential-never-in-body',onImportSuccess(){callbacks++;}});}
  render();mounted=true;for(const effect of effects)cleanups.push(effect());await flush();
  function find(node,text){if(!node||typeof node!=='object')return; if(node.type==='button'&&JSON.stringify(node.props.children).includes(text))return node;for(const child of [node.props?.children].flat(Infinity)){const found=find(child,text);if(found)return found;}}
  return {calls,wait,callbacks:()=>callbacks,button:text=>{const button=find(render(),text);assert.ok(button,text);return button;},async click(text){const button=find(render(),text);assert.ok(button,text);button.props.onClick();await flush();},unmount(){cleanups.forEach(fn=>fn?.());}};
}
test('review fetches actual samples and obligations; confirmation freezes exact revision and budget',async()=>{
 const f=await fixture({policies:[policy],policyId:policy.policy_id,estimate:'12.345678'});
 await f.click('Review acquisition');assert(f.calls.some(c=>c.path.includes('/preview/')));assert.equal(f.calls.filter(c=>c.init.method==='POST'&&c.path.endsWith('/acquisitions/')).length,0);
 await f.click('Confirm and acquire');const launch=f.calls.find(c=>c.init.method==='POST'&&c.path.endsWith('/acquisitions/'));assert(launch);
 assert.deepEqual(JSON.parse(launch.init.body),{budget_policy_id:policy.policy_id,estimated_amount:'12.345678',source_revision:'abcdef'});assert(!launch.init.body.includes('credential-never-in-body'));f.unmount();
});
test('missing budgets, invalid estimates, share-alike consent and unavailable connectors block review',async()=>{
 for(const options of [{policies:[policy]},{policies:[policy],policyId:policy.policy_id,estimate:'NaN'},{budgetFailure:true},{bankSource:{...source,eligibility:'opt_in_required'}},{bankSource:{...source,acquisition_available:false}}]){
  const f=await fixture(options);assert.equal(f.button('Review acquisition').props.disabled,true);await f.click('Review acquisition');assert(!f.calls.some(c=>c.path.includes('/preflight/')));f.unmount();
 }
});
test('full release confirmation sends measured storage quota and selected scope',async()=>{
 const bankSource={...source,full_acquisition_available:true,full_acquisition:{pinned_revision:'full-pin',measured_selected_bytes:100,record_limit:2}};
 const f=await fixture({bankSource,downloadScope:'full'});await f.click('Review acquisition');await f.click('Confirm and acquire');const launch=f.calls.find(c=>c.init.method==='POST'&&c.path.endsWith('/acquisitions/'));
 assert.deepEqual(JSON.parse(launch.init.body),{download_scope:'full',project_policy:{max_storage_quota_bytes:200},source_revision:'full-pin'});f.unmount();
});
test('server history restores a failed acquisition and resume sends its selected remaining reservation',async()=>{
 const f=await fixture({existing:acquisition,policies:[policy],policyId:policy.policy_id,estimate:'1'});assert.equal(f.button('Resume transfer').props.disabled,false);await f.click('Resume transfer');
 const call=f.calls.find(c=>c.path.endsWith('/resume/'));assert.deepEqual(JSON.parse(call.init.body),{budget_policy_id:policy.policy_id,estimated_amount:'1'});f.unmount();
});
test('unmount aborts an in-flight review and prevents later launch or callbacks',async()=>{
 const f=await fixture({pending:true});await f.click('Review acquisition');const request=f.calls.find(c=>c.path.includes('/preflight/'));f.unmount();assert(request.init.signal.aborted);f.wait.resolve({status:'approved'});await flush();assert(!f.calls.some(c=>c.init.method==='POST'&&c.path.endsWith('/acquisitions/')));assert.equal(f.callbacks(),0);
});

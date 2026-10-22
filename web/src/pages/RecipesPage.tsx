import { Identifier } from '../components/Identifier';
import { Button, Card, Field, MultilineField, Notice } from '../components/ui';
import { useEffect, useRef, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { allResources } from '../api/resources';
import { resourceHash } from '../api/resource-routes';
import { graphErrors, importRecipe, newStep, starterRecipe, uploadRecipeSource, type RecipeDefinition, type RecipeKind, type RecipeRun, type RecipeStep } from '../api/recipes';
import './ml-pages.css';
import './recipes.css';

export function RecipesPage({token,refreshKey}: {token:string;refreshKey?:number}) {
  const [recipe,setRecipe] = useState<RecipeDefinition>(() => starterRecipe());
  const [version,setVersion] = useState(''); const [versions,setVersions] = useState<{artifact_id:string;name:string;sha256:string}[]>([]);
  const [files,setFiles] = useState<Record<string,File>>({}); const [sources,setSources] = useState<Record<string,string>>({});
  const [models,setModels] = useState<{id:string;name:string}[]>([]); const [model,setModel] = useState(''); const [device,setDevice] = useState('mps:0');
  const [pools,setPools] = useState<{id:number;name:string}[]>([]); const [pool,setPool] = useState('');
  const [policies,setPolicies] = useState<{policy_id:string;name:string}[]>([]); const [policy,setPolicy] = useState('');
  const [datasets,setDatasets] = useState<{dataset_id:string;name:string}[]>([]); const [dataset,setDataset] = useState('');
  const [recent,setRecent] = useState<RecipeRun[]>([]); const [selected,setSelected] = useState(''); const [status,setStatus] = useState<RecipeRun|null>(null);
  const [protectedSources,setProtectedSources] = useState<string[]>([]);
  const [protectedOptions,setProtectedOptions] = useState<{artifact_id:string;object_key:string;sha256:string;metadata:{kind?:string}}[]>([]);
  const [preview,setPreview] = useState(''); const [reviewed,setReviewed] = useState(false); const [addType,setAddType] = useState<RecipeKind>('validate');
  const [busy,setBusy] = useState(false); const [error,setError] = useState(''); const [notice,setNotice] = useState('');
  const lock = useRef(false); const delivery = useRef(''); const ordinal = useRef(1);
  const needsModel = recipe.steps.some(s => s.type === 'generate'); const errors = graphErrors(recipe);

  useEffect(() => {
    if (!token.trim()) return;
    const c = new AbortController();
    void Promise.all([
      apiRequest<typeof versions>('/api/v1/recipes/',token,{signal:c.signal}),
      apiRequest<{data:typeof models}>('/api/v1/inference/models/',token,{signal:c.signal}),
      allResources<{id:number;name:string;status:string}>('/api/v1/worker-pools/',token,c.signal),
      allResources<{policy_id:string;name:string;unit:string;enabled:boolean;currency:string}>('/api/v1/budget-policies/',token,c.signal),
      allResources<{dataset_id:string;name:string}>('/api/v1/datasets/',token,c.signal),
      allResources<{artifact_id:string;object_key:string;sha256:string;media_type:string;metadata:{kind?:string}}>('/api/v1/artifacts/',token,c.signal),
    ]).then(([v,m,p,b,d,a]) => {if (!c.signal.aborted) {
      setVersions(v);setModels(m.data);setPools(p.filter(x => x.status === 'active'));
      setPolicies(b.filter(x => x.enabled && x.unit === 'recipe_attempts' && !x.currency));setDatasets(d);
      setProtectedOptions(a.filter(x => x.media_type==='application/x-ndjson' || x.metadata.kind==='prepared_dataset'));
    }}).catch(e => {if (!c.signal.aborted) setError(errorMessage(e));});
    return () => c.abort();
  },[token,refreshKey]);

  useEffect(() => {
    if (!token.trim()) return;
    const c = new AbortController();let timer:ReturnType<typeof setTimeout>;
    delivery.current='';setStatus(null);
    async function poll() {
      try {
        const list = await apiRequest<RecipeRun[]>('/api/v1/recipes/runs/',token,{signal:c.signal});
        const run = selected ? await apiRequest<RecipeRun>(`/api/v1/recipes/runs/${selected}/`,token,{signal:c.signal}) : null;
        if (c.signal.aborted) return;
        setRecent(list);setStatus(run);
        if (run?.result && delivery.current !== run.run_id) {
          delivery.current = run.run_id;
          setRecipe(run.definition);setVersion(run.bindings.recipe);setSources(run.bindings.sources);
          setModel(run.bindings.model || '');setDevice(run.bindings.device);setPool(String(run.bindings.pool));setPolicy(run.bindings.budget_policy);
          setProtectedSources(run.bindings.protected_sources);setPreview(run.preview ? run.run_id : '');setReviewed(false);
        }
      } catch(e) {if (!c.signal.aborted) setError(errorMessage(e));}
      if (!c.signal.aborted) timer=setTimeout(() => void poll(),2500);
    }
    void poll();return () => {c.abort();clearTimeout(timer);};
  },[token,selected]);

  function change(next:RecipeDefinition) {
    const reusable = new Set(next.steps.filter(s => s.type==='source' && recipe.steps.some(old => old.type==='source' && old.id===s.id && old.format===s.format)).map(s => s.id));
    setSources(current => Object.fromEntries(Object.entries(current).filter(([id]) => reusable.has(id))));
    setFiles(current => Object.fromEntries(Object.entries(current).filter(([id]) => reusable.has(id))));
    setRecipe(next);setVersion('');setPreview('');setReviewed(false);setSelected('');setNotice('');
  }
  function update(index:number,fields:Partial<RecipeStep>) {
    const steps=recipe.steps.map((s,i) => i===index ? {...s,...fields} : s);change({...recipe,steps});
  }
  async function operation(action:()=>Promise<void>) {
    if (lock.current) return;lock.current=true;setBusy(true);setError('');setNotice('');
    try {await action();} catch(e) {setError(errorMessage(e));} finally {setBusy(false);lock.current=false;}
  }
  async function save() {
    const ref = await apiRequest<{artifact_id:string;sha256:string}>('/api/v1/recipes/',token,{method:'POST',body:JSON.stringify(recipe)});
    setVersion(ref.artifact_id);setVersions(current => [{...ref,name:recipe.name},...current.filter(v => v.artifact_id !== ref.artifact_id)]);
    return ref.artifact_id;
  }
  function queue(isPreview:boolean) {
    void operation(async () => {
      const recipeId=version || await save();const refs={...sources};
      for (const step of recipe.steps.filter(s => s.type==='source')) {
        if (!Object.hasOwn(refs,step.id)) {
          if (!Object.hasOwn(files,step.id)) throw new Error(`Choose the source for ${step.id}.`);
          refs[step.id]=(await uploadRecipeSource(token,files[step.id],step.format || 'json')).artifact_id;
        }
      }
      setSources(refs);
      const run=await apiRequest<RecipeRun>('/api/v1/recipes/runs/',token,{method:'POST',body:JSON.stringify({recipe:recipeId,sources:refs,
        ...(needsModel ? {model} : {}),device:needsModel ? device : 'cpu',pool:Number(pool),budget_policy:policy,
        idempotency_key:crypto.randomUUID(),preview:isPreview,protected_sources:protectedSources,
        ...(!isPreview ? {dataset,preview_run:preview,reviewed_preview:reviewed} : {})})});
      setSelected(run.run_id);setNotice(`${isPreview ? 'Preview' : 'Full recipe'} queued as job ${run.job_id}.`);
    });
  }
  const canQueue=token.trim() && pool && policy && !errors.length && (!needsModel || model) && recipe.steps.filter(s => s.type==='source').every(s => Object.hasOwn(sources,s.id) || Object.hasOwn(files,s.id));

  return <div className="data-workspace ml-page recipe-page">
    {error && <Notice tone="error" role="alert">{error}</Notice>}{notice && <Notice tone="success" role="status">{notice}</Notice>}
    <Card className="panel ml-main-panel">
      <div className="panel-body">
        <fieldset disabled={busy} className="recipe-toolbar">
          <Button onClick={() => change(starterRecipe(false))}>Prepare documents</Button><Button onClick={() => change(starterRecipe())}>Generate summaries</Button>
          <label>Import recipe JSON<input type="file" accept="application/json" onChange={e => {
            const file=e.target.files?.[0];if (file) void operation(async () => {if (file.size>64000) throw new Error('Recipe import exceeds 64,000 bytes.');change(importRecipe(await file.text()));setSources({});setFiles({});});
          }} /></label>
          <Button onClick={() => {
            const url=URL.createObjectURL(new Blob([JSON.stringify(recipe,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='modelanvil-recipe.json';link.click();setTimeout(() => URL.revokeObjectURL(url),1000);
          }}>Export definition</Button>
          <label>Saved versions<select value={version} onChange={e => void operation(async () => {
            const id=e.target.value;if (!id) return;
            const v=await apiRequest<{definition:RecipeDefinition}>(`/api/v1/recipes/versions/${id}/`,token);change(v.definition);setVersion(id);setSources({});setFiles({});
          })}><option value="">Select a version</option>{versions.map((v, index) => <option key={v.artifact_id} value={v.artifact_id}>{v.name} · version {index + 1}</option>)}</select></label>
        </fieldset>
        <label>Recipe name<Field disabled={busy} maxLength={100} value={recipe.name} onChange={e => change({...recipe,name:e.target.value})} /></label>
        <div className="recipe-editor">
          <details className="workspace-details recipe-map"><summary>Recipe dependency map</summary>
          <svg className="recipe-graph" role="img" aria-label="Recipe dependencies; editable list follows" viewBox={`0 0 480 ${recipe.steps.length*72}`}>
            {recipe.steps.map((step,i) => <g key={i}>
              {(step.type==='merge' ? step.inputs || [] : step.input ? [step.input] : []).map(input => {
                const parent=recipe.steps.findIndex(s => s.id===input);return parent>=0 ? <path key={input} d={`M 240 ${parent*72+48} C 450 ${parent*72+55},450 ${i*72-7},240 ${i*72}`} /> : null;
              })}
              <rect x={70} y={i*72} width={340} height={48} rx={8} /><text x={85} y={i*72+29}>{step.id} · {step.type}</text>
            </g>)}
          </svg>
          </details>
          <ol className="recipe-step-list">{recipe.steps.map((step,index) => <li key={index}>
            <details open={index === 0}><summary>{index+1}. {step.type} · {step.id}</summary>
            <fieldset disabled={busy}><legend>{index+1}. {step.type}</legend>
              <label>Step ID<Field value={step.id} pattern="[a-z][a-z0-9_\-]{0,31}" onChange={e => update(index,{id:e.target.value})} /></label>
              {step.type!=='source' && step.type!=='merge' && <label>Input step<select value={step.input || ''} onChange={e => update(index,{input:e.target.value})}><option value="">Select an earlier step</option>{recipe.steps.slice(0,index).map((s,i) => <option key={i} value={s.id}>{s.id} · {s.type}</option>)}</select></label>}
              {step.type==='source' && <>
                <label>Source format<select value={step.format} onChange={e => {update(index,{format:e.target.value,...(['docx','pdf'].includes(e.target.value) ? {text_field:'text',group_field:null} : {})});setSources(current => {const next={...current};delete next[step.id];return next;});}}>{['json','csv','jsonl','docx','pdf'].map(f => <option key={f}>{f}</option>)}</select></label>
                {['json','csv'].includes(step.format || '') && <label>Text field<Field value={step.text_field || 'text'} onChange={e => update(index,{text_field:e.target.value})} /></label>}
                <label>Source file<input type="file" onChange={e => {
                  const f=e.target.files?.[0];if (f) {setFiles(current => ({...current,[step.id]:f}));setSources(current => {const next={...current};delete next[step.id];return next;});setPreview('');setSelected('');setReviewed(false);}
                }} /></label>{Object.hasOwn(sources,step.id) && <small>Bound source {sources[step.id]}</small>}
              </>}
              {step.type==='sample' && <><label>Sample limit<Field type="number" min={1} max={32} value={step.limit} onChange={e => update(index,{limit:Number(e.target.value)})} /></label><label>Sampler seed<Field type="number" min={0} value={step.seed} onChange={e => update(index,{seed:Number(e.target.value)})} /></label></>}
              {step.type==='expression' && <><label>Text operation<select value={step.operation} onChange={e => update(index,{operation:e.target.value})}>{['strip','lower','upper','replace'].map(v => <option key={v}>{v}</option>)}</select></label>{step.operation==='replace' && <><label>Find literal<Field value={step.find || ''} onChange={e => update(index,{find:e.target.value})} /></label><label>Replacement<Field value={step.replace || ''} onChange={e => update(index,{replace:e.target.value})} /></label></>}</>}
              {step.type==='template' && <label>Prompt template<MultilineField rows={3} value={step.template} onChange={e => update(index,{template:e.target.value})} /><small>Literal placeholders: {'{{value}}'} and {'{{source}}'}.</small></label>}
              {step.type==='generate' && <><label>Generated output<select value={step.output} onChange={e => update(index,{output:e.target.value})}><option value="text">Text</option><option value="json">Finite JSON</option><option value="code">Python code</option></select></label><label>Maximum new tokens<Field type="number" min={1} max={256} value={step.max_tokens} onChange={e => update(index,{max_tokens:Number(e.target.value)})} /></label><label>Generation seed<Field type="number" min={0} value={step.seed} onChange={e => update(index,{seed:Number(e.target.value)})} /></label><small>JSON must parse completely. Python output is checked for syntax and kept as data.</small></>}
              {step.type==='validate' && <><label>Minimum characters<Field type="number" min={0} value={step.min_characters || 0} onChange={e => update(index,{min_characters:Number(e.target.value)})} /></label><label>Required literals, one per line<MultilineField value={(step.contains || []).join('\n')} onChange={e => update(index,{contains:e.target.value.split('\n').filter(Boolean)})} /></label><label>Required JSON keys, one per line<MultilineField value={(step.required_keys || []).join('\n')} onChange={e => update(index,{required_keys:e.target.value.split('\n').filter(Boolean)})} /></label></>}
              {step.type==='merge' && <div>Merge inputs{recipe.steps.slice(0,index).map((s,i) => <label key={i} className="checkbox-label"><input type="checkbox" checked={step.inputs?.includes(s.id) || false} onChange={e => update(index,{inputs:e.target.checked ? [...step.inputs || [],s.id] : step.inputs?.filter(v => v!==s.id)})} />{s.id}</label>)}</div>}
              {step.type!=='output' && <Button onClick={() => change({...recipe,steps:recipe.steps.filter((_,i) => i!==index)})}>Remove step {index+1}</Button>}
            </fieldset></details>
          </li>)}</ol>
        </div>
        {errors.length>0 && <ul role="alert">{errors.map((message,i) => <li key={i}>{message}</li>)}</ul>}
        <fieldset disabled={busy} className="recipe-toolbar"><label>Add a step<select value={addType} onChange={e => setAddType(e.target.value as RecipeKind)}>{['source','sample','expression','template','generate','validate','merge'].map(v => <option key={v}>{v}</option>)}</select></label>
          <Button disabled={recipe.steps.length>=12} onClick={() => {const steps=[...recipe.steps];const next=newStep(addType,`step_${ordinal.current++}`,steps.at(-2)?.id || '');steps.splice(steps.length-1,0,next);steps[steps.length-1]={...steps.at(-1)!,input:next.id};change({...recipe,steps});}}>Add step</Button>
          <Button disabled={Boolean(errors.length)} onClick={() => void operation(async () => {await save();setNotice('Saved immutable recipe version.');})}>Save version</Button>
        </fieldset>
        <fieldset disabled={busy} className="form-grid recipe-execution">
          {needsModel && <><label>Local generator<select value={model} onChange={e => {setModel(e.target.value);setPreview('');setReviewed(false);}}><option value="">Select a local model</option>{models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label><label>Generation device<select value={device} onChange={e => {setDevice(e.target.value);setPreview('');setReviewed(false);}}><option value="mps:0">Apple GPU</option><option value="cpu">CPU</option><option value="mlx:0">MLX Metal</option></select></label></>}
          <label>Recipe worker pool<select value={pool} onChange={e => setPool(e.target.value)}><option value="">Select a pool</option>{pools.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
          <label>Recipe attempt quota<select value={policy} onChange={e => setPolicy(e.target.value)}><option value="">Select a recipe_attempts quota</option>{policies.map(p => <option key={p.policy_id} value={p.policy_id}>{p.name}</option>)}</select></label>
          <p className="full-width muted">Three attempts are reserved per run. Previews generate at most three rows per step; full generation uses at most 32. Completed step and row checkpoints survive worker interruption. Privacy, deduplication and protected-source checks run before generation and publication.</p>
          <label className="full-width">Protected sources and held-out manifests<select multiple value={protectedSources} onChange={e => {setProtectedSources([...e.target.selectedOptions].map(o => o.value));setPreview('');setReviewed(false);}}>{protectedOptions.map((a, index) => <option key={a.artifact_id} value={a.artifact_id}>{a.metadata.kind || 'Canonical source'} · source {index + 1}</option>)}</select><small>Canonical sources exclude their complete source groups. Prepared manifests exclude validation/test groups.</small></label>
          <Button disabled={!canQueue} onClick={() => queue(true)}>Queue preview</Button>
          <label>Output dataset<select value={dataset} onChange={e => setDataset(e.target.value)}><option value="">Select a dataset</option>{datasets.map(d => <option key={d.dataset_id} value={d.dataset_id}>{d.name}</option>)}</select></label>
          <label className="checkbox-label"><input type="checkbox" checked={reviewed} disabled={!preview} onChange={e => setReviewed(e.target.checked)} />I reviewed the matching preview and rejections.</label>
          <Button disabled={!canQueue || !preview || !reviewed || !dataset} onClick={() => queue(false)}>Run and publish recipe</Button>
        </fieldset>
        <section className="detail-box"><h3>Recipe executions <Identifier value={selected} label="Recipe run ID" /></h3><label>Recent recipe runs<select value={selected} onChange={e => {setSelected(e.target.value);setReviewed(false);}}><option value="">Select a run</option>{recent.map((r, index) => <option key={r.run_id} value={r.run_id}>{r.preview ? 'Preview' : 'Full run'} {index + 1} · {r.status}</option>)}</select></label>
          {status && <><p role="status">{status.status} · attempt {status.attempt_count} of {status.max_attempts} · {status.completed_steps.length} steps and {status.saved_rows} row checkpoints saved</p>
            <span>Job <Identifier value={status.job_id} label="Job ID" /></span>{status.error && <p role="alert">{status.error}</p>}
            <div className="recipe-toolbar"><Button disabled={busy || !['queued','running','interrupted'].includes(status.status) || status.desired_action==='cancel'} onClick={() => void operation(async () => {await apiRequest(`/api/v1/recipes/runs/${selected}/cancel/`,token,{method:'POST'});})}>Cancel recipe run</Button>
              <Button disabled={busy || !['failed','interrupted'].includes(status.status) || status.desired_action==='cancel' || status.attempt_count>=status.max_attempts} onClick={() => void operation(async () => {await apiRequest(`/api/v1/recipes/runs/${selected}/retry/`,token,{method:'POST'});})}>Retry recipe run</Button></div>
            {status.result && <><h4>{status.publication.row_count} accepted · {status.publication.rejected_count} rejected</h4>{status.publication.usage && <p>{status.publication.usage.completed_generation_calls} completed generation calls · {status.publication.usage.total_tokens} measured tokens</p>}{status.publication.revision_id && <p>Published immutable revision {status.publication.revision_id}. <a href={resourceHash('dataset-revision', status.publication.revision_id)}>Inspect published dataset</a></p>}<details open><summary>Accepted rows and origins</summary><pre tabIndex={0} aria-label="Accepted recipe rows and origins">{JSON.stringify(status.result.rows,null,2)}</pre></details><details><summary>Rejections and measured generation usage</summary><pre tabIndex={0} aria-label="Recipe rejections and usage">{JSON.stringify(status.result.rejected,null,2)}</pre></details></>}
          </>}
        </section>
      </div>
    </Card>
  </div>;
}

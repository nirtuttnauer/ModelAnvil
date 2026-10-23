"""Bounded, actual CPU-reference context experiments. No task-quality fixtures."""
import hashlib
import json
import platform
import sys
from django.db import transaction
from modelanvil.context_lab.compiler import ContextCompiler, ContextOverflowError
from modelanvil.context_lab.models import ContextExperiment
from modelanvil.core.tenancy import get_active_project, get_active_tenant
from modelanvil.identity.models import check_resource_access
from modelanvil.runners import inference
from modelanvil.runners.local_execution import load_reference_bundle
from modelanvil.runners.training import runtime, general_runtime

TEMPLATE = 'context-role-lines-v1'
ROLE_LINE = '{role}: {content}\n'
GENERATION_PREFIX = 'assistant: '


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def model_codec(model):
    tenant,project=get_active_tenant(),get_active_project()
    bundle,artifact,_=load_reference_bundle(model,tenant=tenant,project=project)
    spec=bundle['tokenizer_config.json']
    module=runtime if model.architecture_ref==runtime.RUNTIME_ID else general_runtime
    count=lambda text:len(module.encode(text,spec,enforce_limit=False))
    pins={'model_version_id':str(model.model_version_id),'model_artifact_id':str(artifact.artifact_id),
        'model_sha256':artifact.sha256,'model_bytes':artifact.byte_size,'tokenizer_id':str(model.tokenizer.tokenizer_id),
        'tokenizer_digest':digest(spec),'runtime':model.architecture_ref,
        'runtime_contract':runtime.CONTRACT_DIGEST if model.architecture_ref==runtime.RUNTIME_ID else general_runtime.CONTRACT_DIGEST,
        'template':TEMPLATE,'template_digest':digest({'id':TEMPLATE,'role_line':ROLE_LINE,'generation_prefix':GENERATION_PREFIX})}
    return pins,count,min(64,bundle['config.json'].get('context_window',64))


def serialize(blocks):
    return ''.join(ROLE_LINE.format(role=b.role,content=b.rendered_content) for b in blocks)+GENERATION_PREFIX


def pinned_compiler(version):
    if not check_resource_access(version) or not check_resource_access(version.recipe):
        raise ValueError('Recipe is outside the current project.')
    if not version.model_version_id:
        return ContextCompiler(version)
    pins,count,limit=model_codec(version.model_version)
    if pins!=version.runtime_pins or version.chat_template!=TEMPLATE or version.tokenizer_ref!=pins['tokenizer_id']:
        raise ValueError('Pinned model, tokenizer or template changed. Save a new recipe revision.')
    if version.model_limit_tokens>limit or not 1<=version.output_reserve_tokens<=32:
        raise ValueError(f'This CPU runtime requires a model limit at most {limit} and 1–32 output tokens.')
    return ContextCompiler(version,token_counter=count,serializer=serialize)


def recipe_pin(version):
    return digest({'version_id':str(version.recipe_version_id),'limit':version.model_limit_tokens,
        'reserve':version.output_reserve_tokens,'policy':version.budget_policy,'pins':version.runtime_pins,
        'blocks':list(version.blocks.order_by('order','priority','block_key').values('block_key','block_type','role','order','priority','max_tokens','content_template'))})


def visible_experiment(experiment):
    details=experiment.details
    if details.get('origin')!='actual_cpu_reference':
        return True
    from modelanvil.context_lab.models import ContextRecipeVersion
    if not isinstance(details.get('recipes'),list) or len(details['recipes'])!=2:
        return False
    for row in details['recipes']:
        if not isinstance(row,dict) or not row.get('version_id') or not row.get('digest'):
            return False
        version=ContextRecipeVersion.all_objects.filter(recipe_version_id=row['version_id'],tenant_id=experiment.tenant_id).first()
        if version is None or not check_resource_access(version) or not check_resource_access(version.recipe) or recipe_pin(version)!=row['digest']:
            return False
        try:pinned_compiler(version)
        except ValueError:return False
    return True


@transaction.atomic
def run_pair(version,baseline,*,name,cases,seed):
    if not version.model_version_id or version.runtime_pins!=baseline.runtime_pins or version.output_reserve_tokens!=baseline.output_reserve_tokens:
        raise ValueError('Pair recipes pinned to the same verified CPU model/tokenizer/template and output reserve.')
    compilers=[pinned_compiler(v) for v in (baseline,version)]
    rows=[]
    with inference.local_session(version.model_version,tenant=get_active_tenant(),project=get_active_project(),device='cpu') as session:
        for number,case in enumerate(cases):
            variants=[]
            for recipe,compiler in zip((baseline,version),compilers):
                try:
                    compiled=compiler.compile(case['variables'])
                    if not compiled.included_blocks:raise ValueError('No context blocks remain after compilation.')
                    output='';finish=None
                    for event in inference.generate(session,[{'role':'user','content':compiled.serialized_prompt}],
                            max_tokens=recipe.output_reserve_tokens,temperature=0,seed=seed+number,prompt_format='plain'):
                        output+=event.get('text','')
                        if 'usage'in event:finish=event
                    if finish is None or finish['usage']['prompt_tokens']!=compiled.total_input_tokens:
                        raise ValueError('Runtime usage differs from the compiled tokenizer count.')
                    retained={key:value in compiled.serialized_prompt for key,value in case.get('evidence',{}).items()}
                    variants.append({'version_id':str(recipe.recipe_version_id),'status':'completed','prompt':compiled.serialized_prompt,
                        'output':output,'exact_match':output.strip()==case['expected'].strip(),
                        'evidence_retained':retained,'usage':finish['usage'],'elapsed_seconds':finish['elapsed_seconds'],
                        'finish_reason':finish['finish_reason'],'omitted_blocks':compiled.omitted_blocks,'truncated_blocks':compiled.truncated_blocks})
                except (ContextOverflowError,ValueError) as exc:
                    variants.append({'version_id':str(recipe.recipe_version_id),'status':'failed','reason':str(exc)})
            rows.append({'case_id':case['case_id'],'session_key':case['session_key'],'expected':case['expected'],
                'baseline':variants[0],'candidate':variants[1],
                'output_changed':variants[0].get('output')!=variants[1].get('output')})
    metrics={}
    for side in ('baseline','candidate'):
        complete=[row[side] for row in rows if row[side]['status']=='completed']
        metrics[side]={'total_cases':len(rows),'completed_cases':len(complete),'failed_cases':len(rows)-len(complete),
            'exact_match_fraction':sum(r['exact_match'] for r in complete)/len(rows),
            'prompt_tokens':sum(r['usage']['prompt_tokens'] for r in complete),
            'completion_tokens':sum(r['usage']['completion_tokens'] for r in complete),
            'elapsed_seconds':sum(r['elapsed_seconds'] for r in complete)}
    return ContextExperiment.objects.create(tenant_id=version.tenant_id,project_id=get_active_project(),name=name,
        recipe_version=version,stress_type='measured_pair',metrics=metrics,status='completed',
        details={'origin':'actual_cpu_reference','cases_digest':digest(cases),'inputs':cases,'cases':rows,
            'recipes':[{'version_id':str(v.recipe_version_id),'digest':recipe_pin(v)} for v in (baseline,version)],
            'pins':version.runtime_pins,'decoding':{'temperature':0,'seed':seed,'seed_rule':'seed + case index',
                'max_new_tokens':version.output_reserve_tokens,'prompt_format':'plain'},
            'environment':{'python':sys.version.split()[0],'platform':platform.platform(),'device':'cpu'},
            'limits':'Bounded local reference model; exact match on declared cases is not general task or safety qualification. Each case supplies its own memory/tool text; no session state is shared.'})

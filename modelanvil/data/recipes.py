"""Bounded typed recipe graphs. Expressions and generated code are never executed."""
import ast
import hashlib
import json
import re
import uuid

from modelanvil.data.detection import sample_text
from modelanvil.runners.training.runtime import digest

SCHEMA = 'modelanvil.recipe.v1'
MAX_ROWS = 32
FIELDS = {
    'source':{'format','text_field','group_field'}, 'sample':{'input','limit','seed'},
    'expression':{'input','operation','find','replace'}, 'template':{'input','template'},
    'generate':{'input','output','max_tokens','seed','prompt_format'},
    'validate':{'input','min_characters','required_keys','contains'},
    'merge':{'inputs'}, 'output':{'input'},
}


def bounded_integer(value, minimum, maximum):
    return type(value) is int and minimum <= value <= maximum


def validate_recipe(value):
    if (not isinstance(value, dict) or set(value) != {'schema','name','steps'} or value['schema'] != SCHEMA
            or not isinstance(value['name'],str) or not 1 <= len(value['name'].strip()) <= 100
            or not isinstance(value['steps'],list) or not 2 <= len(value['steps']) <= 12
            or len(json.dumps(value,allow_nan=False).encode()) > 64000):
        raise ValueError('Use a named recipe with 2–12 bounded typed steps.')
    types, dependencies = {}, {}
    for step in value['steps']:
        if (not isinstance(step,dict) or step.get('type') not in FIELDS
                or not isinstance(step.get('id'),str) or not re.fullmatch('[a-z][a-z0-9_-]{0,31}',step['id'])
                or step['id'] in types or set(step)-{'id','type'}-FIELDS[step['type']]):
            raise ValueError('Recipe steps need unique IDs and supported fields.')
        kind, key = step['type'],step['id']
        inputs = step.get('inputs') if kind == 'merge' else [step.get('input')] if kind != 'source' else []
        if (not isinstance(inputs,list) or any(not isinstance(n,str) or n not in types for n in inputs)
                or kind == 'merge' and (not 2 <= len(inputs) <= 4 or len(set(inputs)) != len(inputs))):
            raise ValueError('Step dependencies must reference earlier steps; cycles and missing inputs are refused.')
        incoming = types[inputs[0]] if inputs else 'text'
        if inputs and any(types[n] != incoming for n in inputs):
            raise ValueError('Merged steps must have the same output type.')
        if kind == 'source' and (step.get('format') not in {'jsonl','json','csv','docx','pdf'}
                or not isinstance(step.get('text_field','text'),str) or not 1 <= len(step.get('text_field','text')) <= 128
                or step.get('group_field') is not None and (not isinstance(step['group_field'],str) or not 1 <= len(step['group_field']) <= 128)):
            raise ValueError('Select a supported source format and bounded field mapping.')
        if kind == 'sample' and (not bounded_integer(step.get('limit'),1,MAX_ROWS) or not bounded_integer(step.get('seed'),0,2147483647)):
            raise ValueError('Samplers need a limit of 1–32 and a nonnegative seed.')
        if kind == 'expression' and (incoming != 'text' or step.get('operation') not in {'strip','lower','upper','replace'}
                or step['operation']=='replace' and any(not isinstance(step.get(k),str) or len(step[k]) > 256 for k in ('find','replace'))
                or step['operation']=='replace' and not step['find']):
            raise ValueError('Expressions support strip/lower/upper/replace on text only.')
        if kind == 'template' and (not isinstance(step.get('template'),str) or not 1 <= len(step['template']) <= 4000
                or any(token not in {'value','source'} for token in re.findall(r'\{\{(.*?)\}\}',step['template']))):
            raise ValueError('Templates support bounded literal text and {{value}}/{{source}} placeholders.')
        if kind == 'generate' and (incoming != 'text' or step.get('output') not in {'text','json','code'}
                or not bounded_integer(step.get('max_tokens'),1,256) or not bounded_integer(step.get('seed'),0,2147483647)
                or step.get('prompt_format','model') not in {'model','plain','chatml'}):
            raise ValueError('Generation needs text prompts, a typed output, 1–256 tokens and an explicit seed.')
        if kind == 'validate':
            if not bounded_integer(step.get('min_characters',0),0,16000):
                raise ValueError('Validator character bounds are invalid.')
            for field in ('contains','required_keys'):
                items=step.get(field,[])
                if not isinstance(items,list) or len(items)>16 or any(not isinstance(t,str) or not 1<=len(t)<=120 for t in items):
                    raise ValueError('Validators need bounded literal strings or JSON keys.')
            if step.get('required_keys') and incoming != 'json':
                raise ValueError('Required-key validation applies only to JSON outputs.')
        types[key] = step['output'] if kind == 'generate' else 'text' if kind == 'template' else incoming
        dependencies[key] = inputs
    if value['steps'][-1]['type'] != 'output' or sum(s['type']=='output' for s in value['steps']) != 1:
        raise ValueError('The recipe needs exactly one final output step.')
    reachable=set()
    def visit(key):
        if key not in reachable:
            reachable.add(key)
            for parent in dependencies[key]:visit(parent)
    visit(value['steps'][-1]['id'])
    if reachable != set(types):
        raise ValueError('Every recipe step must contribute to the final output.')
    return types


def text_value(value):
    return value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False)


def parse_generated(text, output):
    if not isinstance(text,str) or not text.strip() or len(text.encode()) > 32000:
        raise ValueError('empty_or_oversized_output')
    if output == 'json':
        from modelanvil.data.publication import _unique_object, _reject_constant
        try:
            value=json.loads(text,object_pairs_hook=_unique_object,parse_constant=_reject_constant)
            json.dumps(value,allow_nan=False)
            return value
        except (ValueError,RecursionError):
            raise ValueError('invalid_json_output') from None
    if output == 'code':
        try:
            tree=ast.parse(text)
            if sum(1 for _ in ast.walk(tree))>2000:raise ValueError()
        except (SyntaxError,ValueError,RecursionError):
            raise ValueError('invalid_python_syntax') from None
    return text


def source_cells(rows, node):
    return [{'key':digest([node,r['sample_id']]),'source':r,'value':sample_text(r),'format':'text',
             'trace':[node],'usage':{}} for r in rows]


def transform(cell, step):
    value=cell['value'];kind=step['type']
    if kind=='expression':
        op=step['operation'];value=value.replace(step['find'],step['replace']) if op=='replace' else getattr(value,op)()
    elif kind=='template':
        value=re.sub(r'\{\{(value|source)\}\}',lambda m:text_value(cell['value']) if m[1]=='value' else sample_text(cell['source']),step['template'])
    elif kind=='validate':
        text=text_value(value)
        if len(text)<step.get('min_characters',0):raise ValueError('too_short')
        if any(s not in text for s in step.get('contains',[])):raise ValueError('missing_literal')
        if step.get('required_keys') and (not isinstance(value,dict) or any(s not in value for s in step['required_keys'])):
            raise ValueError('missing_json_key')
    if len(text_value(value).encode()) > 32000:raise ValueError('transform_output_too_large')
    return {**cell,'key':digest([cell['key'],step['id']]),'value':value,
            'format':'text' if kind=='template' else cell['format'],'trace':[*cell['trace'],step['id']]}


def generated_cell(cell, step, result):
    value=parse_generated(result['text'],step['output'])
    call=digest([step['id'],cell['key']])
    return {**cell,'key':call,'value':value,'format':step['output'],'trace':[*cell['trace'],step['id']],
        'usage':{**cell['usage'],call:{'usage':result['usage'],'finish_reason':result['finish_reason']}}}


def envelopes(cells, *, recipe_sha, model_sha, runtime):
    rows=[]
    for cell in cells:
        source=cell['source'];value=cell['value'];kind=cell['format']
        content=hashlib.sha256(text_value(value).encode()).hexdigest()
        block={'block_id':'generated','type':kind, **({'value':value} if kind=='json' else {'text':value})}
        locations=[b['location'] for b in source['blocks'] if b.get('location')]
        block['location']={'source_path':source['provenance']['source_record_key'],
            **({'page':locations[0]['page']} if locations and all(l.get('page')==locations[0].get('page') for l in locations) and locations[0].get('page') else {})}
        rows.append({'schema_version':'1.0','sample_id':str(uuid.uuid5(uuid.NAMESPACE_URL,digest([recipe_sha,model_sha,cell['key'],content]))),
            'source_group_id':source['source_group_id'],'blocks':[block],
            'provenance':{**source['provenance'],'content_sha256':content,'parent_sample_refs':[source['sample_id']],
                'transformation_revision_ref':SCHEMA},
            'metadata':{'recipe_sha256':recipe_sha,'model_snapshot_sha256':model_sha,'runtime_sha256':runtime,
                'steps':cell['trace'],'source_sample_id':source['sample_id'],'generation_calls':cell['usage'],'review_required':True}})
        rows[-1]['metadata']['source_locations']=locations
    return rows

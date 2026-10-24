"""Budgeted tool chats: committed calls are replayed as results, never executed twice."""
import io
import json
import tempfile
from django.db import transaction
from django.utils import timezone
from modelanvil.artifacts.models import Artifact
from modelanvil.budgets.models import BudgetPolicy,BudgetReservation,UsageEvent
from modelanvil.core.ids import uuid7
from modelanvil.core.models import IdempotencyKey
from modelanvil.core.privacy import project_policy
from modelanvil.identity.models import Tenant
from modelanvil.jobs.models import Job,JobAttempt,Worker
from modelanvil.runners.models import InferenceRequest
from modelanvil.runners.inference import runtime_input_identity,verified_artifact,copy_verified
from modelanvil.runners.model_catalog import _store
from modelanvil.runners import tool_runtime as runtime,tool_schema,mcp_connections as mcp,tool_sandbox
from modelanvil.runners.training.runtime import digest

TYPE='qualified_tool_chat'
UNIT='generated_tokens'
PYTHON={'type':'function','function':{'name':'python','description':'Execute bounded Python in a disposable offline sandbox. Print the result.',
    'parameters':{'type':'object','properties':{'code':{'type':'string','maxLength':4096}},'required':['code'],'additionalProperties':False}}}


def catalog(tenant,project,identifiers,code):
    if (not isinstance(identifiers,list) or len(identifiers)>3 or any(not isinstance(i,str) for i in identifiers)
            or len(set(identifiers))!=len(identifiers) or type(code) is not bool):raise ValueError('Select at most3 installed MCP targets and an explicit code grant.')
    offered=[];bindings={};servers={}
    for identifier in identifiers:
        listing=mcp.discover(identifier,tenant,project);servers[identifier]={'catalog_digest':listing['result']['catalog_digest'],
            'configuration_signature':listing['configuration_signature'],'server':listing['server']}
        for name,item in listing['result']['tools'].items():
            if name in bindings or name=='python':raise ValueError('Selected MCP tool names conflict; select a distinct allowlist.')
            offered.append({'type':'function','function':{'name':name,'description':item.get('description',''), 'parameters':item['inputSchema']}})
            bindings[name]={'kind':'mcp','server_id':identifier}
    sandbox=None
    if code:
        if not project_policy(tenant,project)['code_execution']:raise ValueError('An administrator must enable code execution in project Privacy first.')
        sandbox=tool_sandbox.available();offered.append(PYTHON);bindings['python']={'kind':'python'}
    if not offered:raise ValueError('Select at least one permitted MCP target or the isolated Python tool.')
    tool_schema.tools(offered)
    return {'tools':offered,'bindings':bindings,'servers':servers,'sandbox':sandbox}


@transaction.atomic
def queue(*,tenant,project,principal,version,prompt,max_tokens,targets,code,pool,policy_id,key):
    if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>2048:raise ValueError('Use1–2048 prompt characters.')
    runtime.require_packages();plan=runtime.candidate_bundle(version,tenant,project.pk)
    tools=catalog(tenant,project.pk,targets,code);messages=[{'role':'user','content':prompt}]
    runtime.native_input(messages,tools['tools'],max_tokens)
    frozen={'model_id':str(version.model_version_id),'model_identity':runtime_input_identity(version),'plan':plan,
        'catalog':tools,'messages':messages,'max_tokens':max_tokens,'build_digest':runtime.build_digest(),'accelerator':runtime.observed_device()}
    fingerprint=digest({'frozen':frozen,'pool':pool.pk,'policy_id':str(policy_id)})
    admission,created=IdempotencyKey.all_objects.select_for_update().get_or_create(tenant_id=tenant,principal=str(principal),
        http_method='POST',path=f'/tools/{project.pk}/jobs',key=key,defaults={'request_hash':fingerprint})
    if not created:
        if admission.request_hash!=fingerprint:raise ValueError('Idempotency key belongs to different tool inputs.')
        return InferenceRequest.all_objects.get(tenant_id=tenant,project=project,request_id=admission.response_body['request_id'])
    from modelanvil.jobs.setup import local_capacity_available
    workers=list(Worker.all_objects.filter(tenant_id=tenant,pool=pool,status__in=('available','busy')))
    if (str(pool.tenant_id)!=str(tenant) or pool.status!='active' or pool.result_egress!='envelope' or len(workers)!=1
            or not runtime.capable_worker(workers[0]) or not local_capacity_available(workers[0])):raise ValueError('Use one available exact CPU tools worker in an active envelope pool.')
    policy=BudgetPolicy.all_objects.filter(tenant_id=tenant,policy_id=policy_id,enabled=True,unit=UNIT,currency='').first()
    if policy is None:raise ValueError('Select an enabled generated_tokens quota without currency pricing.')
    job_id=uuid7();BudgetReservation.reserve(tenant_id=tenant,policy=policy,job_id=job_id,estimated_amount=9*max_tokens)
    record=InferenceRequest.all_objects.create(tenant_id=tenant,project=project,principal_id=str(principal),model_version=version,
        status='queued',input_digest=digest(frozen),configuration={'kind':TYPE,'job_id':str(job_id),'frozen':frozen,'trace':[],
            'messages':messages,'model_turns':0,'tool_calls':0,'charges':{}})
    Job.all_objects.create(tenant_id=tenant,project=project,job_id=job_id,pool=pool,name='Bounded CPU tool chat',max_attempts=3,
        payload={'type':TYPE,'request_id':str(record.request_id),'input_digest':record.input_digest},requirements={'slots':1,'tool_runtime':runtime.CONTRACT_DIGEST,'gpu_device':'cpu'})
    admission.response_body={'request_id':str(record.request_id)};admission.response_status=202;admission.completed_at=timezone.now();admission.save()
    return record


def owning_request(job,lock=False):
    qs=InferenceRequest.all_objects.select_related('model_version__tokenizer','project')
    if lock:qs=qs.select_for_update()
    record=qs.get(tenant_id=job.tenant_id,request_id=job.payload['request_id'])
    if (record.project_id!=job.project_id or record.configuration.get('kind')!=TYPE
            or record.configuration.get('job_id')!=str(job.job_id) or record.input_digest!=job.payload.get('input_digest')
            or digest(record.configuration['frozen'])!=record.input_digest):raise ValueError('Tool job ownership or immutable inputs changed.')
    return record


def current_inputs(record,job):
    frozen=record.configuration['frozen'];cat=frozen['catalog']
    if (not Tenant.objects.filter(pk=record.tenant_id,status='active').exists() or job.pool.result_egress!='envelope'
            or frozen['build_digest']!=runtime.build_digest() or frozen['accelerator']!=runtime.observed_device()
            or frozen['model_identity']!=runtime_input_identity(record.model_version)
            or frozen['plan']!=runtime.candidate_bundle(record.model_version,record.tenant_id,record.project_id)):
        raise ValueError('Tool source, model, code, project or egress changed.')
    for identifier,pin in cat['servers'].items():
        if mcp.resolve(identifier,record.tenant_id,record.project_id)['signature']!=pin['configuration_signature']:
            raise ValueError('MCP permissions or installed credentials changed.')
    if cat['sandbox'] and not project_policy(record.tenant_id,record.project_id)['code_execution']:raise ValueError('Code execution permission was revoked.')
    reservation=BudgetReservation.all_objects.select_for_update().get(tenant_id=job.tenant_id,job_id=job.job_id,state='reserved')
    policy=BudgetPolicy.all_objects.select_for_update().get(pk=reservation.policy_id,tenant_id=job.tenant_id)
    period,committed=BudgetReservation.current_commitment(policy)
    if (not policy.enabled or policy.unit!=UNIT or policy.currency or period!=reservation.period_start
            or committed>policy.limit_amount or reservation.estimated_amount!=9*frozen['max_tokens']):raise ValueError('Tool quota is no longer authorized.')
    return frozen


def live(context,*,retain_terminal_report=False):
    attempt=JobAttempt.all_objects.select_for_update().get(pk=context.attempt.pk)
    job=Job.all_objects.select_for_update().select_related('pool').get(pk=attempt.job_id)
    if (attempt.status!='running' or job.status!='running' or attempt.fencing_token!=context.fencing_token
            or job.fencing_token!=context.fencing_token or job.claimed_by_id!=attempt.worker_id or job.desired_action=='cancel' and not retain_terminal_report
            or not attempt.lease_expires_at or attempt.lease_expires_at<=timezone.now()):raise ValueError('Tool job cancelled or fenced out.')
    record=owning_request(job,lock=True)
    if not retain_terminal_report:current_inputs(record,job)
    return record,job


def gpu_claim_plan(job,worker):
    from modelanvil.device_admission import device_key,device_available
    record=owning_request(job,lock=True);frozen=current_inputs(record,job)
    if not runtime.capable_worker(worker) or not device_available('cpu'):raise ValueError('Exact physical CPU tools worker is unavailable.')
    return {'host_key':frozen['accelerator']['host_key'],'device_key':device_key('cpu')}


def _save(record,event=None,**changes):
    config=record.configuration
    if event:config={**config,'trace':[*config['trace'],event]}
    record.configuration={**config,**changes};record.save(update_fields=['configuration','updated_at'])


def _cancelled(context):
    if not context.heartbeat(progress=.5):return True
    try:
        with transaction.atomic():live(context)
    except (ValueError,KeyError,TypeError):return True
    return False


def tool_executor(descriptor,context):
    if descriptor.get('payload',{}).get('type')!=TYPE:raise ValueError('This installed executor accepts typed tool chats only.')
    try:
        with transaction.atomic():
            record,job=live(context)
            if record.configuration.get('complete'):return
            if record.configuration.get('pending_call'):raise ValueError('A prior tool call has an unknown result and will not be replayed.')
            frozen=current_inputs(record,job)
        from modelanvil.device_admission import device_lease
        with device_lease('cpu',pass_descriptor=True) as fd,runtime.staged_files(frozen['plan']['files'],record.tenant_id,record.project_id) as directory:
            while True:
                with transaction.atomic():
                    record,job=live(context);config=record.configuration;turn=config['model_turns']
                    if turn>=3:raise ValueError('The bounded model turn/retry limit was reached.')
                    charge=f'{context.attempt.attempt_id}:{turn}';charges={**config['charges'],charge:{'tokens':frozen['max_tokens'],'basis':'unknown_inflight_upper_bound'}}
                    messages=config['messages'];_save(record,model_turns=turn+1,charges=charges)
                report=runtime.generate(directory,messages,frozen['catalog']['tools'],frozen['max_tokens'],cancelled=lambda:_cancelled(context),lease_descriptor=fd)
                with transaction.atomic():
                    record,job=live(context);charges=record.configuration['charges'];charges[charge]={'tokens':report['usage']['completion_tokens'],'basis':'verified_generated_tokens'}
                    _save(record,{'kind':'model','turn':turn,'input':json.loads(runtime.native_input(messages,frozen['catalog']['tools'],frozen['max_tokens'])),
                        'report':report},charges=charges)
                try:
                    if report['finish_reason']!='stop':raise ValueError('Length-limited native tool output is incomplete.')
                    reply=tool_schema.parse_reply(report['content'],frozen['catalog']['tools'])
                except ValueError:
                    with transaction.atomic():
                        record,job=live(context);_save(record,{'kind':'validation_failure','turn':turn,'reason':'Incomplete or invalid native tool reply; no dispatch.'},
                            messages=[*messages,{'role':'user','content':'The previous response failed tool validation. Return a complete native call using only the offered names and exact JSON arguments, or a plain final answer.'}])
                    continue
                if not reply['calls']:
                    if not reply['content'].strip():raise ValueError('Tool model produced no complete answer.')
                    with transaction.atomic():
                        record,job=live(context);_save(record,{'kind':'answer','turn':turn,'content':reply['content']},complete=True,answer=reply['content'])
                    return
                with transaction.atomic():
                    record,job=live(context)
                    if record.configuration['tool_calls']+len(reply['calls'])>2:raise ValueError('The bounded two-call limit was reached.')
                    ids=[f'call_{turn}_{i}' for i in range(len(reply['calls']))]
                    messages=[*messages,{'role':'assistant','content':'','tool_calls':[{'id':identifier,'type':'function','function':call} for identifier,call in zip(ids,reply['calls'])]}]
                    _save(record,messages=messages)
                for identifier,call in zip(ids,reply['calls']):
                    with transaction.atomic():
                        record,job=live(context);_save(record,{'kind':'tool_started','id':identifier,'call':call},pending_call=identifier,
                            tool_calls=record.configuration['tool_calls']+1)
                    binding=frozen['catalog']['bindings'][call['name']]
                    if binding['kind']=='mcp':
                        server=binding['server_id'];pin=frozen['catalog']['servers'][server]
                        result=mcp.call(server,record.tenant_id,record.project_id,name=call['name'],arguments=call['arguments'],
                            catalog_digest=pin['catalog_digest'],configuration_signature=pin['configuration_signature'],cancelled=lambda:_cancelled(context),lease_descriptor=fd)
                        result.pop('configuration_signature',None)
                        okay=result['result'].get('is_error') is False
                        content=json.dumps(result['result'].get('structured_content') or result['result']['content'],allow_nan=False)
                    else:
                        result=tool_sandbox.run(call['arguments']['code'],seconds=5,cancelled=lambda:_cancelled(context),lease_descriptor=fd)
                        okay=result['status']=='completed' and result['exit_code']==0 and result['container_removed']
                        content=json.dumps({k:result.get(k) for k in ('status','stdout','stderr','exit_code')},allow_nan=False)
                    # Results retain the execution report even when too large for this model's context.
                    with transaction.atomic():
                        record,job=live(context,retain_terminal_report=True);messages=[*messages,{'role':'tool','tool_call_id':identifier,'name':call['name'],'content':content}]
                        _save(record,{'kind':'tool_result','id':identifier,'name':call['name'],'binding':binding,'result':result,'successful':bool(okay)},pending_call=None,messages=messages)
                    if not okay:raise ValueError('The actual tool returned a failure; inspect the retained structured result.')
    except Exception:
        # Private transport/model diagnostics never enter job logs. Preserve already committed evidence.
        try:
            with transaction.atomic():
                record,job=live(context,retain_terminal_report=True);_save(record,{'kind':'failure','reason':'The bounded tool run could not complete; inspect validation, tool reports and current permissions.'})
        except (ValueError,KeyError,TypeError):pass


def validate_trace(record):
    config=record.configuration;frozen=config['frozen'];trace=config['trace'];started={};results={};answers=[];models={}
    if not config.get('complete') or config.get('pending_call') or not isinstance(trace,list) or len(trace)>20:raise ValueError('Tool chat has no complete committed trace.')
    if type(config.get('model_turns')) is not int or not 1<=config['model_turns']<=3:raise ValueError('Invalid model turn count.')
    for event in trace:
        kind=event.get('kind')
        if kind=='model':
            value=event['input'];raw=runtime.native_input(value['messages'],value['tools'],value['max_tokens'])
            if value['tools']!=frozen['catalog']['tools'] or value['max_tokens']!=frozen['max_tokens']:raise ValueError('Trace tools differ from admission.')
            runtime.validate_report(event['report'],raw,value['max_tokens'])
            if type(event['turn']) is not int or not 0<=event['turn']<config['model_turns'] or event['turn'] in models:raise ValueError('Duplicate or invalid generation turn.')
            models[event['turn']]=event['report']
        elif kind=='tool_started':
            if event['id'] in started:raise ValueError('Duplicate tool dispatch.')
            import re
            match=re.fullmatch(r'call_([0-2])_([01])',event['id'])
            if match is None:raise ValueError('Tool call has no native generation identity.')
            turn,index=map(int,match.groups());model=models.get(turn,{})
            native=tool_schema.parse_reply(model.get('content',''),frozen['catalog']['tools'])
            if model.get('finish_reason')!='stop' or index>=len(native['calls']) or native['calls'][index]!=event['call']:
                raise ValueError('Tool dispatch differs from the actual validated model call.')
            tool_schema.arguments(event['call']['name'],event['call']['arguments'],frozen['catalog']['tools']);started[event['id']]=event
        elif kind=='tool_result':
            if event['id'] not in started or event['id'] in results or event['successful'] is not True:raise ValueError('Tool result has no successful unique committed call.')
            name=started[event['id']]['call']['name']
            if event['name']!=name or event['binding']!=frozen['catalog']['bindings'][name]:raise ValueError('Tool result binding changed.')
            result=event['result']
            if event['binding']['kind']=='python':
                if result.get('status')!='completed' or result.get('exit_code')!=0 or result.get('container_removed') is not True or result.get('isolation',{}).get('network')!='none':raise ValueError('Sandbox evidence is incomplete.')
            elif result.get('status')!='completed' or result.get('result',{}).get('is_error') is not False or result.get('protocol',{}).get('protocol_version')!=mcp.PROTOCOL:
                raise ValueError('MCP execution evidence is incomplete.')
            results[event['id']]=event
        elif kind=='answer':
            report=models.get(event['turn'],{});parsed=tool_schema.parse_reply(report.get('content',''),frozen['catalog']['tools'])
            if report.get('finish_reason')!='stop' or parsed['calls'] or parsed['content']!=event['content']:raise ValueError('Final answer has no actual complete model continuation.')
            answers.append(event['content'])
    if set(results)!=set(started) or len(started)>2 or len(models)>3 or answers!=[config.get('answer')]:raise ValueError('Tool trace is missing committed calls or its final answer.')
    return {'schema_version':'modelanvil.tool-chat-trace.v1','input_digest':record.input_digest,'source':runtime.SOURCE,
        'answer':answers[0],'trace':trace,'model_turns':config['model_turns'],'tool_calls':len(results),'production_qualified':False}


def finalize_job(job,status):
    if status in ('queued','interrupted'):return status
    record=owning_request(job,lock=True)
    if job.desired_action=='cancel':status='cancelled'
    if status=='succeeded':
        try:current_inputs(record,job);result=validate_trace(record)
        except (ValueError,KeyError,TypeError,OSError):status='failed'
        else:record.output_digest=digest(result)
    config=record.configuration;trace=config.get('trace',[])
    report={'schema_version':'modelanvil.tool-chat-trace.v1','status':status,'input_digest':record.input_digest,'source':runtime.SOURCE,
        'answer':config.get('answer','') if status=='succeeded' else '', 'trace':trace,'production_qualified':False}
    ref=_store(io.BytesIO(json.dumps(report,allow_nan=False).encode()),tenant=record.tenant_id,project=record.project_id,
        name='tool-trace.json',media_type='application/json',metadata={'kind':'tool_execution_trace','request_id':str(record.request_id)})
    record.configuration={**config,'trace_artifact':ref};record.status='completed' if status=='succeeded' else status;record.completed_at=timezone.now()
    record.usage={'completion_tokens':sum(c['tokens'] for c in config['charges'].values()),'model_turns':config['model_turns'],
        'tool_calls':config['tool_calls'],'unknown_inflight_tokens':sum(c['tokens'] for c in config['charges'].values() if c['basis']=='unknown_inflight_upper_bound')}
    record.elapsed_seconds=sum(e['report']['wall_seconds'] for e in trace if e.get('kind')=='model');record.save()
    reservation=BudgetReservation.all_objects.select_for_update().get(tenant_id=job.tenant_id,job_id=job.job_id)
    if reservation.state=='reserved':
        for identity,charge in config['charges'].items():
            UsageEvent.record(tenant_id=job.tenant_id,provider_event_key=f'tools:{identity}',quantity=charge['tokens'],unit=UNIT,reservation=reservation,
                detail={'request_id':str(record.request_id),**charge})
        reservation.settle(record.usage['completion_tokens'])
    return status


@transaction.atomic
def cancel(record):
    job=Job.all_objects.select_for_update().get(tenant_id=record.tenant_id,job_id=record.configuration['job_id'])
    if job.status in ('succeeded','failed','cancelled'):raise ValueError('This tool chat is already terminal.')
    job.desired_action='cancel'
    if job.status in ('queued','interrupted'):job.status=finalize_job(job,'cancelled')
    job.save(update_fields=['desired_action','status','updated_at']);return job

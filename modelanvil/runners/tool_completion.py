"""Native compatible tool completions return calls; caller-defined functions are never dispatched."""
import json
import re
from django.db import transaction
from django.utils import timezone
from modelanvil.budgets.models import BudgetPolicy,BudgetReservation,UsageEvent
from modelanvil.core.ids import uuid7
from modelanvil.core.models import IdempotencyKey
from modelanvil.identity.models import Tenant
from modelanvil.runners.models import InferenceRequest,ModelVersion
from modelanvil.runners.inference import runtime_input_identity
from modelanvil.runners import tool_runtime as runtime,tool_schema
from modelanvil.runners.training.runtime import digest


def messages(values,offered):
    if not isinstance(values,list) or not 1<=len(values)<=12:raise ValueError('Use1–12 native messages.')
    result=[];pending={};seen=set()
    for i,item in enumerate(values):
        if not isinstance(item,dict) or item.get('role') not in ('system','user','assistant','tool'):raise ValueError('Unsupported native message role.')
        role=item['role'];allowed={'role','content'}|({'tool_calls'} if role=='assistant' else {'tool_call_id','name'} if role=='tool' else set())
        if set(item)-allowed or not isinstance(item.get('content','') or '',str) or len((item.get('content','') or '').encode())>16384:
            raise ValueError('Native messages contain unsupported or oversized fields.')
        if role=='system' and i!=0:raise ValueError('System instructions belong at the beginning.')
        if pending and role!='tool':raise ValueError('Supply every outstanding tool result before continuing.')
        native={'role':role,'content':item.get('content') or ''}
        if role=='assistant' and item.get('tool_calls'):
            calls=item['tool_calls']
            if not isinstance(calls,list) or not 1<=len(calls)<=2:raise ValueError('Use at most2 calls per assistant message.')
            native['tool_calls']=[]
            for call in calls:
                if (not isinstance(call,dict) or set(call)!={'id','type','function'} or call['type']!='function'
                        or not isinstance(call['id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',call['id']) or call['id'] in seen
                        or not isinstance(call['function'],dict) or set(call['function'])!={'name','arguments'}
                        or not isinstance(call['function']['arguments'],str)):raise ValueError('Use standard unique tool_call IDs and JSON-string function arguments.')
                function=call['function'];args=tool_schema.loads(function['arguments']);tool_schema.arguments(function['name'],args,offered)
                pending[call['id']]=function['name'];seen.add(call['id'])
                native['tool_calls'].append({**call,'function':{'name':function['name'],'arguments':args}})
        elif role=='tool':
            identifier=item.get('tool_call_id')
            if identifier not in pending or item.get('name',pending[identifier])!=pending[identifier]:raise ValueError('Tool result ID/name does not match an outstanding call.')
            native.update(tool_call_id=identifier,name=pending.pop(identifier))
        result.append(native)
    if pending or result[-1]['role'] not in ('user','tool'):raise ValueError('End with a user message or all matching tool results.')
    return result


@transaction.atomic
def reserve(*,tenant,project,principal,version,value,key,policy_id):
    plan=runtime.candidate_bundle(version,tenant,project.pk);runtime.require_packages()
    frozen={'messages':value['messages'],'tools':value['tools'],'tool_choice':value['tool_choice'],'max_tokens':value['max_tokens'],
        'model':str(version.model_version_id),'model_identity':runtime_input_identity(version),'plan':plan,'build_digest':runtime.build_digest()}
    fingerprint=digest({'frozen':frozen,'policy_id':str(policy_id)})
    admission,created=IdempotencyKey.all_objects.select_for_update().get_or_create(tenant_id=tenant,principal=str(principal),http_method='POST',
        path=f'/tools/{project.pk}/completions',key=key,defaults={'request_hash':fingerprint})
    if not created:
        if admission.request_hash!=fingerprint:raise ValueError('Idempotency key belongs to different native completion inputs.')
        return InferenceRequest.all_objects.get(request_id=admission.response_body['request_id'],tenant_id=tenant,project=project),True
    policy=BudgetPolicy.all_objects.filter(tenant_id=tenant,policy_id=policy_id,enabled=True,unit='generated_tokens',currency='').first()
    if policy is None:raise ValueError('Select an enabled generated_tokens quota.')
    reservation_id=uuid7();BudgetReservation.reserve(tenant_id=tenant,policy=policy,job_id=reservation_id,estimated_amount=value['max_tokens'])
    record=InferenceRequest.all_objects.create(tenant_id=tenant,project=project,principal_id=str(principal),model_version=version,input_digest=digest(frozen),
        configuration={'kind':'native_tool_completion','frozen':frozen,'reservation_job_id':str(reservation_id)})
    admission.response_body={'request_id':str(record.request_id)};admission.response_status=202;admission.completed_at=timezone.now();admission.save()
    return record,False


def execute(record,authorized):
    frozen=record.configuration['frozen'];report=None;failure=None
    offered=[] if frozen['tool_choice']=='none' else frozen['tools']
    def cancelled():
        if not authorized() or not Tenant.objects.filter(pk=record.tenant_id,status='active').exists():return True
        with transaction.atomic():
            reservation=BudgetReservation.all_objects.select_for_update().select_related('policy').get(tenant_id=record.tenant_id,job_id=record.configuration['reservation_job_id'])
            policy=BudgetPolicy.all_objects.select_for_update().get(pk=reservation.policy_id,tenant_id=record.tenant_id)
            period,committed=BudgetReservation.current_commitment(policy)
            if (reservation.state!='reserved' or not policy.enabled or policy.unit!='generated_tokens' or policy.currency
                    or reservation.estimated_amount!=frozen['max_tokens'] or period!=reservation.period_start or committed>policy.limit_amount):return True
        record.model_version=ModelVersion.all_objects.select_related('tokenizer').get(pk=record.model_version_id)
        return (frozen['build_digest']!=runtime.build_digest() or frozen['model_identity']!=runtime_input_identity(record.model_version)
            or frozen['plan']!=runtime.candidate_bundle(record.model_version,record.tenant_id,record.project_id))
    try:
        if cancelled():raise ValueError('Native completion authorization changed.')
        from modelanvil.device_admission import device_lease
        with device_lease('cpu',pass_descriptor=True) as fd,runtime.staged_files(frozen['plan']['files'],record.tenant_id,record.project_id) as directory:
            report=runtime.generate(directory,frozen['messages'],offered,frozen['max_tokens'],cancelled=cancelled,lease_descriptor=fd)
            if cancelled():raise ValueError('Native completion authorization changed.')
        if report['finish_reason']!='stop':raise ValueError('Length-limited native tool output was refused; no function was executed.')
        reply=tool_schema.parse_reply(report['content'],offered)
        if frozen['tool_choice']=='required' and not reply['calls']:raise ValueError('The model did not produce the required valid tool call.')
        calls=[{'id':f'call_{record.request_id.hex[:12]}_{i}','type':'function','function':{'name':call['name'],'arguments':json.dumps(call['arguments'],separators=(',',':'))}}
            for i,call in enumerate(reply['calls'])]
        response={'id':f'chatcmpl-{record.request_id}','object':'chat.completion','created':int(record.created_at.timestamp()),'model':frozen['model'],
            'choices':[{'index':0,'message':{'role':'assistant','content':reply['content'] or None,**({'tool_calls':calls} if calls else {})},'finish_reason':'tool_calls' if calls else 'stop'}],
            'usage':report['usage'],'modelanvil':{'request_id':str(record.request_id),'tool_execution':'caller_managed','caller_tool_results_verified':False,'production_qualified':False}}
    except Exception as exc:failure=exc;response=None
    with transaction.atomic():
        record=InferenceRequest.all_objects.select_for_update().get(pk=record.pk)
        reservation=BudgetReservation.all_objects.select_for_update().get(tenant_id=record.tenant_id,job_id=record.configuration['reservation_job_id'])
        if record.status!='running' or reservation.state!='reserved':raise ValueError('This completion was already finalized or reconciled.')
        tokens=report['usage']['completion_tokens'] if report else frozen['max_tokens']
        UsageEvent.record(tenant_id=record.tenant_id,provider_event_key=f'native-tools:{record.request_id}',quantity=tokens,unit='generated_tokens',reservation=reservation,
            detail={'request_id':str(record.request_id),'basis':'verified_generated_tokens' if report else 'unknown_inflight_upper_bound'})
        reservation.settle(tokens);record.configuration={**record.configuration,'report':report,'response':response};record.status='failed' if failure else 'completed'
        record.usage=report['usage'] if report else {'unknown_inflight_completion_tokens':tokens};record.completed_at=timezone.now()
        record.output_digest=digest(response) if response else '';record.elapsed_seconds=report['wall_seconds'] if report else None;record.save()
    if failure:raise ValueError('Native tool completion failed validation, authorization or its bounded runtime; no caller-defined function was executed.') from None
    return response

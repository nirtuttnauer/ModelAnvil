"""Conservatively close abandoned synchronous tool completions after their hard runtime bound."""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from modelanvil.runners.models import InferenceRequest
from modelanvil.budgets.models import BudgetReservation,UsageEvent


class Command(BaseCommand):
    help='Fail native tool completions still running after120seconds and charge the admitted token ceiling. Active durable tool jobs use normal worker lease reconciliation.'

    def handle(self,*args,**options):
        cutoff=timezone.now()-timedelta(seconds=120);count=0
        ids=InferenceRequest.all_objects.filter(configuration__kind='native_tool_completion',status='running',created_at__lt=cutoff).values_list('pk',flat=True)
        for identifier in list(ids):
            with transaction.atomic():
                record=InferenceRequest.all_objects.select_for_update().get(pk=identifier)
                if record.status!='running':continue
                config=record.configuration;tokens=config['frozen']['max_tokens']
                reservation=BudgetReservation.all_objects.select_for_update().get(tenant_id=record.tenant_id,job_id=config['reservation_job_id'])
                if reservation.state=='reserved':
                    UsageEvent.record(tenant_id=record.tenant_id,provider_event_key=f'native-tools:{record.request_id}',quantity=tokens,unit='generated_tokens',
                        reservation=reservation,detail={'request_id':str(record.request_id),'basis':'unknown_inflight_upper_bound'})
                    reservation.settle(tokens)
                record.status='failed';record.completed_at=timezone.now();record.usage={'unknown_inflight_completion_tokens':tokens}
                record.configuration={**config,'response':None,'failure':'Abandoned completion; its admitted token ceiling was charged.'};record.save();count+=1
        self.stdout.write(f'Reconciled {count} abandoned native tool completions.')

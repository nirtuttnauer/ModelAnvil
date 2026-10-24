import json
from django.core.management.base import BaseCommand,CommandError
from modelanvil.runners.accelerator_support import OPERATIONS,inspect,report

class Command(BaseCommand):
    help='Inspect installed operation/device compatibility without model loading or jobs; does not qualify hardware.'
    def add_arguments(self,parser):
        parser.add_argument('--operation',choices=OPERATIONS)
        parser.add_argument('--device')
        parser.add_argument('--precision',default='fp32')
        parser.add_argument('--quantization',default='none')
        parser.add_argument('--offload',action='store_true')
    def handle(self,*args,**options):
        if bool(options['operation'])!=bool(options['device']):raise CommandError('Select both --operation and --device, or neither for the full report.')
        value=inspect(options['operation'],options['device'],precision=options['precision'],quantization=options['quantization'],offload=options['offload']) if options['operation'] else report()
        self.stdout.write(json.dumps(value,indent=2))
        if options['operation'] and not value['installed_compatible']:raise CommandError('Selected operation/device is unavailable; see the structured reason above.')

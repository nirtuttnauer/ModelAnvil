"""Print or archive the measured training hardware/runtime report for this host."""
import json

from django.core.management.base import BaseCommand

from modelanvil.runners.training.hardware import hardware_report


class Command(BaseCommand):
    help = 'Measure this host and print the training hardware/runtime report. Qualifies nothing.'

    def add_arguments(self, parser):
        parser.add_argument('--output', help='Optional path to write the JSON report to.')
        parser.add_argument('--indent', type=int, default=2, help='JSON indent for the printed report.')

    def handle(self, *args, **options):
        report = hardware_report()
        payload = json.dumps(report, indent=options['indent'], sort_keys=True)
        output = options.get('output')
        if output:
            with open(output, 'w', encoding='utf-8') as handle:
                handle.write(payload + '\n')
            self.stdout.write(f'wrote {output}')
        self.stdout.write(payload)
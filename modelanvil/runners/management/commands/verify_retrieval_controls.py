import json
from pathlib import Path
from django.core.management.base import BaseCommand,CommandError
from modelanvil.rag.benchmark import benchmark


class Command(BaseCommand):
    help='Run the frozen public relevance/random/full-text and raw ANN controls on actual PostgreSQL.'

    def add_arguments(self,parser):
        parser.add_argument('--output',required=True)

    def handle(self,*args,**options):
        path=Path(options['output'])
        if path.exists():raise CommandError('Preserve the existing report; choose a new output path.')
        report=benchmark();path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('x') as stream:json.dump(report,stream,indent=2);stream.write('\n')
        self.stdout.write(json.dumps({'passed':report['passed'],'documents':report['documents'],'chunks':report['chunks'],
            'held_out_ndcg':{mode:value['metrics']['ndcg@5'] for mode,value in report['held_out'].items()},
            'frozen_thresholds':report['frozen_thresholds']}))
        if not report['passed']:raise CommandError('Frozen held-out control criteria did not pass; inspect the preserved report without tuning on it.')

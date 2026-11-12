import json
from pathlib import Path
from django.core.management.base import BaseCommand,CommandError
from modelanvil.rag import benchmark_expanded as expanded


class Command(BaseCommand):
    help=('ANVIL-020 expanded SciFact small correctness check (policy rag-expanded-corpus-v1). '
          'plan: rebuild the frozen split; development: measure and optionally freeze thresholds; '
          'held_out: measure once against the committed thresholds.')

    def add_arguments(self,parser):
        parser.add_argument('--phase',required=True,choices=['plan','development','held_out'])
        parser.add_argument('--output',required=True)
        parser.add_argument('--freeze',help='development only: write the thresholds file to commit before the held-out run')
        parser.add_argument('--thresholds',help='held_out only: the committed thresholds file')
        parser.add_argument('--beir-cross-check',action='store_true',help='plan only: compare the cached BEIR test qrels byte for byte')

    def handle(self,*args,**options):
        phase=options['phase'];path=Path(options['output'])
        if path.exists():raise CommandError('Preserve the existing output; choose a new output path.')
        if options['freeze'] and phase!='development':raise CommandError('--freeze applies to the development phase only.')
        if options['thresholds'] and phase!='held_out':raise CommandError('--thresholds applies to the held_out phase only.')
        if options['beir_cross_check'] and phase!='plan':raise CommandError('--beir-cross-check applies to the plan phase only.')
        freeze=Path(options['freeze']) if options['freeze'] else None
        if freeze and freeze.exists():raise CommandError('Preserve the existing thresholds file; choose a new path.')
        try:
            if phase=='plan':
                if options['beir_cross_check']:
                    check=expanded.beir_cross_check()
                    self.stdout.write('BEIR_CROSS_CHECK '+json.dumps(check))
                    if not check['identical_bytes'] or not check['matches_pin']:raise CommandError('Rebuilt held-out judgments differ from BEIR test.tsv.')
                report=expanded.build_plan()[0]
            else:
                report=expanded.run(phase,options['thresholds'])
        except ValueError as exc:
            raise CommandError(str(exc)) from None
        text=expanded.dumps(report);path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('x') as stream:stream.write(text)
        if phase=='plan':
            self.stdout.write(json.dumps({'policy_id':report['policy_id'],'size':report['size'],
                'shards':[{k:v for k,v in s.items() if k!='document_ids'} for s in report['shards']]}))
            return
        summary={'label':report['label'],'phase':phase,'queries':report['queries_evaluated'],'documents':report['documents'],
            'chunks':report['chunks'],'ndcg@5':{m:r['metrics']['ndcg@5'] for m,r in report['relevance'].items()},
            'thresholds':report['thresholds'],'elapsed_seconds':report['elapsed_seconds']}
        if phase=='development':
            summary['ready_to_freeze']=report['ready_to_freeze']
            self.stdout.write('ANVIL020_DEVELOPMENT '+json.dumps(summary))
            if not report['ready_to_freeze']:raise CommandError('Development did not qualify; the report is preserved and nothing was frozen.')
            if freeze:
                frozen=expanded.freeze(report,text.encode());freeze.parent.mkdir(parents=True,exist_ok=True)
                with freeze.open('x') as stream:stream.write(expanded.dumps(frozen))
            return
        summary['passed']=report['passed']
        self.stdout.write('ANVIL020_HELD_OUT '+json.dumps(summary))
        if not report['passed']:raise CommandError('Frozen held-out criteria did not pass; inspect the preserved report without tuning on it.')

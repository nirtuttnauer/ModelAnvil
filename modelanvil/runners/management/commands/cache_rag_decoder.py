from django.core.management.base import BaseCommand
from modelanvil.rag.decoder import cache_decoder,directory


class Command(BaseCommand):
    help='Explicitly download and verify the fixed public Apache-2.0 CPU RAG decoder.'

    def handle(self,*args,**options):
        cache_decoder();self.stdout.write(str(directory()))

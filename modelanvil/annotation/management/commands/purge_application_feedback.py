"""Erase expired feedback content and its owned review/publication copies."""
from django.core.management.base import BaseCommand
from modelanvil.annotation.feedback import purge


class Command(BaseCommand):
    help = 'Erase all expired application feedback and its owned source artifacts; run periodically.'
    def handle(self,*args,**options):
        self.stdout.write(f'deleted_feedback={purge()}')

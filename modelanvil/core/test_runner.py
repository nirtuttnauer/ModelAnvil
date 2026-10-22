from django.db import connection
from django.test.runner import DiscoverRunner


class Runner(DiscoverRunner):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # SQLite runs do not select pg tests. `--tag=pg` still runs them.
        if connection.vendor != "postgresql" and "pg" not in self.tags:
            self.exclude_tags.add("pg")

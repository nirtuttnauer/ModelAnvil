from django.db import connection
from django.test import TestCase, tag
from pgvector import Vector


@tag("pg")
class VectorExtensionTests(TestCase):
    def test_vector_extension_round_trip(self):
        self.assertEqual(connection.vendor, "postgresql")
        literal = Vector([1.0, 2.0, 3.0]).to_text()
        with connection.cursor() as cursor:
            cursor.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            self.assertEqual(cursor.fetchone()[0], "vector")
            cursor.execute("SELECT %s::vector <-> '[1,2,4]'::vector", [literal])
            distance = cursor.fetchone()[0]
        self.assertEqual(float(distance), 1.0)

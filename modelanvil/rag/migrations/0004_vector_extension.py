from django.db import migrations


def create_vector_extension(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("CREATE EXTENSION IF NOT EXISTS vector")


class Migration(migrations.Migration):

    dependencies = [
        ("rag", "0003_private_data_policy"),
    ]

    operations = [
        migrations.RunPython(create_vector_extension, migrations.RunPython.noop),
    ]

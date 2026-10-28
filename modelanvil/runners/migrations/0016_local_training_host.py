from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('runners', '0015_arena_review_handoff')]
    operations = [migrations.CreateModel(name='LocalTrainingHost', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ('name', models.CharField(max_length=32, unique=True, default='local')),
        ('status', models.CharField(max_length=20, default='starting')),
        ('device', models.CharField(max_length=32, blank=True)),
        ('memory_bytes', models.PositiveBigIntegerField(default=0)),
        ('error', models.CharField(max_length=400, blank=True)),
        ('build_digest', models.CharField(max_length=64, blank=True)),
        ('last_heartbeat_at', models.DateTimeField(null=True)),
    ])]

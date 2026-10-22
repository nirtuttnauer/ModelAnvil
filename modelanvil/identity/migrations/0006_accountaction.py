import django.db.models.deletion
import django.utils.timezone
import modelanvil.core.ids
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('identity', '0005_uuid7_identifiers'),
    ]

    operations = [
        migrations.CreateModel(
            name='AccountAction',
            fields=[
                ('id', models.UUIDField(default=modelanvil.core.ids.uuid7, editable=False, primary_key=True, serialize=False)),
                ('purpose', models.CharField(choices=[('password_reset', 'Password reset'), ('invitation', 'Invitation')], max_length=32)),
                ('email', models.EmailField(max_length=254)),
                ('secret_hash', models.CharField(max_length=64, unique=True)),
                ('role', models.CharField(choices=[('owner', 'Owner'), ('admin', 'Admin'), ('manager', 'Manager'), ('engineer', 'Engineer'), ('viewer', 'Viewer'), ('worker', 'Worker')], default='engineer', max_length=16)),
                ('expires_at', models.DateTimeField()),
                ('used_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('project', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='account_actions', to='identity.project')),
                ('tenant', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='account_actions', to='identity.tenant')),
            ],
            options={'indexes': [models.Index(fields=['purpose', 'email'], name='identity_ac_purpose_d3dbfd_idx')]},
        ),
    ]

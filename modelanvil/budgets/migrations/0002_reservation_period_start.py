import datetime

from django.db import migrations, models


def backfill_period_start(apps, schema_editor):
    Reservation = apps.get_model("budgets", "BudgetReservation")
    Policy = apps.get_model("budgets", "BudgetPolicy")
    alias = schema_editor.connection.alias
    policies = {policy.pk: policy.period for policy in Policy.objects.using(alias).all()}
    for reservation in Reservation.objects.using(alias).all().iterator():
        period = policies.get(reservation.policy_id)
        if period == "daily":
            start = reservation.reserved_at.date()
        elif period == "monthly":
            start = reservation.reserved_at.date().replace(day=1)
        else:
            start = datetime.date(1970, 1, 1)
        Reservation.objects.using(alias).filter(pk=reservation.pk).update(period_start=start)


class Migration(migrations.Migration):
    dependencies = [("budgets", "0001_initial")]
    operations = [
        migrations.AddField(
            model_name="budgetreservation",
            name="period_start",
            field=models.DateField(db_index=True, default=datetime.date(1970, 1, 1)),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_period_start, migrations.RunPython.noop),
    ]

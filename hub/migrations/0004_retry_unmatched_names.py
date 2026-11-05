from django.db import migrations


def forget_unmatched_names(apps, schema_editor):
    """Searches now include aliases, so names that found nothing deserve another try."""
    apps.get_model("hub", "ArtistName").objects.filter(artist=None).delete()


class Migration(migrations.Migration):
    dependencies = [("hub", "0003_admin_and_music")]

    operations = [migrations.RunPython(forget_unmatched_names, migrations.RunPython.noop)]

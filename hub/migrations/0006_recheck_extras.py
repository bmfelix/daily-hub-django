from django.db import migrations


def recheck(apps, schema_editor):
    """Fetch Wikipedia again for saved artists, this time with the photo."""
    apps.get_model("hub", "Artist").objects.update(extras_checked_at=None)


class Migration(migrations.Migration):
    dependencies = [("hub", "0005_wikipedia_image")]

    operations = [migrations.RunPython(recheck, migrations.RunPython.noop)]

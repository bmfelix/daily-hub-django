from django.db import migrations


def seed(apps, schema_editor):
    """A starting point for the About page. Everything here can be edited in the admin."""
    apps.get_model("hub", "Profile").objects.create(name="Brad Felix")
    apps.get_model("hub", "Project").objects.create(
        title="Daily Hub",
        description="A personal dashboard built three times, in Django, Next.js, and Laravel, to compare the frameworks.",
        tech="Django, Next.js, Laravel, Postgres, Docker",
        repo_url="https://github.com/bmfelix/daily-hub-django",
    )


class Migration(migrations.Migration):
    dependencies = [("hub", "0008_charts_about")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]

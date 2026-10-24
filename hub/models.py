from django.db import models


class Task(models.Model):
    title = models.CharField(max_length=200)
    done = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["done", "-created_at"]

    def __str__(self):
        return self.title


class Note(models.Model):
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title


class Artist(models.Model):
    """Everything MusicBrainz has on one artist, saved so it is fetched only once."""

    mbid = models.UUIDField("MusicBrainz ID", unique=True)
    name = models.CharField(max_length=300)
    data = models.JSONField(help_text="The full MusicBrainz artist record.")
    release_groups = models.JSONField(default=list, help_text="Every album, EP, and single.")
    fetched_at = models.DateTimeField()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ArtistName(models.Model):
    """A name as the radio spells it, and the artist it matched (or none)."""

    key = models.CharField(max_length=300, unique=True, help_text="The name in lowercase.")
    name = models.CharField(max_length=300)
    artist = models.ForeignKey(Artist, null=True, blank=True, on_delete=models.CASCADE, related_name="names")
    checked_at = models.DateTimeField()

    def __str__(self):
        return self.name

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Entry


@receiver(post_delete, sender=Entry)
def delete_audio_file(sender, instance, **kwargs):
    """Remove the object from storage when an entry (or its whole container) is deleted."""
    if instance.audio:
        storage, name = instance.audio.storage, instance.audio.name
        transaction.on_commit(lambda: storage.delete(name))

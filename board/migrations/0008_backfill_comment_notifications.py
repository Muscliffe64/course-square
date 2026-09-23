from django.db import migrations


def backfill(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Comment = apps.get_model("board", "Comment")
    Notification = apps.get_model("board", "Notification")
    alias = schema_editor.connection.alias
    staff_ids = list(User.objects.using(alias).filter(is_staff=True, is_active=True).values_list("pk", flat=True))
    for comment in Comment.objects.using(alias).filter(author__is_staff=False).iterator():
        for recipient_id in staff_ids:
            item, created = Notification.objects.using(alias).get_or_create(
                recipient_id=recipient_id, comment_id=comment.pk,
                defaults={"actor_id": comment.author_id, "post_id": comment.post_id, "kind": "new_comment"},
            )
            if created:
                Notification.objects.using(alias).filter(pk=item.pk).update(created_at=comment.created_at)


class Migration(migrations.Migration):
    dependencies = [("board", "0007_comment_parent_notification")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]

from django.db import migrations


def forward(apps, schema_editor):
    Subject = apps.get_model("questions", "Subject")
    Topic = apps.get_model("questions", "Topic")
    by_teacher = {}
    for t in Topic.objects.filter(subject__isnull=True).order_by("id"):
        subj = by_teacher.get(t.teacher_id)
        if subj is None:
            subj, _ = Subject.objects.get_or_create(teacher_id=t.teacher_id, name="Python")
            by_teacher[t.teacher_id] = subj
        t.subject = subj
        t.order = Topic.objects.filter(subject=subj).count() + 1
        t.save(update_fields=["subject", "order"])


class Migration(migrations.Migration):
    dependencies = [("questions", "0002_alter_topic_options_question_code_and_more")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]

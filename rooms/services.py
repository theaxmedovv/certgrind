from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction

from django.utils import timezone

from .models import Room, RoomQuestion


def snapshot_question(question):
    """Savolning to'liq nusxasi (rasm faylini ham nusxalaydi)."""
    image_url = None
    if question.image:
        try:
            with question.image.open("rb") as f:
                name = default_storage.save(
                    f"snapshots/{question.image.name.split('/')[-1]}", ContentFile(f.read())
                )
            image_url = default_storage.url(name)
        except Exception:
            image_url = None
    return {
        "text": question.text,
        "code": question.code,
        "input_values": question.input_values,
        "topic": question.topic.name,
        "topic_order": question.topic.order,
        "external_no": question.external_no,
        "difficulty": question.difficulty,
        "image": image_url,
        "options": [
            {"id": o.id, "text": o.text, "is_correct": o.is_correct}
            for o in question.options.all()
        ],
    }


@transaction.atomic
def create_room_with_questions(teacher, data, questions, question_set=None):
    """data: name, password va Room maydonlari. Tanlangan savollarning NUSXASI saqlanadi."""
    data = dict(data)
    password = data.pop("password")
    # Eski maydonlar (tasodifiy oraliq o'rnatilguncha) oraliqning yuqori chegarasi bilan moslanadi
    if "steal_max_percent" in data:
        data.setdefault("steal_percent", data["steal_max_percent"])
    if "freeze_max_seconds" in data:
        data.setdefault("freeze_seconds", data["freeze_max_seconds"])
    room = Room(teacher=teacher, code=Room.generate_code(), question_set=question_set, **data)
    room.set_password(password)
    room.save()
    RoomQuestion.objects.bulk_create(
        [
            RoomQuestion(room=room, question=q, order=i, snapshot=snapshot_question(q))
            for i, q in enumerate(questions)
        ]
    )
    return room


def create_room_from_set(teacher, data, question_set):
    """To'plamdagi savollarning NUSXASI (snapshot) bilan xona yaratadi."""
    questions = [
        it.question
        for it in question_set.items.select_related("question__topic").prefetch_related("question__options")
    ]
    room = create_room_with_questions(teacher, data, questions, question_set=question_set)
    question_set.last_used_at = timezone.now()
    question_set.save(update_fields=["last_used_at"])
    return room

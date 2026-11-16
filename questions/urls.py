from django.urls import path

from . import views, views_sets

urlpatterns = [
    path("savollar/", views.question_list, name="question_list"),
    path("savollar/yangi/", views.question_edit, name="question_create"),
    path("savollar/<int:pk>/", views.question_edit, name="question_edit"),
    path("savollar/<int:pk>/ochirish/", views.question_delete, name="question_delete"),
    path("savollar/import/", views.question_import, name="question_import"),
    path("savollar/shablon/", views.import_template, name="import_template"),
    path("fanlar/", views.subject_list, name="subject_list"),
    path("fanlar/yangi/", views.subject_create, name="subject_create"),
    path("fanlar/<int:pk>/ochirish/", views.subject_delete, name="subject_delete"),
    path("fanlar/<int:pk>/eksport/", views.subject_export, name="subject_export"),
    path("fanlar/<int:subject_pk>/mavzu/", views.topic_create, name="topic_create"),
    path("fanlar/<int:subject_pk>/tartib/", views.topic_reorder, name="topic_reorder"),
    path("mavzu/<int:pk>/nom/", views.topic_rename, name="topic_rename"),
    path("mavzu/<int:pk>/ochirish/", views.topic_delete, name="topic_delete"),
    path("toplamlar/", views_sets.set_list, name="set_list"),
    path("toplamlar/yangi/", views_sets.set_generate, name="set_generate"),
    path("toplamlar/taqsimot/", views_sets.set_plan, name="set_plan"),
    path("toplamlar/hammasi/", views_sets.set_auto_all, name="set_auto_all"),
    path("toplamlar/<int:pk>/", views_sets.set_detail, name="set_detail"),
    path("toplamlar/<int:pk>/nom/", views_sets.set_rename, name="set_rename"),
    path("toplamlar/<int:pk>/aralashtirish/", views_sets.set_reshuffle, name="set_reshuffle"),
    path("toplamlar/<int:pk>/nusxa/", views_sets.set_copy, name="set_copy"),
    path("toplamlar/<int:pk>/ochirish/", views_sets.set_delete, name="set_delete"),
    path("toplamlar/<int:pk>/eksport/", views_sets.set_export, name="set_export"),
    path("toplamlar/<int:pk>/savol/<int:item_pk>/almashtirish/", views_sets.set_item_replace, name="set_item_replace"),
    path("toplamlar/<int:pk>/savol/<int:item_pk>/ochirish/", views_sets.set_item_remove, name="set_item_remove"),
    path("sinflar/", views.classes, name="classes"),
    path("sinflar/<int:pk>/ochirish/", views.class_delete, name="class_delete"),
]

import datetime
from importlib import import_module

from django.apps import apps as django_apps
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Lecture, LoginEvent, Resource, ResourceAccess, VisitLog
from .participation import participation


def resource(title, lecture=None, name="notes.pdf", body=b"%PDF-1.4 x"):
    item = Resource(title=title, lecture=lecture); item.file.save(name, ContentFile(body), save=False); item.save()
    return item


class ParticipationTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user("teacher", password="pw", first_name="老师", is_staff=True)
        self.a = User.objects.create_user("20260001", password="20260001", first_name="张三")
        self.b = User.objects.create_user("20260002", password="20260002", first_name="李四")
        self.c = User.objects.create_user("20260003", password="20260003", first_name="王五")
        past = timezone.localdate() - datetime.timedelta(days=7)
        self.l1 = Lecture.objects.create(number=1, date=past - datetime.timedelta(days=7))
        self.l2 = Lecture.objects.create(number=2, date=past)
        self.l3 = Lecture.objects.create(number=3, date=timezone.localdate() + datetime.timedelta(days=7))
        self.r1 = resource("第一讲讲稿", self.l1)
        self.r2 = resource("第二讲讲稿", self.l2, name="notes.md", body=b"# hi")
        self.r3 = resource("第三讲预习", self.l3)
        self.loose = resource("没挂讲次")

    def login(self, user):
        self.client.post(reverse("login"), {"username": user.username, "password": user.username})

    def test_real_login_is_counted(self):
        self.login(self.a); self.client.logout(); self.login(self.a)
        self.assertEqual(LoginEvent.objects.filter(user=self.a).count(), 2)
        self.client.logout()
        self.client.post(reverse("login"), {"username": self.b.username, "password": "wrong"})
        self.assertFalse(LoginEvent.objects.filter(user=self.b).exists())

    def test_download_and_read_are_recorded(self):
        self.client.force_login(self.a)
        self.client.get(reverse("board:resource_download", args=[self.r1.pk]))
        self.client.get(reverse("board:resource_read", args=[self.r2.pk]))
        # 非 Markdown 的「阅读」会跳到下载：只算下载那一次
        self.client.get(reverse("board:resource_read", args=[self.r1.pk]), follow=True)
        kinds = list(ResourceAccess.objects.filter(user=self.a).order_by("pk").values_list("resource_id", "kind"))
        self.assertEqual(kinds, [(self.r1.pk, "download"), (self.r2.pk, "read"), (self.r1.pk, "download")])

    def test_coverage_counts_only_held_lectures(self):
        for r in (self.r1, self.r1, self.r2, self.r3, self.loose):
            ResourceAccess.objects.create(user=self.a, resource=r)
        ResourceAccess.objects.create(user=self.b, resource=self.r1)
        rows, lectures, held, summary = participation("coverage")
        self.assertEqual([l.number for l in lectures], [1, 2, 3])
        self.assertEqual([l.number for l in held], [1, 2])
        by = {r.username: r for r in rows}
        self.assertEqual((by["20260001"].downloads, by["20260001"].distinct_resources, by["20260001"].covered_count), (5, 4, 2))
        self.assertEqual(by["20260002"].covered_count, 1)
        self.assertEqual(rows[0].username, "20260001")
        self.assertEqual(summary["full_coverage"], 1)
        self.assertEqual(summary["unassigned_resources"], 1)

    def test_never_logged_in(self):
        self.login(self.a)
        rows, *_ , summary = participation(only_never=True)
        self.assertEqual([r.username for r in rows], ["20260002", "20260003"])
        self.assertEqual((summary["students"], summary["logged_in"], summary["never"]), (3, 1, 2))

    def test_teacher_only(self):
        url = reverse("admin:board_participation")
        self.client.force_login(self.a)
        self.assertNotEqual(self.client.get(url).status_code, 200)
        self.client.force_login(self.teacher)
        response = self.client.get(url)
        self.assertContains(response, "从未登录"); self.assertContains(response, "20260003")
        self.assertNotContains(response, ">teacher<")
        export = self.client.get(url + "?export=xlsx")
        self.assertEqual(export["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertContains(self.client.get(reverse("admin:index")), url)

    def test_backfill_from_visit_log(self):
        when = timezone.now() - datetime.timedelta(days=3)
        for path in (f"/resources/{self.r1.pk}/download/", f"/resources/{self.r2.pk}/read/",
                     f"/resources/{self.r1.pk}/read/", "/resources/999/download/", "/resources/"):
            VisitLog.objects.create(user=self.a, path=path)
        VisitLog.objects.create(user=None, path=f"/resources/{self.r1.pk}/download/")
        VisitLog.objects.update(created_at=when)
        backfill = import_module("board.migrations.0011_login_event_resource_access").backfill_resource_access
        ResourceAccess.objects.all().delete()
        backfill(django_apps, type("E", (), {"connection": connection})())
        got = sorted(ResourceAccess.objects.values_list("resource_id", "kind"))
        self.assertEqual(got, sorted([(self.r1.pk, "download"), (self.r2.pk, "read")]))
        self.assertTrue(all(abs((a.created_at - when).total_seconds()) < 1 for a in ResourceAccess.objects.all()))

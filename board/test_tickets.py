from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Notification, Ticket

User = get_user_model()


class AskTeacherRoundTripTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user("teacher", password="pw", first_name="韩老师", is_staff=True)
        self.student = User.objects.create_user("20260001", password="pw", first_name="张三")
        self.other = User.objects.create_user("20260002", password="pw", first_name="李四")

    def ask(self, body="反向传播没听懂"):
        self.client.force_login(self.student)
        self.client.post(reverse("board:quick_post"), {"body": body, "mode": "teacher"})
        return Ticket.objects.get(body=body)

    def test_teacher_sees_ticket_in_pending_and_sidebar_count(self):
        ticket = self.ask()
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("board:pending"))
        self.assertContains(response, "反向传播没听懂")
        self.assertContains(response, f'id="ticket-{ticket.pk}"')
        self.assertEqual(response.context["pending_count"], 1)
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.teacher_read_at)

    def test_student_sees_status_and_reply(self):
        ticket = self.ask()
        page = self.client.get(reverse("board:my_questions"))
        self.assertContains(page, "反向传播没听懂")
        self.assertContains(page, "已送达")

        self.client.force_login(self.teacher)
        self.client.get(reverse("board:pending"))
        self.client.post(reverse("board:ticket_respond", args=[ticket.pk]), {"action": "reply", "reply": "看第三讲讲义第 5 页"})
        self.assertEqual(self.client.get(reverse("board:pending")).context["pending_count"], 0)

        note = Notification.objects.get(recipient=self.student)
        self.assertEqual(note.kind, "ticket_reply")
        self.client.force_login(self.student)
        self.assertContains(self.client.get(reverse("board:notifications")), "老师回复了你的提问")
        opened = self.client.post(reverse("board:notification_open", args=[note.pk]))
        self.assertEqual(opened["Location"], reverse("board:my_questions") + f"#ticket-{ticket.pk}")
        page = self.client.get(reverse("board:my_questions"))
        self.assertContains(page, "看第三讲讲义第 5 页")
        self.assertContains(page, "老师已回复")

    def test_in_class_and_read_only(self):
        a, b = self.ask("问题甲"), self.ask("问题乙")
        self.client.force_login(self.teacher)
        self.client.post(reverse("board:ticket_respond", args=[a.pk]), {"action": "in_class"})
        self.client.post(reverse("board:ticket_respond", args=[b.pk]), {"action": "read"})
        self.assertEqual(Notification.objects.filter(recipient=self.student).count(), 1)  # 已读不打扰学生
        self.client.force_login(self.student)
        page = self.client.get(reverse("board:my_questions"))
        self.assertContains(page, "老师会在课上回应")
        self.assertContains(page, "老师已读")

    def test_empty_reply_rejected_and_bad_action_404(self):
        ticket = self.ask()
        self.client.force_login(self.teacher)
        self.client.post(reverse("board:ticket_respond", args=[ticket.pk]), {"action": "reply", "reply": "  "})
        ticket.refresh_from_db()
        self.assertEqual(ticket.response, "")
        self.assertEqual(self.client.post(reverse("board:ticket_respond", args=[ticket.pk]), {"action": "delete"}).status_code, 404)

    def test_privacy(self):
        ticket = self.ask()
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(reverse("board:my_questions")), "反向传播没听懂")
        self.assertEqual(self.client.post(reverse("board:ticket_respond", args=[ticket.pk]), {"action": "read"}).status_code, 403)
        self.client.force_login(self.student)
        self.assertEqual(self.client.post(reverse("board:ticket_respond", args=[ticket.pk]), {"action": "reply", "reply": "自问自答"}).status_code, 403)

    def test_ask_link_preselects_teacher_mode(self):
        self.client.force_login(self.student)
        self.assertContains(self.client.get("/?ask=1"), 'value="teacher" checked')

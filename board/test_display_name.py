from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class DisplayNameFallbackTests(TestCase):
    """A student without a name must never be labelled 课程管理员."""

    def test_nameless_student_shows_student_id(self):
        student = User.objects.create_user("1", password="a-real-password-123")
        self.client.force_login(student)
        html = self.client.get(reverse("board:settings")).content.decode()
        self.assertNotIn("课程管理员", html)
        self.assertIn("学号 1", html)

    def test_nameless_staff_still_shows_admin(self):
        staff = User.objects.create_user("admin", password="a-real-password-123", is_staff=True)
        self.client.force_login(staff)
        html = self.client.get(reverse("board:settings")).content.decode()
        self.assertIn("课程管理员", html)

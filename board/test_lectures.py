import io
import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .management.commands.notify_pending import build_request, in_quiet_hours
from .models import Comment, Lecture, Like, Notification, Post, TeacherDigest, Ticket
from .pending import derive_title, pending_comments, pending_posts
from .tickets import pseudonym


class Base(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.teacher = User.objects.create_user("teacher", first_name="韩老师", is_staff=True)
        self.student = User.objects.create_user("s1", first_name="张一")
        self.other = User.objects.create_user("s2", first_name="李二")
        self.past = Lecture.objects.create(number=2, title="感知机", date=today - timedelta(days=5))
        self.next = Lecture.objects.create(number=3, title="神经网络", date=today + timedelta(days=2))
        self.later = Lecture.objects.create(number=4, date=today + timedelta(days=9))


class LectureTests(Base):
    def test_upcoming_and_latest_held(self):
        self.assertEqual(Lecture.upcoming(), self.next)
        self.assertEqual(Lecture.latest_held(), self.past)
        today_lecture = Lecture.objects.create(number=5, date=timezone.localdate())
        self.assertEqual(Lecture.upcoming(), today_lecture)
        self.assertEqual(Lecture.latest_held(), today_lecture)


class DeriveTitleTests(TestCase):
    def test_first_sentence_or_truncated(self):
        self.assertEqual(derive_title("扩散模型怎么画图？我一直没懂。"), "扩散模型怎么画图？")
        self.assertEqual(derive_title("  第一行\n第二行"), "第一行")
        self.assertEqual(derive_title("没有标点" * 20), ("没有标点" * 20)[:30] + "…")
        self.assertEqual(derive_title("短句"), "短句")
        # 最早出现的句号优先，而不是按标点种类的顺序
        self.assertEqual(derive_title("为什么？因为。"), "为什么？")


class QuickPostTests(Base):
    url = reverse("board:quick_post")

    def test_login_and_post_only(self):
        self.assertEqual(self.client.post(self.url, {"body": "x"}).status_code, 302)
        self.assertFalse(Post.objects.exists())
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_creates_post_with_derived_title(self):
        self.client.force_login(self.student)
        response = self.client.post(self.url, {"body": "  注意力机制到底在注意什么？上课没跟上。 ", "kind": "topic", "anonymous": "on"})
        post = Post.objects.get()
        self.assertEqual(post.title, "注意力机制到底在注意什么？")
        self.assertEqual(post.body, "注意力机制到底在注意什么？上课没跟上。")
        self.assertTrue(post.anonymous)
        self.assertEqual(post.author, self.student)
        self.assertRedirects(response, reverse("board:home") + f"?kind=topic#post-{post.pk}", fetch_redirect_response=False)

    def test_showcase_kind_and_bad_kind_falls_back(self):
        self.client.force_login(self.student)
        self.client.post(self.url, {"body": "做了个东西", "kind": "showcase"})
        self.client.post(self.url, {"body": "另一个", "kind": "evil"})
        self.assertEqual(sorted(Post.objects.values_list("kind", flat=True)), ["showcase", "topic"])

    def test_empty_body_rejected_and_draft_kept(self):
        self.client.force_login(self.student)
        self.client.post(self.url, {"body": "   ", "anonymous": "on"})
        self.assertFalse(Post.objects.exists())
        long_text = "长" * 1001
        response = self.client.post(self.url, {"body": long_text}, follow=True)
        self.assertFalse(Post.objects.exists())
        self.assertContains(response, "最多 1000 字")
        self.assertContains(response, "长" * 1000)  # 输入没有丢

    def test_double_submit_is_idempotent(self):
        self.client.force_login(self.student)
        self.client.post(self.url, {"body": "同一句话"})
        self.client.post(self.url, {"body": "同一句话"})
        self.assertEqual(Post.objects.count(), 1)

    def test_to_teacher_makes_private_real_name_ticket(self):
        self.client.force_login(self.student)
        response = self.client.post(self.url, {"body": "反向传播完全没懂", "to_teacher": "on", "anonymous": "on"}, follow=True)
        self.assertFalse(Post.objects.exists())
        ticket = Ticket.objects.get()
        self.assertEqual((ticket.author, ticket.lecture), (self.student, self.past))
        self.assertContains(response, "只有老师能看到")
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get("/"), "反向传播完全没懂")

    def test_composer_on_home_but_not_on_resource_tab(self):
        self.client.force_login(self.student)
        self.assertContains(self.client.get("/"), 'data-composer')
        self.assertContains(self.client.get("/"), "只给老师看")
        self.assertNotContains(self.client.get("/", {"kind": "resource"}), 'data-composer')
        self.client.force_login(self.teacher)
        self.assertNotContains(self.client.get("/"), "只给老师看")


class PlanTests(Base):
    def setUp(self):
        super().setUp()
        self.post = Post.objects.create(author=self.student, title="想听 RAG", body="b", kind="topic")
        self.url = reverse("board:post_plan", args=[self.post.pk])

    def test_student_cannot_plan(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.post(self.url, {"lecture": self.next.pk}).status_code, 403)
        self.post.refresh_from_db()
        self.assertIsNone(self.post.planned_lecture)

    def test_plan_notifies_and_shows_badge_then_unplan(self):
        self.client.force_login(self.teacher)
        self.client.post(self.url, {"lecture": self.next.pk})
        self.post.refresh_from_db()
        self.assertEqual((self.post.planned_lecture, self.post.status), (self.next, "planned"))
        note = Notification.objects.get(recipient=self.student)
        self.assertEqual(note.kind, Notification.Kind.POST_PLANNED)
        self.client.post(self.url, {"lecture": self.next.pk})  # 再排一次同一讲不重复通知
        self.assertEqual(Notification.objects.filter(recipient=self.student).count(), 1)
        self.client.force_login(self.student)
        self.assertContains(self.client.get("/"), "排进第 3 讲")
        self.assertContains(self.client.get(reverse("board:notifications")), "老师把你的帖子排进了第 3 讲")
        self.client.force_login(self.teacher)
        self.client.post(self.url, {})
        self.post.refresh_from_db()
        self.assertEqual((self.post.planned_lecture, self.post.status), (None, "open"))

    def test_past_lecture_badge(self):
        Post.objects.filter(pk=self.post.pk).update(planned_lecture=self.past, status="planned")
        self.client.force_login(self.student)
        self.assertContains(self.client.get(reverse("board:post_detail", args=[self.post.pk])), "✓ 第 2 讲讲过")

    def test_unknown_lecture_404(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.post(self.url, {"lecture": 999}).status_code, 404)

    def test_staff_detail_has_plan_form_student_does_not(self):
        detail = reverse("board:post_detail", args=[self.post.pk])
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get(detail), "排进这一讲")
        self.client.force_login(self.student)
        self.assertNotContains(self.client.get(detail), "排进这一讲")


class RankingTests(Base):
    def setUp(self):
        super().setUp()
        self.a = Post.objects.create(author=self.student, title="候选甲", body="b", kind="topic")
        self.b = Post.objects.create(author=self.other, title="候选乙", body="b", kind="topic")
        self.done = Post.objects.create(author=self.other, title="已排的", body="b", kind="topic", planned_lecture=self.next, status="planned")
        self.share = Post.objects.create(author=self.other, title="一个分享", body="b", kind="showcase")
        for user in (self.student, self.other):
            Like.objects.create(post=self.b, user=user)
        Like.objects.create(post=self.done, user=self.student)
        Like.objects.create(post=self.share, user=self.student)

    def test_order_promise_and_voted_state(self):
        self.client.force_login(self.student)
        response = self.client.get("/")
        ranking = response.context["ranking"]
        self.assertEqual([p.title for p in ranking], ["候选乙", "候选甲"])
        self.assertTrue(ranking[0].voted)
        self.assertFalse(ranking[1].voted)
        self.assertEqual((ranking[0].percent, ranking[1].percent), (100, 0))
        self.assertContains(response, "票数最高的一条，第 3 讲一定讲。")
        self.assertEqual(response.context["ranking_voters"], 2)

    def test_vote_via_like_returns_to_ranking(self):
        self.client.force_login(self.student)
        response = self.client.post(reverse("board:post_like", args=[self.a.pk]), {"next": "/#ranking"})
        self.assertEqual(response["Location"], "/#ranking")
        self.assertTrue(Like.objects.filter(post=self.a, user=self.student).exists())

    def test_only_on_unfiltered_first_page(self):
        self.client.force_login(self.student)
        self.assertIn("ranking", self.client.get("/", {"kind": "topic"}).context)
        self.assertNotIn("ranking", self.client.get("/", {"kind": "showcase"}).context)
        self.assertNotIn("ranking", self.client.get("/", {"week": "current"}).context)

    def test_without_lectures_still_promises_next_class(self):
        Lecture.objects.all().delete()
        self.client.force_login(self.student)
        self.assertContains(self.client.get("/"), "票数最高的一条，下节课一定讲。")

    def test_staff_one_click_plan_from_ranking(self):
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get("/"), "排进第 3 讲</button>")


class PendingTests(Base):
    def setUp(self):
        super().setUp()
        self.post = Post.objects.create(author=self.student, title="没人理的问题", body="b", kind="topic")
        self.teacher_post = Post.objects.create(author=self.teacher, title="老师的帖子", body="b", kind="topic")

    def test_student_forbidden(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse("board:pending")).status_code, 403)
        self.assertEqual(self.client.post(reverse("board:pending_dismiss"), {"type": "post", "id": self.post.pk}).status_code, 403)
        self.assertNotContains(self.client.get("/"), "待回应")

    def test_post_leaves_list_after_teacher_comment(self):
        self.assertEqual(list(pending_posts()), [self.post])
        Comment.objects.create(post=self.post, author=self.teacher, body="收到")
        self.assertEqual(list(pending_posts()), [])

    def test_comment_pending_until_later_teacher_comment(self):
        early = Comment.objects.create(post=self.teacher_post, author=self.teacher, body="老师先说")
        question = Comment.objects.create(post=self.teacher_post, author=self.student, body="学生追问")
        self.assertEqual(list(pending_comments()), [question])
        self.assertNotIn(early, pending_comments())
        Comment.objects.create(post=self.teacher_post, author=self.teacher, body="回答", parent=question)
        self.assertEqual(list(pending_comments()), [])

    def test_page_sidebar_count_and_dismiss(self):
        comment = Comment.objects.create(post=self.teacher_post, author=self.other, body="谢谢老师", anonymous=True)
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("board:pending"))
        self.assertContains(response, "没人理的问题")
        self.assertContains(response, "谢谢老师")
        self.assertContains(response, "李二")  # 老师能看到匿名者真名
        self.assertEqual(response.context["pending_count"], 2)
        response = self.client.post(reverse("board:pending_dismiss"), {"type": "comment", "id": comment.pk, "anchor": "comment-1"})
        self.assertEqual(response["Location"], reverse("board:pending") + "#comment-1")
        self.client.post(reverse("board:pending_dismiss"), {"type": "post", "id": self.post.pk, "anchor": "javascript:x"})
        self.assertEqual(self.client.get(reverse("board:pending")).context["pending_count"], 0)
        self.assertEqual(self.client.post(reverse("board:pending_dismiss"), {"type": "user", "id": 1}).status_code, 404)

    def test_planning_clears_pending(self):
        self.client.force_login(self.teacher)
        self.client.post(reverse("board:post_plan", args=[self.post.pk]), {"lecture": self.next.pk})
        self.assertEqual(list(pending_posts()), [])


class FakeResponse(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *args): return False


@override_settings(SECRET_KEY="test-secret")
class NotifyTests(Base):
    def setUp(self):
        super().setUp()
        Post.objects.create(author=self.student, title="新问题", body="b", kind="topic")
        Ticket.objects.create(author=self.student, lecture=self.past, body="小票内容")

    def run_command(self, env, reply=b'{"errcode":0}'):
        out = io.StringIO()
        with mock.patch.dict("os.environ", env, clear=False), \
             mock.patch("urllib.request.urlopen", return_value=FakeResponse(reply)) as urlopen:
            call_command("notify_pending", stdout=out)
        return out.getvalue(), urlopen

    def test_sends_once_then_waits_for_new_items(self):
        env = {"TEACHER_NOTIFY_WEBHOOK": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=k", "COURSE_SITE_URL": "https://example.test", "TEACHER_NOTIFY_QUIET_HOURS": ""}
        out, urlopen = self.run_command(env)
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertIn("新增 帖子 1、小票 1", payload["text"]["content"])
        self.assertIn("https://example.test/pending/", payload["text"]["content"])
        self.assertNotIn("张一", payload["text"]["content"])
        self.assertEqual(TeacherDigest.objects.count(), 1)
        out, urlopen = self.run_command(env)
        urlopen.assert_not_called()
        self.assertIn("没有新的待回应", out)

    def test_error_reply_is_not_recorded(self):
        env = {"TEACHER_NOTIFY_WEBHOOK": "https://qyapi.weixin.qq.com/x", "TEACHER_NOTIFY_QUIET_HOURS": ""}
        with self.assertRaises(CommandError):
            self.run_command(env, reply=b'{"errcode":93000,"errmsg":"invalid key"}')
        self.assertFalse(TeacherDigest.objects.exists())

    def test_no_webhook_skips(self):
        out, urlopen = self.run_command({"TEACHER_NOTIFY_WEBHOOK": ""})
        urlopen.assert_not_called()
        self.assertIn("跳过", out)

    def test_quiet_hours(self):
        self.assertTrue(in_quiet_hours("23-8", 23))
        self.assertTrue(in_quiet_hours("23-8", 3))
        self.assertFalse(in_quiet_hours("23-8", 8))
        self.assertTrue(in_quiet_hours("12-14", 13))
        self.assertFalse(in_quiet_hours("", 3))

    def test_serverchan_format(self):
        request = build_request("https://sctapi.ftqq.com/KEY.send", "标题", "a\nb")
        self.assertIn(b"title=", request.data)
        self.assertEqual(request.get_header("Content-type"), "application/x-www-form-urlencoded")


@override_settings(SECRET_KEY="test-secret")
class TicketExportTests(Base):
    def test_export_replaces_names_with_stable_codes(self):
        Ticket.objects.create(author=self.student, lecture=self.past, body="没懂梯度")
        Ticket.objects.create(author=self.student, lecture=self.next, body="还是没懂")
        self.teacher.is_superuser = True
        self.teacher.save()
        self.client.force_login(self.teacher)
        response = self.client.post(reverse("admin:board_lecture_changelist"), {
            "action": "export_tickets", "_selected_action": [self.past.pk, self.next.pk]})
        text = response.content.decode("utf-8-sig")
        self.assertIn("没懂梯度", text)
        self.assertNotIn("张一", text)
        self.assertEqual(text.count(pseudonym(self.student.pk)), 2)
        self.assertNotEqual(pseudonym(self.student.pk), pseudonym(self.other.pk))

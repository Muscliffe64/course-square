"""把新出现的「待回应」推送到老师的手机（站外提醒）。

由 systemd timer 每 30 分钟跑一次。只有上次推送之后出现了新的待回应内容才会发，
没有新内容就什么都不做。推送里只有数量和标题，不含学生姓名。

配置（/etc/course-square.env）：
  TEACHER_NOTIFY_WEBHOOK   推送地址，支持：
      Server 酱        https://sctapi.ftqq.com/<SendKey>.send       （推到个人微信，推荐）
      企业微信群机器人  https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...
      飞书群机器人      https://open.feishu.cn/open-apis/bot/v2/hook/...
      钉钉群机器人      https://oapi.dingtalk.com/robot/send?access_token=...
  COURSE_SITE_URL          站点地址，用于生成「待回应」链接，例如 https://123.57.56.38
  TEACHER_NOTIFY_QUIET_HOURS  免打扰时段，例如 23-8；这段时间不推送，内容攒到下一次
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from board.models import TeacherDigest
from board.pending import new_since, pending_counts

TIMEOUT_SECONDS = 10
MAX_LISTED = 5


def in_quiet_hours(spec, hour):
    if not spec:
        return False
    try:
        start, end = (int(part) % 24 for part in spec.split("-", 1))
    except ValueError:
        raise CommandError(f"TEACHER_NOTIFY_QUIET_HOURS 格式应为 23-8，现在是 {spec!r}")
    return start <= hour < end if start < end else hour >= start or hour < end


def build_message(posts, comments, ticket_count, total, site_url):
    parts = [f"帖子 {len(posts)}" if posts else "", f"留言 {len(comments)}" if comments else "", f"小票 {ticket_count}" if ticket_count else ""]
    title = "课程广场：新增 " + "、".join(p for p in parts if p)
    lines = [f"目前共有 {total} 条待回应。"]
    items = [f"· 帖子：{p.title[:30]}" for p in posts] + [f"· 留言：{c.body[:30]}" for c in comments]
    lines += items[:MAX_LISTED]
    if len(items) > MAX_LISTED:
        lines.append(f"……还有 {len(items) - MAX_LISTED} 条")
    if site_url:
        lines.append(site_url.rstrip("/") + "/pending/")
    return title, "\n".join(lines)


def build_request(webhook, title, body):
    host = urllib.parse.urlparse(webhook).hostname or ""
    if host.endswith("ftqq.com"):
        data = urllib.parse.urlencode({"title": title, "desp": body.replace("\n", "\n\n")}).encode()
        return urllib.request.Request(webhook, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    if host == "qyapi.weixin.qq.com":
        payload = {"msgtype": "text", "text": {"content": f"{title}\n{body}"}}
    elif host.endswith("feishu.cn") or host.endswith("larksuite.com"):
        payload = {"msg_type": "text", "content": {"text": f"{title}\n{body}"}}
    elif host == "oapi.dingtalk.com":
        payload = {"msgtype": "text", "text": {"content": f"{title}\n{body}"}}
    else:
        payload = {"title": title, "text": body}
    return urllib.request.Request(webhook, data=json.dumps(payload, ensure_ascii=False).encode(), headers={"Content-Type": "application/json"})


def check_reply(reply):
    """这些服务出错时常常仍返回 HTTP 200，要看返回体里的错误码。"""
    try:
        data = json.loads(reply)
    except ValueError:
        return
    if not isinstance(data, dict):
        return
    for key in ("errcode", "code", "StatusCode"):
        if data.get(key) not in (None, 0):
            raise CommandError(f"推送服务返回错误：{reply[:300]}")


class Command(BaseCommand):
    help = "有新的待回应内容时，推送一条提醒给老师。"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="只打印要发的内容，不发送、不记录")

    def handle(self, *args, dry_run=False, **options):
        webhook = os.getenv("TEACHER_NOTIFY_WEBHOOK", "").strip()
        if not webhook and not dry_run:
            self.stdout.write("未配置 TEACHER_NOTIFY_WEBHOOK，跳过。")
            return
        now = timezone.localtime()
        cutoff = timezone.now()
        if in_quiet_hours(os.getenv("TEACHER_NOTIFY_QUIET_HOURS", "").strip(), now.hour) and not dry_run:
            self.stdout.write("免打扰时段，跳过。")
            return
        last = TeacherDigest.objects.first()
        # 第一次运行只看最近一天，避免把历史积压一次性推过去。
        since = last.sent_at if last else now - timedelta(days=1)
        posts, comments, ticket_count = new_since(since, cutoff)
        new_count = len(posts) + len(comments) + ticket_count
        if not new_count:
            self.stdout.write("没有新的待回应。")
            return
        counts = pending_counts()
        total = counts["posts"] + counts["comments"]
        title, body = build_message(posts, comments, ticket_count, total, os.getenv("COURSE_SITE_URL", ""))
        if dry_run:
            self.stdout.write(f"{title}\n{body}")
            return
        try:
            with urllib.request.urlopen(build_request(webhook, title, body), timeout=TIMEOUT_SECONDS) as response:
                reply = response.read(2000).decode("utf-8", errors="replace")
        except OSError as exc:  # 网络错误不记录，下一次会连同新内容一起重试
            raise CommandError(f"推送失败：{exc}")
        check_reply(reply)
        TeacherDigest.objects.create(sent_at=cutoff, new_count=new_count, total_count=total)
        self.stdout.write(f"已推送：{title}（服务返回 {reply[:200]}）")

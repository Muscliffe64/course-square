"""学生参与度：登录、来访天数、资料下载，只给老师在后台看，用来参考平时分。"""
from dataclasses import dataclass, field

from django.contrib.auth.models import User
from django.db.models import Count, Min
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.utils import timezone

from .models import Lecture, LoginEvent, Resource, ResourceAccess, VisitLog

SORTS = {
    "id": ("学号", lambda r: (r.username,)),
    "downloads": ("下载次数", lambda r: (-r.downloads, -r.distinct_resources, r.username)),
    "coverage": ("覆盖讲数", lambda r: (-r.covered_count, -r.downloads, r.username)),
    "logins": ("登录次数", lambda r: (-r.logins, r.username)),
    "days": ("来过几天", lambda r: (-r.active_days, r.username)),
}


@dataclass
class StudentRow:
    username: str
    name: str
    last_login: object
    logins: int = 0
    active_days: int = 0
    downloads: int = 0
    distinct_resources: int = 0
    covered: set = field(default_factory=set)
    covered_count: int = 0

    @property
    def never_logged_in(self):
        return self.last_login is None


def lecture_columns():
    """有资料挂着的讲次，才谈得上「这讲下没下」。"""
    lectures = list(Lecture.objects.annotate(n=Count("resources")).filter(n__gt=0).order_by("number"))
    held = [lecture for lecture in lectures if lecture.is_past]
    return lectures, held


def participation(sort="id", only_never=False):
    students = User.objects.filter(is_active=True, is_staff=False, is_superuser=False).order_by("username")
    rows = {u.pk: StudentRow(u.username, u.first_name, u.last_login) for u in students}

    for item in LoginEvent.objects.filter(user_id__in=rows).values("user_id").annotate(n=Count("id")):
        rows[item["user_id"]].logins = item["n"]
    for item in (VisitLog.objects.filter(user_id__in=rows).annotate(day=TruncDate("created_at"))
                 .values("user_id").annotate(n=Count("day", distinct=True))):
        rows[item["user_id"]].active_days = item["n"]
    for item in (ResourceAccess.objects.filter(user_id__in=rows).values("user_id")
                 .annotate(n=Count("id"), distinct=Count("resource", distinct=True))):
        rows[item["user_id"]].downloads = item["n"]; rows[item["user_id"]].distinct_resources = item["distinct"]

    lectures, held = lecture_columns()
    held_ids = {lecture.pk for lecture in held}
    for user_id, lecture_id in (ResourceAccess.objects.filter(user_id__in=rows, resource__lecture__isnull=False)
                                .values_list("user_id", "resource__lecture_id").distinct()):
        rows[user_id].covered.add(lecture_id)
    for row in rows.values():
        row.covered_count = len(row.covered & held_ids)

    result = list(rows.values())
    if only_never:
        result = [row for row in result if row.never_logged_in]
    result.sort(key=SORTS.get(sort, SORTS["id"])[1])

    summary = {
        "students": len(rows),
        "logged_in": sum(1 for row in rows.values() if not row.never_logged_in),
        "never": sum(1 for row in rows.values() if row.never_logged_in),
        "login_since": LoginEvent.objects.aggregate(t=Min("created_at"))["t"],
        "download_since": ResourceAccess.objects.aggregate(t=Min("created_at"))["t"],
        "resources": Resource.objects.count(),
        "unassigned_resources": Resource.objects.filter(lecture__isnull=True).count(),
        "full_coverage": sum(1 for row in rows.values() if held and row.covered_count == len(held)),
    }
    return result, lectures, held, summary


def _local(value, fmt="%Y-%m-%d %H:%M"):
    return timezone.localtime(value).strftime(fmt) if value else ""


def participation_xlsx(rows, lectures, held):
    """用 xlsx 而不是 CSV：学号是长数字，CSV 进 Excel 会变成科学计数法。"""
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Font
    workbook = Workbook(); sheet = workbook.active; sheet.title = "参与度"
    header = ["学号", "姓名", "最近登录", "登录次数", "来过几天", "下载次数", "下载过的资料数",
              f"覆盖讲数（共 {len(held)} 讲）"] + [lecture.label for lecture in lectures]
    sheet.append(header)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append([row.username, row.name, _local(row.last_login) or "从未登录", row.logins, row.active_days,
                      row.downloads, row.distinct_resources, row.covered_count]
                     + [1 if lecture.pk in row.covered else 0 for lecture in lectures])
    for cell in sheet["A"][1:]:
        cell.number_format = "@"  # 学号当文字
    sheet.freeze_panes = "C2"
    for column, width in zip("ABCDEFGH", (14, 10, 18, 10, 10, 10, 14, 16)):
        sheet.column_dimensions[column].width = width
    buffer = BytesIO(); workbook.save(buffer)
    response = HttpResponse(buffer.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="participation-{timezone.localdate():%Y%m%d}.xlsx"'
    return response

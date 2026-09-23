"""课后小票导出：姓名换成稳定代号，方便拿到平台外做摘要。"""
import csv
import hashlib
import hmac

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone


def pseudonym(user_id):
    """同一个学生在所有讲次里代号相同（能看出同一人前后变化），但代号本身推不回是谁。"""
    digest = hmac.new(settings.SECRET_KEY.encode(), f"ticket-author:{user_id}".encode(), hashlib.sha256).hexdigest()
    return "S" + digest[:6].upper()


def tickets_csv(tickets, filename):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("﻿")  # Excel 打开不乱码
    writer = csv.writer(response)
    writer.writerow(["讲次", "代号", "内容", "提交时间"])
    for ticket in tickets.select_related("lecture").order_by("lecture__number", "created_at"):
        writer.writerow([ticket.lecture.label if ticket.lecture else "未分讲次", pseudonym(ticket.author_id),
                         ticket.body, timezone.localtime(ticket.created_at).strftime("%Y-%m-%d %H:%M")])
    return response

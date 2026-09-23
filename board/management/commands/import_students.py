import csv
import re
import warnings
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from openpyxl import load_workbook


def normalize_id(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    result = str(value).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,150}", result):
        raise CommandError("学号只能包含 ASCII 字母、数字、下划线或连字符。")
    return result


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"student_id", "name"}.issubset({x.strip() for x in reader.fieldnames}):
            raise CommandError("CSV 必须包含 student_id,name 表头。")
        for row in reader:
            yield row.get("student_id"), row.get("name")


def read_xlsx(path):
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Workbook contains no default style", category=UserWarning)
        book = load_workbook(path, read_only=True, data_only=True)
    sheet = book.active
    sheet.reset_dimensions()
    rows = sheet.iter_rows(values_only=True)
    header = None
    for number, row in enumerate(rows, 1):
        values = [str(value).strip() if value is not None else "" for value in row]
        if "学号" in values and "姓名" in values:
            header = (values.index("学号"), values.index("姓名"))
            break
        if number >= 30:
            break
    if header is None:
        raise CommandError("前 30 行未找到学号/姓名表头。")
    for row in rows:
        student_id = row[header[0]] if len(row) > header[0] else None
        name = row[header[1]] if len(row) > header[1] else None
        if student_id is not None or name is not None:
            yield student_id, name
    book.close()


class Command(BaseCommand):
    help = "Import course students from CSV or XLSX."
    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--dry-run", action="store_true")
    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.is_file():
            raise CommandError("名单文件不存在。")
        source = read_csv(path) if path.suffix.lower() == ".csv" else read_xlsx(path) if path.suffix.lower() == ".xlsx" else None
        if source is None:
            raise CommandError("仅支持 CSV 和 XLSX。")
        records = {}
        for raw_id, raw_name in source:
            student_id = normalize_id(raw_id)
            name = str(raw_name or "").strip()
            if not student_id or not name:
                raise CommandError("学号和姓名不能为空。")
            if student_id in records and records[student_id] != name:
                raise CommandError("名单中存在冲突的重复学号。")
            records[student_id] = name
        created = updated = unchanged = 0
        with transaction.atomic():
            for student_id, name in records.items():
                user = User.objects.filter(username=student_id).first()
                if user is None:
                    created += 1
                    if not options["dry_run"]:
                        user = User(username=student_id, first_name=name); user.set_password(student_id); user.save()
                elif user.first_name != name:
                    updated += 1
                    if not options["dry_run"]:
                        user.first_name = name; user.save(update_fields=["first_name"])
                else:
                    unchanged += 1
        self.stdout.write(f"created={created} updated={updated} unchanged={unchanged}")

# Backend implementation report

## Scope delivered

- Django 5.2 application configuration, SQLite persistence with a 20-second lock timeout, WhiteNoise static storage, authentication routes, database-backed login throttling (including Django admin), and fail-closed production secret configuration.
- Posts, comments, unique likes, resources, announcements, reports, and login-attempt persistence with migrations and Chinese Django admin metadata.
- Login-required content, POST-only mutations, CSRF enforcement, owner/staff deletion permissions, private attachment responses, safe HTTP(S) links, server-side length and upload limits.
- JPEG/PNG/WebP verification and re-encoding. Re-encoding strips EXIF/text metadata, derives the extension from decoded content, and assigns a random UUID storage name.
- Current Asia/Shanghai calendar-week filtering, new/popular sorting, counts, and 20-item pagination.
- CSV/XLSX roster import with dry-run, header discovery in the first 30 rows, broken worksheet-dimension recovery, transaction-safe duplicate conflict rejection, and password-preserving idempotency. Student IDs preserve case and accept the characters present in the actual roster: ASCII letters, digits, `_`, and `-`.

## Test-first evidence

- Initial integration run failed because the backend models did not exist (`ImportError: cannot import name 'Comment'`).
- The broken XLSX-dimension regression failed before parser implementation and now passes after `reset_dimensions()`.
- The legitimate `D1234567` roster-ID regression failed with the earlier numeric-only validation and passed after validation was corrected.
- Static discovery, post-kind preselection, detail like counts, and metadata stripping were covered before their implementations were completed.

## Verification evidence

Run from `course-square` with the pinned virtual environment:

```text
.venv/bin/python manage.py test --verbosity 1
Ran 16 tests in 14.665s -- OK

.venv/bin/python manage.py check
System check identified no issues (0 silenced).

.venv/bin/python manage.py makemigrations --check --dry-run
No changes detected

.venv/bin/python manage.py collectstatic --noinput --clear --verbosity 0
exit 0

.venv/bin/python manage.py import_students '../人工智能导论_点名册.xlsx' --dry-run
created=0 updated=0 unchanged=80
```

Production-secret negative check:

```text
DJANGO_DEBUG=false (without DJANGO_SECRET_KEY) .venv/bin/python manage.py check
exit 1: RuntimeError: DJANGO_SECRET_KEY is required when DJANGO_DEBUG is false
```

## Final-review backend fixes

The five accepted findings in `docs/final-review.md` were addressed together:

- Django admin now uses the same Pillow re-encoding sanitizer as the student post form. The admin form still includes moderation fields such as author, status, and pinned. Actual admin add and replacement POSTs verify that synthetic PNG text metadata is removed and the moderation fields are retained.
- A response middleware adds `Cache-Control: private, no-store, max-age=0, must-revalidate`, `Pragma: no-cache`, and `Expires: 0` to dynamic application responses, including login pages and protected file responses. It runs behind WhiteNoise, so WhiteNoise-served `/static/` assets retain their own cache policy.
- Login throttling accepts a validated `X-Real-IP` only when the validated direct peer is a loopback proxy. Non-loopback peers cannot override their address, and malformed proxy values fall back to the direct loopback address. Usernames use Django's NFKC normalization before the throttle lookup. The supplied Nginx snippet already overwrites `X-Real-IP` from `$remote_addr` and proxies only to the application's loopback listener.
- Assigning a replacement resource upload now refreshes `original_filename` from the new upload, so download names track the current file.
- Authenticated users visiting the course login page redirect to a safe `next` destination or the board home. Authenticated staff visiting the admin login page follow the same safe destination behavior, while authenticated non-staff users still receive the admin reauthentication page instead of entering a redirect loop. Failed admin reauthentication by an already logged-in non-staff user is recorded and throttled rather than mistaken for a successful login.
- Student form labels no longer duplicate the template's “可选” badge.

Test-first evidence for this review: the six initial regressions failed before implementation (five assertion failures and one missing-header error), covering admin metadata, dynamic cache headers, trusted proxy IP separation, authenticated login redirects, and resource replacement names. The non-staff admin-login regression then reproduced the redirect-loop edge as a `302` before the role-aware admin behavior was added. A final authenticated non-staff regression observed zero stored failures before successful-response detection replaced the old pre-existing-session check.

Fresh verification after the fixes:

```text
.venv/bin/python manage.py test --verbosity 1
Ran 24 tests in 22.189s -- OK

.venv/bin/python manage.py check
System check identified no issues (0 silenced).

.venv/bin/python manage.py makemigrations --check --dry-run
No changes detected

git diff --check
exit 0
```

## Operational concerns

- SQLite and uploaded files live below configurable persistent paths and need deployment backups together.
- Login throttling is keyed by stripped username and source IP for a 15-minute window. Old records remain available to administrators and may be pruned operationally if the table grows over a long deployment.
- The roster dry-run read the real workbook but did not write accounts or expose identities; only aggregate counts were printed.

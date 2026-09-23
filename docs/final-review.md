# Final code review

Reviewed the supplied initial implementation diff through `87742ac`, the design/plan, backend report, and current application/deployment source. No application source changed by this reviewer. No private credential file, real roster, or application database was accessed.

## Critical

None found.

## Important

### P2 — Administrator image uploads bypass metadata removal

- Location: `board/admin.py:5-7`; sanitizer is only in `board/forms.py:20-37`.
- Trigger: An administrator adds or replaces an image on an anonymous post through Django admin. `PostAdmin` uses Django's generated ModelForm, whose image field validates the format but never executes the application's `PostForm.clean_image` sanitizer.
- Impact: Student image downloads can contain the original author/device/location metadata, violating the image privacy guarantee even when the visible post is anonymous.
- Evidence: A synthetic PNG with `Author=SYNTHETIC-STUDENT-IDENTITY` passed the actual registered admin form's image-field validation and retained that metadata. The ordinary student PostForm removed synthetic metadata. No database write was needed.
- Fix: Share an image-cleaning routine between the student and administrator forms, retaining the administrator's additional moderation fields. Add a regression using the actual admin upload path.

### P2 — Private dynamic responses do not prohibit browser caching

- Location: `config/settings.py:13` and authenticated handlers in `board/views.py`, especially `post_detail` and `resource_download`/`post_image` at lines 94-106.
- Trigger: A shared browser first displays an administrator's post detail, which contains anonymous real names, then logs out or switches to a student. Browser history/cache may reuse the old private representation without making an authenticated request.
- Impact: The fresh-request permission checks do not control previously cached administrator HTML or private attachment responses.
- Evidence: Source has no `never_cache` or equivalent middleware; synthetic file-response inspection returned Content-Type, Content-Length, Content-Disposition and nosniff only, without Cache-Control. Actual browser history reuse was not reproduced in this review and varies by browser.
- Fix: Apply `Cache-Control: private, no-store` to private dynamic responses and validate logout/account-switch behavior. Keep public static asset caching independent.

## Minor

1. **Proxy IP collapses login throttling across clients.** `board/auth_views.py:13-14` keys failures on `REMOTE_ADDR`, while `deploy/nginx.conf:7-12` connects via loopback and passes the real client address in `X-Real-IP`. In the supplied deployment, five wrong attempts against one username block that username for every client for 15 minutes. Use only the trusted proxy's overwritten real-IP header (with a direct-development fallback), or explicitly document and implement intentional account-wide throttling.
2. **Replacing a resource retains its old download name.** `board/models.py:95-98` only initializes `original_filename` if empty. Replacing `slides.pptx` with `notes.pdf` in admin leaves the attachment named `slides.pptx`, confusing file opening. Update the filename when a new upload is committed.
3. **An authenticated visit to `/login/` renders an empty content area.** `ThrottledLoginView` keeps `redirect_authenticated_user=False`, while the login template only implements `guest_content` and base.html selects `content` for authenticated users. Redirect authenticated visitors to the home page.

## Other conclusions and validation scope

- Fresh course-content and file requests require authentication. Student mutation forms exclude privileged fields and use CSRF protection; owner/staff deletion checks are present. Templates server-side omit anonymous author names for student viewers and escape user text.
- The roster importer preserves existing passwords and letter-containing IDs. The supplied default-password behavior is an explicit user requirement, not a review finding.
- Production secrets fail closed with DEBUG disabled; the systemd service binds to loopback and has persistent writable storage. Nginx does not publish media directly. Upgrade backups and release switching are present. Backup consistency limitations for live attachments are explicitly documented.
- Existing 16-test results, UI smoke checks, roster reimport and backup restoration were provided by the owner; the full suite was not redundantly rerun. This review executed only synthetic image/form and response-header checks.
- Alibaba deployment is still pending the user's intended server/access details. Local verification does not establish remote readiness or an externally reachable deployment.

Findings refer to the reviewed revision. Owner fixes and their subsequent verification should be recorded separately or appended here.

## Resolution and scoped signoff — `45e0b4d`

Re-reviewed `private/review-fixes.diff` (`87742ac..45e0b4d`) and the updated backend report. All five findings above are resolved in the reviewed code:

- **Admin image metadata:** `PostAdminForm` now shares `ImageSanitizingFormMixin` with the student form and retains all moderation fields. Regression coverage exercises actual administrator add and image-replacement POSTs, asserting metadata removal.
- **Dynamic caching:** `PrivateDynamicResponseMiddleware` installs private/no-store headers across application responses, including files and authentication pages. Its placement after WhiteNoise preserves static asset caching. Tests cover private pages/downloads, login, and static responses.
- **Proxy address:** validated `X-Real-IP` is accepted only from a loopback direct peer; external peers cannot spoof it, and malformed values fall back safely. Tests cover distinct proxied clients, untrusted peers, and malformed values. This matches the supplied loopback-only service and Nginx header-overwrite configuration.
- **Resource filenames:** assigning a fresh uncommitted upload updates the original filename. The replacement regression verifies persistence after reload.
- **Authenticated login:** regular login redirects authenticated users to validated destinations. Admin login keeps non-staff reauthentication available and redirects staff safely. Tests cover safe/external next destinations and the non-staff redirect-loop edge.

The additional normalized username throttle key follows Django's NFKC normalization. Failed admin reauthentication now depends on the login response being successful rather than merely finding a pre-existing authenticated student session; the added regression covers that bypass.

Verification evidence supplied by the fixer: **24 tests passed in 22.189 seconds**, system checks clean, no migration drift, and `git diff --check` clean. This reviewer inspected the fixes and regression assertions without redundantly rerunning the complete suite or accessing private course data.

**Scoped result: no remaining Critical or Important blockers found in these fixes.** The original findings are retained above as review history and are no longer open. This is local code-review signoff; production smoke checks remain the owner's responsibility, and remote Alibaba deployment remains pending actual server/access details.

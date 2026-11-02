"""Authenticated endpoints use this bounded, single-range file response."""
import re
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.utils.http import content_disposition_header

class BoundedFile:
    def __init__(self, file, start, length):
        self.file = file
        self.remaining = length
        file.seek(start)
    def __iter__(self):
        return self
    def __next__(self):
        if not self.remaining:
            self.close(); raise StopIteration
        chunk = self.file.read(min(64 * 1024, self.remaining))
        if not chunk:
            self.close(); raise StopIteration
        self.remaining -= len(chunk)
        return chunk
    def close(self):
        self.file.close()

def video_response(request, upload, filename):
    if not upload:
        raise Http404
    try:
        file = upload.open('rb')
        size = upload.size
    except (FileNotFoundError, OSError) as exc:
        raise Http404 from exc
    start, end, status = 0, size - 1, 200
    value = request.headers.get('Range', '')
    if value and ',' not in value:
        match = re.fullmatch(r'bytes=([0-9]{0,20})-([0-9]{0,20})', value)
        invalid = not match or not size
        if match and size:
            left, right = match.groups()
            if left:
                start = int(left); end = min(int(right), size - 1) if right else size - 1
                invalid = start >= size or end < start
            elif right and int(right) > 0:
                start = max(0, size - int(right))
            else:
                invalid = True
        if invalid:
            file.close()
            response = HttpResponse(status=416)
            response['Content-Range'] = f'bytes */{size}'
            return media_headers(response)
        status = 206
    length = max(0, end - start + 1)
    if request.method == 'HEAD':
        file.close(); response = HttpResponse(status=status, content_type='video/mp4')
    else:
        response = StreamingHttpResponse(BoundedFile(file, start, length), status=status, content_type='video/mp4')
    response['Content-Length'] = str(length)
    response['Content-Disposition'] = content_disposition_header(False, filename)
    if status == 206:
        response['Content-Range'] = f'bytes {start}-{end}/{size}'
    return media_headers(response)

def media_headers(response):
    response['Accept-Ranges'] = 'bytes'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, max-age=86400'
    response.private_media_cache = True
    return response

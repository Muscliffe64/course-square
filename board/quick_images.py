"""Compare attachments so the short retry window cannot silently discard new images."""
import hashlib


def _digest(stream):
    digest = hashlib.sha256()
    for chunk in stream.chunks():
        digest.update(chunk)
    return digest.digest()


def matching_gallery(post, uploads):
    gallery = list(post.gallery_images.all())
    if post.image or len(gallery) != len(uploads):
        return False
    for existing, upload in zip(gallery, uploads):
        if existing.original_filename != upload.name:
            return False
        try:
            with existing.image.open("rb") as stored:
                if stored.size != upload.size or _digest(stored) != _digest(upload):
                    return False
        except OSError:
            return False
        finally:
            upload.seek(0)
    return True

"""Display-size copies of uploaded images.

Originals stay byte-for-byte untouched (the course keeps upload metadata on
purpose). Thumbnails are re-encoded without EXIF/XMP, so GPS and camera data
never reach the pages that 80 people load at once.
"""
import io
import logging
import uuid
import warnings

from django.core.files.base import ContentFile
from PIL import Image, ImageOps, features

logger = logging.getLogger(__name__)

THUMB_MAX_EDGE = 1200


def thumbnail_upload(instance, filename):
    return f"post-thumbs/{uuid.uuid4().hex}{'.webp' if features.check('webp') else '.jpg'}"


def build_thumbnail(fileobj):
    """Return (ContentFile, suffix) for a display-size copy with metadata removed."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(fileobj) as source:
            icc_profile = source.info.get("icc_profile")
            source.draft("RGB", (THUMB_MAX_EDGE, THUMB_MAX_EDGE))
            image = ImageOps.exif_transpose(source)
            has_alpha = image.mode in {"RGBA", "LA", "PA"} or (image.mode == "P" and "transparency" in image.info)
            image = image.convert("RGBA" if has_alpha else "RGB")
            image.thumbnail((THUMB_MAX_EDGE, THUMB_MAX_EDGE), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    extra = {"icc_profile": icc_profile} if icc_profile else {}
    if features.check("webp"):
        image.save(output, "WEBP", quality=80, method=4, exif=b"", xmp=b"", **extra)
        suffix = ".webp"
    else:
        if image.mode == "RGBA":
            background = Image.new("RGB", image.size, "white")
            background.paste(image, mask=image.getchannel("A"))
            image = background
        image.save(output, "JPEG", quality=82, optimize=True, progressive=True, **extra)
        suffix = ".jpg"
    return ContentFile(output.getvalue()), suffix


def ensure_thumbnail(post_image):
    """Create the thumbnail if missing. Never raises: a failed thumbnail must not block a post."""
    if post_image.thumbnail or not post_image.image:
        return False
    try:
        with post_image.image.open("rb") as source:
            content, suffix = build_thumbnail(source)
        post_image.thumbnail.save(f"thumb{suffix}", content, save=False)
        type(post_image).objects.filter(pk=post_image.pk).update(thumbnail=post_image.thumbnail.name)
        return True
    except Exception:  # noqa: BLE001 - originals are still served if this fails
        logger.exception("Thumbnail generation failed for PostImage %s", post_image.pk)
        return False

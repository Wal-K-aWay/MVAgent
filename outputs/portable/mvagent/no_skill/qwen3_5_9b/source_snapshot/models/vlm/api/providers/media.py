from __future__ import annotations

import base64
import math
import mimetypes
from io import BytesIO
from pathlib import Path
from typing import Any, Tuple

from models.vlm.api.client import ApiVLMError
from models.utils import resolve_local_path


def image_output_format(path: str | Path) -> Tuple[str, str]:
    suffix = Path(path).suffix.lower().lstrip(".")
    if suffix in {"jpg", "jpeg"}:
        return "JPEG", "image/jpeg"
    if suffix == "png":
        return "PNG", "image/png"
    if suffix == "webp":
        return "WEBP", "image/webp"
    return "PNG", "image/png"


def bounded_image_size(
    width: int,
    height: int,
    *,
    min_pixels: int | None,
    max_pixels: int | None,
) -> Tuple[int, int]:
    width = max(1, int(width))
    height = max(1, int(height))
    pixels = width * height

    lower_bound = max(0, int(min_pixels or 0))
    upper_bound = max(0, int(max_pixels or 0))
    if lower_bound and upper_bound and lower_bound > upper_bound:
        lower_bound = upper_bound

    if upper_bound and pixels > upper_bound:
        scale = math.sqrt(float(upper_bound) / float(pixels))
        new_width = max(1, int(round(width * scale)))
        new_height = max(1, int(round(height * scale)))
        while new_width * new_height > upper_bound:
            if new_width >= new_height and new_width > 1:
                new_width -= 1
            elif new_height > 1:
                new_height -= 1
            else:
                break
        return new_width, new_height

    if lower_bound and pixels < lower_bound:
        scale = math.sqrt(float(lower_bound) / float(pixels))
        new_width = max(1, int(math.ceil(width * scale)))
        new_height = max(1, int(math.ceil(height * scale)))
        while new_width * new_height < lower_bound:
            if width >= height:
                new_width += 1
            else:
                new_height += 1
        if upper_bound:
            while new_width * new_height > upper_bound:
                if new_width >= new_height and new_width > 1:
                    new_width -= 1
                elif new_height > 1:
                    new_height -= 1
                else:
                    break
        return new_width, new_height

    return width, height


def image_to_data_url(
    path: str | Path,
    *,
    min_pixels: int | None,
    max_pixels: int | None,
    provider: str | None = None,
    model: str | None = None,
) -> str:
    resolved_path = Path(resolve_local_path(str(path)))
    context = ""
    if provider or model:
        context = f" for provider {provider or 'unknown'} model {model or 'unknown'}"
    try:
        from PIL import Image

        resample_lanczos = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        output_format, mime = image_output_format(resolved_path)
        with Image.open(resolved_path) as image:
            image.load()
            target_size = bounded_image_size(
                image.width,
                image.height,
                min_pixels=min_pixels,
                max_pixels=max_pixels,
            )
            if target_size != image.size:
                image = image.resize(target_size, resample_lanczos)
            if output_format == "JPEG" and image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")

            buffer = BytesIO()
            save_kwargs: dict[str, Any] = {}
            if output_format == "JPEG":
                save_kwargs["quality"] = 95
            image.save(buffer, format=output_format, **save_kwargs)
            image_bytes = buffer.getvalue()
    except (OSError, ValueError) as exc:
        detail = getattr(exc, "strerror", None) or str(exc)
        raise ApiVLMError(
            f"Failed to read or encode image '{resolved_path}'{context}: {detail}"
        ) from exc
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def local_media_to_data_url(path: str | Path, *, default_mime: str) -> str:
    resolved_path = Path(resolve_local_path(str(path)))
    mime_type = mimetypes.guess_type(str(resolved_path))[0] or default_mime
    encoded = base64.b64encode(resolved_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def parse_data_url(value: str) -> tuple[str, str] | None:
    prefix, separator, encoded = str(value or "").partition(",")
    if not separator or ";base64" not in prefix:
        return None
    mime = prefix.removeprefix("data:").split(";", 1)[0]
    if not mime or not encoded:
        return None
    return mime, encoded


__all__ = [
    "bounded_image_size",
    "image_output_format",
    "image_to_data_url",
    "local_media_to_data_url",
    "parse_data_url",
]

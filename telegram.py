from __future__ import annotations

import os
import tempfile
from pathlib import Path

import requests
from PIL import Image

API = "https://api.telegram.org"
MAX_PHOTO_DIMENSION_SUM = 10000
MAX_PHOTO_RATIO = 20


def _prepare_photo_parts(path: Path, temp_dir: Path) -> list[Path]:
    """Return Telegram-compatible photo parts without changing normal-sized images."""
    with Image.open(path) as image:
        width, height = image.size

        if (
            width + height <= MAX_PHOTO_DIMENSION_SUM
            and max(width / height, height / width) <= MAX_PHOTO_RATIO
        ):
            return [path]

        # Telegram limits the sum of width and height to 10000 and the
        # width/height ratio to 20 for photos. Split oversized posters along
        # their long axis so the original resolution and proportions are kept.
        long_is_height = height >= width
        short_side = width if long_is_height else height
        max_long_side = min(
            MAX_PHOTO_DIMENSION_SUM - short_side,
            int(short_side * MAX_PHOTO_RATIO),
        )
        if max_long_side <= 0:
            raise RuntimeError(f"Cannot prepare Telegram photo dimensions for {path}.")

        parts: list[Path] = []
        long_side = height if long_is_height else width
        start = 0
        part_index = 0

        while start < long_side:
            end = min(start + max_long_side, long_side)
            if long_is_height:
                box = (0, start, width, end)
            else:
                box = (start, 0, end, height)

            part = temp_dir / f"{path.stem}_part{part_index + 1}.png"
            image.crop(box).save(part, format="PNG")
            parts.append(part)

            start = end
            part_index += 1

        return parts


def _send_single_photo(path: Path, caption: str, token: str, chat_id: str) -> None:
    url = f"{API}/bot{token}/sendPhoto"
    with path.open("rb") as photo:
        response = requests.post(
            url,
            data={"chat_id": chat_id, "caption": caption},
            files={"photo": (path.name, photo, "image/png")},
            timeout=60,
        )

    if not response.ok:
        raise RuntimeError(
            f"Telegram send failed: HTTP {response.status_code}: {response.text[:500]}"
        )

    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API rejected the message: {payload}")


def send_photo(path: Path, caption: str = "") -> None:
    token = os.environ.get("TELEGRAMBOT")
    chat_id = os.environ.get("TELEGRAMCHANNEL")
    if not token or not chat_id:
        raise RuntimeError("Missing TELEGRAMBOT or TELEGRAMCHANNEL GitHub secret.")

    with tempfile.TemporaryDirectory(prefix="telegram-photo-") as temp:
        parts = _prepare_photo_parts(path, Path(temp))
        for index, part in enumerate(parts):
            _send_single_photo(
                part,
                caption if index == 0 else "",
                token,
                chat_id,
            )


def send_photos(paths: list[Path], caption: str = "") -> None:
    token = os.environ.get("TELEGRAMBOT")
    chat_id = os.environ.get("TELEGRAMCHANNEL")
    if not token or not chat_id:
        raise RuntimeError("Missing TELEGRAMBOT or TELEGRAMCHANNEL GitHub secret.")
    if not paths:
        raise ValueError("No photos to send.")

    # Keep the existing album API for callers that use it. Oversized images
    # are prepared first; each resulting part is then sent as an individual
    # photo because a single media group cannot safely represent an arbitrarily
    # long poster.
    with tempfile.TemporaryDirectory(prefix="telegram-photos-") as temp:
        prepared: list[Path] = []
        for path in paths:
            prepared.extend(_prepare_photo_parts(path, Path(temp)))

        url = f"{API}/bot{token}/sendMediaGroup"
        media = []
        files = {}
        handles = []

        try:
            for index, path in enumerate(prepared):
                handle = path.open("rb")
                handles.append(handle)
                attach_name = f"photo{index}"
                item = {
                    "type": "photo",
                    "media": f"attach://{attach_name}",
                }
                if index == 0 and caption:
                    item["caption"] = caption
                media.append(item)
                files[attach_name] = (path.name, handle, "image/png")

            response = requests.post(
                url,
                data={
                    "chat_id": chat_id,
                    "media": __import__("json").dumps(media),
                },
                files=files,
                timeout=120,
            )
        finally:
            for handle in handles:
                handle.close()

    if not response.ok:
        raise RuntimeError(
            f"Telegram media group send failed: HTTP {response.status_code}: {response.text[:500]}"
        )

    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API rejected the media group: {payload}")

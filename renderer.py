from __future__ import annotations

import datetime as dt
from collections import OrderedDict
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont, features

WIDTH = 1600
MAX_HEIGHT = 2200
MIN_HEIGHT = 760
MARGIN_X = 90
HEADER_H = 230
CARD_GAP = 24
COLUMN_GAP = 28
CARD_RADIUS = 26

BG = (247, 248, 250)
CARD = (255, 255, 255)
TEXT = (24, 27, 32)
MUTED = (105, 111, 122)
ACCENT = (30, 93, 170)
BORDER = (226, 229, 234)

LOGO_SIZE = 76
LOGO_TIMEOUT = 5
_logo_cache: dict[str, Image.Image | None] = {}


def _font(size: int, bold: bool = False):
    candidates = [
        Path("/usr/share/fonts/truetype/noto/" + ("NotoSansArabic-Bold.ttf" if bold else "NotoSansArabic-Regular.ttf")),
        Path("/usr/share/fonts/truetype/dejavu/" + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _team_name(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("longName") or value.get("shortName") or "—")
    return str(value or "—")


def _team_id(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("id") or value.get("teamId") or "")
    return ""


def _competition_name(match: dict) -> str:
    return str(match.get("competition") or match.get("competitionName") or match.get("league") or "نامشخص")


def _kickoff(match: dict) -> str:
    start = match.get("startIran")
    if not start:
        return "—"
    try:
        return dt.datetime.fromisoformat(start).strftime("%H:%M")
    except ValueError:
        return "—"


def _text_width(draw, text: str, font, direction: str = "rtl") -> float:
    return draw.textlength(text, font=font, direction=direction, language="fa" if direction == "rtl" else None)


def _fit_font(draw, text: str, max_width: int, sizes: list[int], bold: bool):
    for size in sizes:
        font = _font(size, bold)
        if _text_width(draw, text, font) <= max_width:
            return font
    return _font(sizes[-1], bold)


def _center_text(draw, x: int, y: int, text: str, font, fill, direction: str = "rtl"):
    draw.text(
        (x, y), text, font=font, fill=fill, anchor="ma",
        direction=direction, language="fa" if direction == "rtl" else None,
    )


def _load_logo(team_id: str) -> Image.Image | None:
    if not team_id:
        return None
    if team_id in _logo_cache:
        return _logo_cache[team_id]
    url = f"https://images.fotmob.com/image_resources/logo/teamlogo/{team_id}.png"
    try:
        response = requests.get(url, timeout=LOGO_TIMEOUT)
        response.raise_for_status()
        from io import BytesIO
        logo = Image.open(BytesIO(response.content)).convert("RGBA")
        logo.thumbnail((LOGO_SIZE, LOGO_SIZE), Image.Resampling.LANCZOS)
        _logo_cache[team_id] = logo
    except (requests.RequestException, OSError):
        logo = None
        _logo_cache[team_id] = None
    return logo


def _paste_logo(image, logo, center):
    if logo is None:
        return
    image.paste(logo, (center[0] - logo.width // 2, center[1] - logo.height // 2), logo)


def _draw_team(image, draw, center_x, logo_y, name_y, name, team_id, max_width):
    logo = _load_logo(team_id)
    if logo is not None:
        _paste_logo(image, logo, (center_x, logo_y))
    else:
        r = 28
        draw.ellipse((center_x - r, logo_y - r, center_x + r, logo_y + r), fill=(236, 239, 244))
    font = _fit_font(draw, name, max_width, [30, 28, 26, 24], True)
    _center_text(draw, center_x, name_y, name, font, TEXT)


def _draw_card(image, draw, box, match, compact):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=CARD_RADIUS, fill=CARD, outline=BORDER, width=2)

    competition = _competition_name(match)
    kickoff = _kickoff(match)
    home = _team_name(match.get("home"))
    away = _team_name(match.get("away"))
    home_id = _team_id(match.get("home"))
    away_id = _team_id(match.get("away"))

    center_x = (x1 + x2) // 2
    inner_w = x2 - x1 - 44
    comp_font = _fit_font(draw, competition, inner_w, [23, 21, 19], True)
    draw.text((x2 - 22, y1 + 22), competition, font=comp_font, fill=MUTED,
              anchor="ra", direction="rtl", language="fa")

    if compact:
        logo_y, name_y, time_y = y1 + 82, y1 + 132, y2 - 27
        name_max = (inner_w - 130) // 2
        _draw_team(image, draw, x1 + (x2 - x1) // 4, logo_y, name_y, home, home_id, name_max)
        _draw_team(image, draw, x1 + 3 * (x2 - x1) // 4, logo_y, name_y, away, away_id, name_max)
    else:
        logo_y, name_y, time_y = y1 + 96, y1 + 154, y2 - 35
        name_max = (inner_w - 180) // 2
        _draw_team(image, draw, center_x - 180, logo_y, name_y, home, home_id, name_max)
        _draw_team(image, draw, center_x + 180, logo_y, name_y, away, away_id, name_max)

    time_font = _font(42 if not compact else 36, True)
    draw.ellipse((center_x - 48, time_y - 48, center_x + 48, time_y + 48), fill=ACCENT)
    _center_text(draw, center_x, time_y + 1, kickoff, time_font, (255, 255, 255), "ltr")


def _group_matches(matches):
    groups = OrderedDict()
    for match in matches:
        groups.setdefault(_competition_name(match), []).append(match)
    return list(groups.items())


def _split_groups(groups, max_items):
    pages = []
    current = []
    count = 0
    for competition, items in groups:
        start = 0
        while start < len(items):
            remaining = max_items - count
            if remaining <= 0:
                pages.append(current)
                current, count = [], 0
                remaining = max_items
            take = min(remaining, len(items) - start)
            current.append((competition, items[start:start + take]))
            count += take
            start += take
            if count >= max_items:
                pages.append(current)
                current, count = [], 0
    if current:
        pages.append(current)
    return pages


def _render_page(groups, day, page_no, page_total, output, cards_per_row):
    compact = cards_per_row == 2
    card_h = 245 if not compact else 230
    section_h = 66
    content_w = WIDTH - 2 * MARGIN_X
    card_w = (content_w - COLUMN_GAP) // cards_per_row
    rows = sum((len(items) + cards_per_row - 1) // cards_per_row for _, items in groups)
    height = min(MAX_HEIGHT, max(MIN_HEIGHT, HEADER_H + 26 + len(groups) * section_h + rows * (card_h + CARD_GAP) + 70))

    image = Image.new("RGB", (WIDTH, height), BG)
    draw = ImageDraw.Draw(image)

    draw.text((WIDTH - MARGIN_X, 68), "مسابقات امروز", font=_font(56, True), fill=TEXT,
              anchor="ra", direction="rtl", language="fa")
    draw.text((WIDTH - MARGIN_X, 145), day.strftime("%Y/%m/%d"), font=_font(25), fill=MUTED,
              anchor="ra", direction="ltr")
    if page_total > 1:
        draw.text((MARGIN_X, 145), f"{page_no} / {page_total}", font=_font(22, True), fill=MUTED,
                  anchor="la", direction="ltr")

    y = HEADER_H
    for competition, items in groups:
        draw.text((WIDTH - MARGIN_X, y), competition,
                  font=_fit_font(draw, competition, content_w, [30, 28, 26], True),
                  fill=ACCENT, anchor="ra", direction="rtl", language="fa")
        y += section_h
        for index, match in enumerate(items):
            row = index // cards_per_row
            col = index % cards_per_row
            x1 = MARGIN_X + col * (card_w + COLUMN_GAP)
            y1 = y + row * (card_h + CARD_GAP)
            _draw_card(image, draw, (x1, y1, x1 + card_w, y1 + card_h), match, compact)
        y += ((len(items) + cards_per_row - 1) // cards_per_row) * (card_h + CARD_GAP) + 12

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "PNG", optimize=True)


def render_fixtures(matches: list[dict], day: dt.date, output: Path) -> None:
    if not matches:
        raise ValueError("Cannot render a fixture report with zero matches.")
    if not features.check("raqm"):
        raise RuntimeError("Pillow was built without libraqm; Persian RTL rendering cannot be trusted.")

    groups = _group_matches(matches)
    total_matches = len(matches)
    cards_per_row = 1 if total_matches <= 10 else 2
    compact = cards_per_row == 2
    card_h = 245 if not compact else 230
    rows_capacity = max(1, (MAX_HEIGHT - HEADER_H - 100) // (card_h + CARD_GAP))
    max_items_per_page = rows_capacity * cards_per_row
    pages = _split_groups(groups, max_items_per_page)
    page_total = len(pages)

    if page_total == 1:
        _render_page(pages[0], day, 1, 1, output, cards_per_row)
        return

    stem, suffix = output.stem, output.suffix or ".png"
    for index, page_groups in enumerate(pages, start=1):
        _render_page(page_groups, day, index, page_total, output.with_name(f"{stem}-{index}{suffix}"), cards_per_row)

    first_page = output.with_name(f"{stem}-1{suffix}")
    first_page.replace(output)
    for old_index in range(page_total + 1, page_total + 6):
        stale = output.with_name(f"{stem}-{old_index}{suffix}")
        if stale.exists():
            stale.unlink()

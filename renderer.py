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
_team_fa_cache: dict[str, str] | None = None
TEAMS_FA_URL = "https://raw.githubusercontent.com/eoghanlochlyneoghanlochlyn/Ftbllrslts/main/teams.json"

COMPETITION_FA = {
    "Premier League": "لیگ برتر انگلیس", "LaLiga": "لالیگا", "La Liga": "لالیگا",
    "Bundesliga": "بوندس‌لیگا", "Serie A": "سری آ", "Ligue 1": "لیگ ۱ فرانسه",
    "Champions League": "لیگ قهرمانان اروپا", "UEFA Champions League": "لیگ قهرمانان اروپا",
    "Europa League": "لیگ اروپا", "UEFA Europa League": "لیگ اروپا",
    "Conference League": "لیگ کنفرانس اروپا", "UEFA Conference League": "لیگ کنفرانس اروپا",
    "FA Cup": "جام حذفی انگلیس", "EFL Cup": "جام اتحادیه انگلیس", "Carabao Cup": "جام اتحادیه انگلیس",
    "Copa del Rey": "جام حذفی اسپانیا", "Coppa Italia": "جام حذفی ایتالیا",
    "DFB Pokal": "جام حذفی آلمان", "DFB-Pokal": "جام حذفی آلمان", "Coupe de France": "جام حذفی فرانسه",
    "Community Shield": "جام خیریه انگلیس", "UEFA Super Cup": "سوپرجام اروپا",
    "European Championship": "جام ملت‌های اروپا", "World Cup": "جام جهانی",
    "World Cup Qualifiers": "انتخابی جام جهانی", "Nations League": "لیگ ملت‌های اروپا",
    "Copa America": "کوپا آمریکا", "Copa Libertadores": "کوپا لیبرتادورس",
    "AFC Champions League Elite": "لیگ نخبگان آسیا", "AFC Champions League Two": "لیگ قهرمانان آسیا ۲",
}

FALLBACK_TEAM_FA = {
    "Liverpool": "لیورپول", "Arsenal": "آرسنال", "Manchester City": "منچسترسیتی",
    "Manchester United": "منچستریونایتد", "Chelsea": "چلسی", "Tottenham Hotspur": "تاتنهام",
    "Juventus": "یوونتوس", "Milan": "میلان", "Inter": "اینتر", "Bayern Munich": "بایرن مونیخ",
    "Borussia Dortmund": "بوروسیا دورتموند", "Paris Saint-Germain": "پاری سن ژرمن",
    "Real Madrid": "رئال مادرید", "Barcelona": "بارسلونا", "Atletico Madrid": "اتلتیکو مادرید",
    "Atlético Madrid": "اتلتیکو مادرید", "Bournemouth": "بورنموث",
}


def _font(size: int, bold: bool = False):
    candidates = [
        Path("/usr/share/fonts/truetype/noto/" + ("NotoSansArabic-Bold.ttf" if bold else "NotoSansArabic-Regular.ttf")),
        Path("/usr/share/fonts/truetype/dejavu/" + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _load_team_fa() -> dict[str, str]:
    global _team_fa_cache
    if _team_fa_cache is not None:
        return _team_fa_cache
    mapping: dict[str, str] = {}
    try:
        response = requests.get(TEAMS_FA_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    team_id = str(item.get("id") or "")
                    persian = str(item.get("persian") or "").strip()
                    if team_id and persian:
                        mapping[team_id] = persian
    except (requests.RequestException, ValueError):
        pass
    _team_fa_cache = mapping
    return mapping


def _team_name(value: object) -> str:
    if isinstance(value, dict):
        team_id = str(value.get("id") or value.get("teamId") or "")
        english = str(value.get("name") or value.get("longName") or value.get("shortName") or "—").strip()
        return _load_team_fa().get(team_id) or FALLBACK_TEAM_FA.get(english, english)
    return str(value or "—")


def _team_id(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("id") or value.get("teamId") or "")
    return ""


def _competition_name(match: dict) -> str:
    english = str(match.get("competition") or match.get("competitionName") or match.get("league") or "نامشخص").strip()
    if english in COMPETITION_FA:
        return COMPETITION_FA[english]
    for key, value in COMPETITION_FA.items():
        if key.casefold() in english.casefold():
            return value
    return english


def _to_persian_digits(value: str) -> str:
    return str(value).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _kickoff(match: dict) -> str:
    start = match.get("startIran")
    if not start:
        return "—"
    try:
        parsed = dt.datetime.fromisoformat(str(start))
        return _to_persian_digits(parsed.strftime("%H:%M"))
    except (TypeError, ValueError):
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

    # Keep competition inside each match card; no separate competition banner.
    if compact:
        logo_y, name_y = y1 + 86, y1 + 145
        name_max = (inner_w - 190) // 2
        _draw_team(image, draw, center_x - 205, logo_y, name_y, home, home_id, name_max)
        _draw_team(image, draw, center_x + 205, logo_y, name_y, away, away_id, name_max)
    else:
        logo_y, name_y = y1 + 94, y1 + 156
        name_max = (inner_w - 220) // 2
        _draw_team(image, draw, center_x - 220, logo_y, name_y, home, home_id, name_max)
        _draw_team(image, draw, center_x + 220, logo_y, name_y, away, away_id, name_max)

    # Small centered time pill, positioned in the gap between the teams.
    time_font = _font(30 if not compact else 27, True)
    time_w = 66 if not compact else 58
    time_h = 46 if not compact else 42
    time_y = y1 + (y2 - y1) // 2 + 8
    draw.rounded_rectangle(
        (center_x - time_w, time_y - time_h // 2, center_x + time_w, time_y + time_h // 2),
        radius=16,
        fill=ACCENT,
    )
    _center_text(draw, center_x, time_y, kickoff, time_font, (255, 255, 255), "rtl")


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
    content_w = WIDTH - 2 * MARGIN_X
    card_w = (content_w - COLUMN_GAP) // cards_per_row
    rows = sum((len(items) + cards_per_row - 1) // cards_per_row for _, items in groups)
    height = min(MAX_HEIGHT, max(MIN_HEIGHT, HEADER_H + 26 + rows * (card_h + CARD_GAP) + len(groups) * 12 + 70))

    image = Image.new("RGB", (WIDTH, height), BG)
    draw = ImageDraw.Draw(image)

    draw.text((WIDTH - MARGIN_X, 68), "مسابقات امروز", font=_font(56, True), fill=TEXT,
              anchor="ra", direction="rtl", language="fa")
    draw.text((WIDTH - MARGIN_X, 145), _to_persian_digits(day.strftime("%Y/%m/%d")), font=_font(25), fill=MUTED,
              anchor="ra", direction="ltr")
    if page_total > 1:
        draw.text((MARGIN_X, 145), f"{page_no} / {page_total}", font=_font(22, True), fill=MUTED,
                  anchor="la", direction="ltr")

    y = HEADER_H
    for competition, items in groups:
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

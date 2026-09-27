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
CARD_GAP = 18
COLUMN_GAP = 28
CARD_RADIUS = 26
COMPETITION_GAP = 28
MATCH_ROW_H = 152

BG = (9, 17, 33)
CARD = (20, 32, 52)
TEXT = (244, 248, 255)
MUTED = (166, 184, 207)
ACCENT = (42, 112, 193)
BORDER = (48, 67, 92)

# Restrained broadcast-style accents; all unknown competitions use blue.
COMPETITION_ACCENTS = {
    "لیگ برتر انگلیس": (167, 94, 232),
    "لالیگا": (232, 91, 103),
    "سری آ": (77, 155, 239),
    "بوندس‌لیگا": (230, 79, 79),
    "لیگ ۱ فرانسه": (218, 182, 76),
    "لیگ قهرمانان اروپا": (98, 135, 242),
    "لیگ اروپا": (237, 151, 70),
    "لیگ کنفرانس اروپا": (94, 192, 145),
}


LOGO_SIZE = 76
LOGO_TIMEOUT = 5
_logo_cache: dict[str, Image.Image | None] = {}
_team_fa_cache: dict[str, str] | None = None
TEAMS_FA_URL = "https://raw.githubusercontent.com/eoghanlochlyneoghanlochlyn/Ftbllrslts/main/teams.json"

NATIONS_LEAGUE_LEVELS = {
    "9806": "لیگ ملت‌های اروپا A",
    "9807": "لیگ ملت‌های اروپا B",
    "9808": "لیگ ملت‌های اروپا C",
    "9809": "لیگ ملت‌های اروپا D",
}

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
    # Keep Nations League A/B/C/D separate by numeric FotMob league ID.
    # Some FotMob responses use the same generic competition name for all levels.
    competition_id = str(
        match.get("leagueId")
        or match.get("competitionId")
        or match.get("tournamentId")
        or ""
    )
    if competition_id in NATIONS_LEAGUE_LEVELS:
        return NATIONS_LEAGUE_LEVELS[competition_id]

    english = str(
        match.get("competition")
        or match.get("competitionName")
        or match.get("league")
        or "نامشخص"
    ).strip()
    if english in COMPETITION_FA:
        return COMPETITION_FA[english]
    for key, value in COMPETITION_FA.items():
        if key.casefold() in english.casefold():
            return value
    return english


def _to_persian_digits(value: str) -> str:
    return str(value).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _jalali_date(day: dt.date) -> str:
    """Convert Gregorian date to Solar Hijri without runtime dependencies."""
    gy, gm, gd = day.year, day.month, day.day
    g_days = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100
    days += (gy2 + 399) // 400 + gd + g_days[gm - 1]
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return _to_persian_digits(f"{jy:04d}/{jm:02d}/{jd:02d}")


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
        draw.ellipse((center_x - r, logo_y - r, center_x + r, logo_y + r), fill=(45, 63, 86))
    font = _fit_font(draw, name, max_width, [30, 28, 26, 24], True)
    _center_text(draw, center_x, name_y, name, font, TEXT)


def _match_stage(match: dict) -> str:
    value = match.get("stage") or match.get("round") or match.get("matchweek") or match.get("week") or match.get("group")
    if isinstance(value, dict):
        value = value.get("name") or value.get("displayName") or value.get("round") or value.get("week")
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    low = text.casefold()
    if low.startswith("matchday") or low.startswith("match week") or low.startswith("week"):
        digits = "".join(ch for ch in text if ch.isdigit())
        return f"هفته {_to_persian_digits(digits)}" if digits else text
    if low.startswith("group"):
        return f"گروه {text.split()[-1]}"
    return text


def _draw_match_row(image, draw, box, match, accent=ACCENT):
    x1, y1, x2, y2 = box
    home = _team_name(match.get("home"))
    away = _team_name(match.get("away"))
    kickoff = _kickoff(match)
    stage = _match_stage(match)
    mid_y = (y1 + y2) // 2

    # RTL visual order: home logo | home name | time | away name |
    # away logo | stage. Every item has a reserved non-overlapping region.
    stage_width = 180
    logo_size = 66
    clock_width = 154
    content_left = x1 + 25
    content_right = x2 - stage_width - 20
    mid_x = (content_left + content_right) // 2
    left_logo_x = content_left + 45
    right_logo_x = content_right - 45
    name_gap = 16
    clock_gap = 18
    home_name_left = left_logo_x + logo_size//2 + name_gap
    home_name_right = mid_x - clock_width//2 - clock_gap
    away_name_left = mid_x + clock_width//2 + clock_gap
    away_name_right = right_logo_x - logo_size//2 - name_gap

    for team_id, logo_x in ((_team_id(match.get("home")), left_logo_x),
                            (_team_id(match.get("away")), right_logo_x)):
        logo = _load_logo(team_id)
        if logo is not None:
            logo.thumbnail((logo_size, logo_size), Image.Resampling.LANCZOS)
            _paste_logo(image, logo, (logo_x, mid_y))
        else:
            draw.ellipse((logo_x-27,mid_y-27,logo_x+27,mid_y+27),
                         fill=(45,63,86))

    def draw_name(name, left, right):
        max_w = max(60, right-left)
        font = _fit_font(draw, name, max_w, [30,28,26,24,22,20,18], True)
        while _text_width(draw, name, font) > max_w and len(name)>2:
            name = name[:-2].rstrip() + "…"
        bbox = draw.textbbox((0,0),name,font=font,direction="rtl",language="fa")
        tw,th = bbox[2]-bbox[0],bbox[3]-bbox[1]
        draw.text(((left+right-tw)/2-bbox[0],mid_y-th/2-bbox[1]),
                  name,font=font,fill=TEXT,direction="rtl",language="fa")

    draw_name(home,home_name_left,home_name_right)
    draw_name(away,away_name_left,away_name_right)

    time_font = _font(29, True)
    draw.rounded_rectangle((mid_x-clock_width//2,mid_y-24,
                            mid_x+clock_width//2,mid_y+24),
                           radius=14,fill=accent)
    bbox = draw.textbbox((0,0),kickoff,font=time_font,
                         direction="rtl",language="fa")
    tw,th = bbox[2]-bbox[0],bbox[3]-bbox[1]
    draw.text((mid_x-tw/2-bbox[0],mid_y-th/2-bbox[1]),
              kickoff,font=time_font,fill=(255,255,255),
              direction="rtl",language="fa")

    if stage:
        stage_font = _fit_font(draw,stage,stage_width-20,[22,20,18,16,14],True)
        bbox = draw.textbbox((0,0),stage,font=stage_font,
                             direction="rtl",language="fa")
        tw,th=bbox[2]-bbox[0],bbox[3]-bbox[1]
        stage_x=x2-stage_width//2
        draw.text((stage_x-tw/2-bbox[0],mid_y-th/2-bbox[1]),
                  stage,font=stage_font,fill=MUTED,
                  direction="rtl",language="fa")


def _draw_competition_box(image, draw, x1, y1, x2, matches, competition):
    header_h = 64
    box_h = header_h + len(matches) * MATCH_ROW_H + max(0, len(matches)-1)
    y2 = y1 + box_h
    accent = COMPETITION_ACCENTS.get(competition, ACCENT)
    draw.rounded_rectangle((x1,y1,x2,y2), radius=CARD_RADIUS, fill=CARD, outline=BORDER, width=2)
    # Competition accent rail and a subtle, inset header panel.
    draw.rounded_rectangle((x1+12,y1+13,x1+19,y1+header_h-12), radius=3, fill=accent)
    draw.rounded_rectangle((x1+29,y1+9,x2-12,y1+header_h-7), radius=12, fill=(26, 42, 65))
    font = _fit_font(draw, competition, x2-x1-40, [30,28,26,24], True)
    draw.text((x2-22,y1+30), competition, font=font, fill=TEXT, anchor="rm", direction="rtl", language="fa")
    draw.line((x1+18,y1+header_h,x2-18,y1+header_h), fill=BORDER, width=2)
    for i, match in enumerate(matches):
        ry1 = y1 + header_h + i*(MATCH_ROW_H+1)
        ry2 = ry1 + MATCH_ROW_H
        if i:
            draw.line((x1+35,ry1,x2-35,ry1), fill=BORDER, width=1)
        _draw_match_row(image, draw, (x1+18,ry1,x2-18,ry2), match, accent)
    return y2


def _draw_card(image, draw, box, match, compact):
    _draw_competition_box(image, draw, box[0], box[1], box[2], [match], _competition_name(match))

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
    content_w = WIDTH - 2 * MARGIN_X
    comp_heights = [64 + len(items) * MATCH_ROW_H + max(0, len(items)-1) for _, items in groups]
    height = min(MAX_HEIGHT, max(MIN_HEIGHT, HEADER_H + 26 + sum(comp_heights) + max(0, len(groups)-1)*COMPETITION_GAP + 70))
    image = Image.new("RGB", (WIDTH, height), BG)
    draw = ImageDraw.Draw(image)
    # Thin broadcast header rule and quiet corner details, drawn in Pillow.
    draw.rounded_rectangle((MARGIN_X, 36, WIDTH-MARGIN_X, 43), radius=3, fill=(42, 112, 193))
    draw.line((MARGIN_X, HEADER_H-22, WIDTH-MARGIN_X, HEADER_H-22), fill=BORDER, width=2)
    draw.text((WIDTH - MARGIN_X, 68), "مسابقات امروز", font=_font(56, True), fill=TEXT,
              anchor="ra", direction="rtl", language="fa")
    # Draw date separators as vector strokes: some Arabic font builds show
    # ASCII slash as a missing-glyph square when mixed with Persian digits.
    date_font = _font(25)
    date_parts = _jalali_date(day).split("/")
    date_x = WIDTH - MARGIN_X
    date_anchor_y = 145
    # Use the actual digit ink bounds rather than an assumed baseline.
    # This keeps the hand-drawn slash centered on the visible numerals.
    sample_box = draw.textbbox((0, date_anchor_y), "۱۴۰۵", font=date_font,
                               anchor="ra", direction="ltr")
    digit_top, digit_bottom = sample_box[1], sample_box[3]
    slash_top = digit_top + 2
    slash_bottom = digit_bottom - 2
    for index, part in enumerate(reversed(date_parts)):
        draw.text((date_x, date_anchor_y), part, font=date_font, fill=MUTED,
                  anchor="ra", direction="ltr")
        date_x -= draw.textlength(part, font=date_font, direction="ltr")
        if index < len(date_parts) - 1:
            date_x -= 9
            draw.line((date_x - 13, slash_bottom, date_x - 2, slash_top),
                      fill=MUTED, width=3)
            date_x -= 22
    if page_total > 1:
        draw.text((MARGIN_X, 145), f"{_to_persian_digits(str(page_no))} / {_to_persian_digits(str(page_total))}",
                  font=_font(22, True), fill=MUTED, anchor="la", direction="ltr")
    y = HEADER_H
    for competition, items in groups:
        box_h = 64 + len(items) * MATCH_ROW_H + max(0, len(items)-1)
        _draw_competition_box(image, draw, MARGIN_X, y, WIDTH-MARGIN_X, items, competition)
        y += box_h + COMPETITION_GAP
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "PNG", optimize=True)

def render_fixtures(matches: list[dict], day: dt.date, output: Path) -> None:
    if not matches:
        raise ValueError("Cannot render a fixture report with zero matches.")
    if not features.check("raqm"):
        raise RuntimeError("Pillow was built without libraqm; Persian RTL rendering cannot be trusted.")
    groups = _group_matches(matches)
    usable_h = MAX_HEIGHT - HEADER_H - 70
    pages = []
    current = []
    used = 0
    for competition, items in groups:
        comp_h = 64 + len(items) * MATCH_ROW_H + max(0, len(items)-1)
        needed = comp_h + (COMPETITION_GAP if current else 0)
        if current and used + needed > usable_h:
            pages.append(current)
            current = []
            used = 0
        current.append((competition, items))
        used += needed
    if current:
        pages.append(current)
    page_total = len(pages)
    if page_total == 1:
        _render_page(pages[0], day, 1, 1, output, 1)
        return
    stem, suffix = output.stem, output.suffix or ".png"
    generated = []
    for index, page_groups in enumerate(pages, start=1):
        path = output.with_name(f"{stem}-{index}{suffix}")
        _render_page(page_groups, day, index, page_total, path, 1)
        generated.append(path)
    generated[0].replace(output)

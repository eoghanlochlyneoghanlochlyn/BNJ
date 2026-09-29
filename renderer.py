from __future__ import annotations

import datetime as dt
import hashlib
import colorsys
import re
from collections import OrderedDict
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont, features

WIDTH = 1600
MAX_HEIGHT = 2600
MIN_HEIGHT = 760
MARGIN_X = 90
HEADER_H = 230
CARD_GAP = 18
COLUMN_GAP = 28
CARD_RADIUS = 26
COMPETITION_GAP = 28
MATCH_ROW_H = 142
COMPACT_MATCH_ROW_H = 126
TWO_COLUMN_THRESHOLD = 11
MAX_MATCHES_PER_COLUMN = 10  # Hard cap; page height below is sized to fit 10 compact cards.

KNOCKOUT_COMPETITION_IDS = {
    "132", "133", "138", "139", "141", "207", "247", "8924", "11015", "222", "134", "209",
}

BG = (9, 17, 33)
CARD = (20, 32, 52)
TEXT = (244, 248, 255)
MUTED = (166, 184, 207)
ACCENT = (42, 112, 193)
BORDER = (48, 67, 92)

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
_competition_fa_cache: dict[str, str] | None = None
TEAMS_FA_URL = "https://raw.githubusercontent.com/eoghanlochlyneoghanlochlyn/Ftbllrslts/main/teams.json"

WORLD_COMPETITION_IDS = {"77": "جام جهانی", "78": "جام جهانی باشگاه‌ها"}

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
    "Friendlies": "بازی دوستانه", "Friendly": "بازی دوستانه",
    "Italian Super Cup": "سوپرکاپ ایتالیا", "Supercoppa Italiana": "سوپرکاپ ایتالیا", "Super Cup Italy": "سوپرکاپ ایتالیا",
    "Trophée des Champions": "سوپرجام فرانسه", "Trophée des champions": "سوپرجام فرانسه",
    "Trophee des Champions": "سوپرجام فرانسه", "Trophee des champions": "سوپرجام فرانسه",
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


def _latin_font(size: int, bold: bool = False):
    candidates = [
        Path("/usr/share/fonts/truetype/dejavu/" + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")),
        Path("/usr/share/fonts/truetype/noto/" + ("NotoSans-Regular.ttf" if not bold else "NotoSans-Bold.ttf")),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(path, size)
    return _font(size, bold)


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


def _load_competition_fa() -> dict[str, str]:
    global _competition_fa_cache
    if _competition_fa_cache is not None:
        return _competition_fa_cache

    mapping: dict[str, str] = {}
    path = Path(__file__).with_name("competitions.json")
    try:
        import json
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    competition_id = str(item.get("id") or "")
                    persian = str(item.get("persian") or "").strip()
                    if competition_id and persian:
                        mapping[competition_id] = persian
    except (OSError, ValueError):
        pass

    # Project-specific display names.
    mapping["11015"] = "سوپرکاپ ایتالیا"
    mapping["222"] = "سوپرکاپ ایتالیا"
    mapping["9806"] = "لیگ ملت‌های اروپا A"
    mapping["9807"] = "لیگ ملت‌های اروپا B"
    mapping["9808"] = "لیگ ملت‌های اروپا C"
    mapping["9809"] = "لیگ ملت‌های اروپا D"
    mapping["207"] = "سوپرکاپ فرانسه"

    _competition_fa_cache = mapping
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
    competition_id = str(
        match.get("leagueId")
        or match.get("competitionId")
        or match.get("tournamentId")
        or ""
    )

    by_id = _load_competition_fa()
    if competition_id in by_id:
        return by_id[competition_id]

    # FotMob has historically exposed the Italian Super Cup under both
    # competition IDs 11015 and 222. Treat both as the same competition.
    if competition_id in {"11015", "222"}:
        return "سوپرکاپ ایتالیا"

    english = str(
        match.get("competitionName")
        or match.get("competition")
        or match.get("league")
        or "نامشخص"
    ).strip()

    if english in COMPETITION_FA:
        return COMPETITION_FA[english]

    if english.casefold() in {"trophée des champions", "trophee des champions"}:
        return "سوپرجام فرانسه"

    normalized = " ".join(english.casefold().replace("-", " ").split())
    for key, value in COMPETITION_FA.items():
        key_normalized = " ".join(key.casefold().replace("-", " ").split())
        if normalized == key_normalized or key_normalized in normalized:
            return value

    return english

def _to_persian_digits(value: str) -> str:
    return str(value).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _jalali_date(day: dt.date) -> str:
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


def _result_label_for_rtl(match: dict) -> str:
    """
    Convert FotMob's logical HOME-AWAY score into the poster's visual
    left-to-right order.

    The poster intentionally places AWAY on the left and HOME on the right.
    score_for() stores resultLabel as:
        HOME - AWAY
        HOME (PEN_HOME-PEN_AWAY) AWAY

    Therefore the rendered token must be:
        AWAY - HOME
        AWAY (PEN_AWAY-PEN_HOME) HOME

    resultLabel is generated by our own results.py, so parsing its numeric
    tokens is safer than trying to reconstruct RTL ordering with a fragile
    regular expression.
    """
    raw = str(match.get("resultLabel") or "").strip()
    if not raw:
        return _kickoff(match)

    # Accept both Western and Persian digits.
    number_re = r"[0-9۰-۹]+"
    values = re.findall(number_re, raw)

    if len(values) == 4:
        # HOME, PEN_HOME, PEN_AWAY, AWAY
        home, home_pen, away_pen, away = values
        return f"{away} ({away_pen}-{home_pen}) {home}"

    if len(values) == 2:
        # HOME, AWAY
        home, away = values
        return f"{away} - {home}"

    # If the source format ever changes, keep the original value instead
    # of inventing a score.
    return raw

def _text_width(draw, text: str, font, direction: str = "rtl") -> float:
    return draw.textlength(text, font=font, direction=direction, language="fa" if direction == "rtl" else None)


def _contains_persian(text: str) -> bool:
    return any(
        "\u0600" <= ch <= "\u06ff"
        or "\u0750" <= ch <= "\u077f"
        or "\u08a0" <= ch <= "\u08ff"
        for ch in str(text)
    )


def _text_font(size: int, text: str, bold: bool = False):
    return _font(size, bold) if _contains_persian(text) else _latin_font(size, bold)


def _fit_font(draw, text: str, max_width: int, sizes: list[int], bold: bool):
    for size in sizes:
        font = _text_font(size, text, bold)
        if _text_width(draw, text, font) <= max_width:
            return font
    return _font(sizes[-1], bold)


def _center_text(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, font, fill, direction: str = "rtl"):
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

    # Knockout competitions must never display a numeric round as a league
    # week. FotMob can expose domestic-cup rounds as a bare number.
    competition_id = str(
        match.get("leagueId")
        or match.get("competitionId")
        or match.get("tournamentId")
        or ""
    )
    competition_name = str(
        match.get("competitionName")
        or match.get("competition")
        or match.get("league")
        or ""
    ).strip().casefold()
    knockout_by_name = (
        "fa cup" in competition_name
        or "efl cup" in competition_name
        or "carabao cup" in competition_name
        or "copa del rey" in competition_name
        or "supercopa de españa" in competition_name
        or "coppa italia" in competition_name
        or "supercoppa italiana" in competition_name
        or "dfb-pokal" in competition_name
        or "dfl-supercup" in competition_name
        or "coupe de france" in competition_name
        or "trophée des champions" in competition_name
        or "trophee des champions" in competition_name
        or "community shield" in competition_name
    )
    if competition_id in KNOCKOUT_COMPETITION_IDS or knockout_by_name:
        if text.isdigit():
            return f"راند {_to_persian_digits(text)}"
        if low.startswith(("week ", "matchweek ", "match day ", "matchday ")):
            digits = "".join(ch for ch in text if ch.isdigit())
            if digits:
                return f"راند {_to_persian_digits(digits)}"
    # Explicit knockout stages take precedence over generic "Round" handling.
    normalized = re.sub(r"\\s+", " ", low).strip()
    knockout = {
        "1/16": "یک‌شانزدهم نهایی", "1/8": "یک‌هشتم نهایی",
        "1/4": "یک‌چهارم نهایی", "1/2": "نیمه‌نهایی",
        "round of 32": "یک‌شانزدهم نهایی", "round of 16": "یک‌هشتم نهایی",
        "round of 8": "یک‌چهارم نهایی", "quarter-finals": "یک‌چهارم نهایی",
        "quarterfinals": "یک‌چهارم نهایی", "quarterfinal": "یک‌چهارم نهایی",
        "semi-finals": "نیمه‌نهایی", "semifinals": "نیمه‌نهایی",
        "semi-final": "نیمه‌نهایی", "semifinal": "نیمه‌نهایی",
        "final": "فینال", "finals": "فینال",
        "16": "یک‌هشتم نهایی", "32": "یک‌شانزدهم نهایی",
        "8": "یک‌چهارم نهایی", "4": "نیمه‌نهایی",
    }
    normalized = normalized.replace("⅛", "1/8").replace("¼", "1/4").replace("½", "1/2")
    if normalized in knockout:
        return knockout[normalized]
    normalized = re.sub(r"^(?:round|stage)\\s*(?:of\\s*)?", "", normalized).strip()
    normalized = re.sub(r"\\s*(?:final stage|finals|final)$", "", normalized).strip() if normalized not in knockout else normalized
    if normalized in knockout:
        return knockout[normalized]
    if low.startswith(("matchday", "match week", "week", "round")):
        digits = "".join(ch for ch in text if ch.isdigit())
        return f"هفته {_to_persian_digits(digits)}" if digits else text
    if low.startswith("group"):
        return f"گروه {text.split()[-1]}"
    if low in {"friendlies", "friendly"}:
        return "دوستانه"
    return text


def _draw_match_row(image, draw, box, match, accent=ACCENT, compact=False):
    x1, y1, x2, y2 = box
    home = _team_name(match.get("home"))
    away = _team_name(match.get("away"))
    kickoff = _result_label_for_rtl(match)
    stage = _match_stage(match)

    # FotMob's resultLabel is already in HOME-SCORE / AWAY-SCORE order.
    # Keep that exact logical order in both layouts. The score token itself
    # is rendered LTR so shootout parentheses remain real parentheses.
    if compact:
        mid_x = (x1 + x2) // 2
        width = x2 - x1
        home_x = x1 + width * 0.72
        away_x = x1 + width * 0.28
        logo_y = y1 + 42
        name_y = y1 + 91

        logo_size = 48
        for team_id, logo_x in (
            (_team_id(match.get("home")), int(home_x)),
            (_team_id(match.get("away")), int(away_x)),
        ):
            logo = _load_logo(team_id)
            if logo is not None:
                logo = logo.copy()
                logo.thumbnail((logo_size, logo_size), Image.Resampling.LANCZOS)
                _paste_logo(image, logo, (logo_x, logo_y))
            else:
                r = 22
                draw.ellipse((logo_x-r, logo_y-r, logo_x+r, logo_y+r), fill=(45, 63, 86))

        def draw_compact_name(name, center_x):
            max_w = int(width * 0.30)
            sizes = [22, 20, 18, 16, 15, 14]
            font = _fit_font(draw, name, max_w, sizes, True)
            bbox = draw.textbbox((0, 0), name, font=font, direction="rtl", language="fa")
            tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
            draw.text(
                (center_x - tw/2 - bbox[0], name_y - th/2 - bbox[1]),
                name, font=font, fill=TEXT, direction="rtl", language="fa",
            )

        draw_compact_name(home, int(home_x))
        draw_compact_name(away, int(away_x))

        time_font = _latin_font(26 if "(" in kickoff else 31, True)
        clock_width = 190 if match.get("resultLabel") and "(" in kickoff else 126
        clock_h = 42
        draw.rounded_rectangle(
            (mid_x-clock_width//2, y1+40, mid_x+clock_width//2, y1+40+clock_h),
            radius=11, fill=accent,
        )
        bbox = draw.textbbox((0, 0), kickoff, font=time_font, direction="ltr")
        tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
        draw.text(
            (mid_x-tw/2-bbox[0], y1+40+clock_h/2-th/2-bbox[1]),
            kickoff, font=time_font, fill=(255,255,255), direction="ltr",
        )

        if stage:
            stage_font = _fit_font(draw, stage, width-40, [17,15,14,13,12], True)
            bbox = draw.textbbox((0,0), stage, font=stage_font, direction="rtl", language="fa")
            tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
            draw.text(
                (mid_x-tw/2-bbox[0], y1+15-th/2-bbox[1]),
                stage, font=stage_font, fill=MUTED, direction="rtl", language="fa",
            )
        return

    mid_y = (y1 + y2) // 2
    stage_width = 180
    logo_size = 66
    clock_width = 250 if match.get("resultLabel") and "(" in kickoff else 154
    content_left = x1 + 25
    content_right = x2 - stage_width - 20
    mid_x = (content_left + content_right) // 2
    left_logo_x = content_left + 45
    right_logo_x = content_right - 45
    name_gap = 16
    clock_gap = 18

    # Visual direction is intentionally mirrored for RTL: AWAY is on the
    # left and HOME is on the right, while the score remains HOME-AWAY.
    away_name_left = left_logo_x + logo_size//2 + name_gap
    away_name_right = mid_x - clock_width//2 - clock_gap
    home_name_left = mid_x + clock_width//2 + clock_gap
    home_name_right = right_logo_x - logo_size//2 - name_gap

    for team_id, logo_x in (
        (_team_id(match.get("away")), left_logo_x),
        (_team_id(match.get("home")), right_logo_x),
    ):
        logo = _load_logo(team_id)
        if logo is not None:
            logo = logo.copy()
            logo.thumbnail((logo_size, logo_size), Image.Resampling.LANCZOS)
            _paste_logo(image, logo, (logo_x, mid_y))
        else:
            draw.ellipse((logo_x-27, mid_y-27, logo_x+27, mid_y+27), fill=(45,63,86))

    def draw_name(name, left, right):
        max_w = max(1, right-left)
        sizes = [30,28,26,24,22,20,18,16,14]
        font = _fit_font(draw, name, max_w, sizes, True)
        lines = [name]
        if _text_width(draw, name, font) > max_w and len(name.split()) > 1:
            words = name.split()
            for size in sizes:
                candidate_font = _text_font(size, name, True)
                candidates = []
                for split in range(1, len(words)):
                    first, second = " ".join(words[:split]), " ".join(words[split:])
                    fw = _text_width(draw, first, candidate_font)
                    sw = _text_width(draw, second, candidate_font)
                    if max(fw, sw) <= max_w:
                        candidates.append((abs(fw-sw), first, second, candidate_font))
                if candidates:
                    _, first, second, font = min(candidates, key=lambda v: v[0])
                    lines = [first, second]
                    break

        bboxes = [draw.textbbox((0,0), line, font=font, direction="rtl", language="fa") for line in lines]
        gap = 5
        heights = [b[3]-b[1] for b in bboxes]
        total_h = sum(heights)+gap*(len(lines)-1)
        top = mid_y-total_h/2
        for line,bbox,h in zip(lines,bboxes,heights):
            tw=bbox[2]-bbox[0]
            draw.text(((left+right-tw)/2-bbox[0], top-bbox[1]),
                      line,font=font,fill=TEXT,direction="rtl",language="fa")
            top += h+gap

    draw_name(away, away_name_left, away_name_right)
    draw_name(home, home_name_left, home_name_right)

    time_font = _latin_font(29 if "(" in kickoff else 36, True)
    draw.rounded_rectangle(
        (mid_x-clock_width//2, mid_y-24, mid_x+clock_width//2, mid_y+24),
        radius=14, fill=accent,
    )
    bbox = draw.textbbox((0,0), kickoff, font=time_font, direction="ltr")
    tw,th=bbox[2]-bbox[0],bbox[3]-bbox[1]
    draw.text(
        (mid_x-tw/2-bbox[0], mid_y-th/2-bbox[1]),
        kickoff,font=time_font,fill=(255,255,255),direction="ltr",
    )

    if stage:
        stage_font = _fit_font(draw, stage, stage_width-20, [22,20,18,16,14], True)
        bbox = draw.textbbox((0,0), stage,font=stage_font,direction="rtl",language="fa")
        tw,th=bbox[2]-bbox[0],bbox[3]-bbox[1]
        stage_x=x2-stage_width//2
        draw.text(
            (stage_x-tw/2-bbox[0],mid_y-th/2-bbox[1]),
            stage,font=stage_font,fill=MUTED,direction="rtl",language="fa",
        )

def _draw_competition_title(draw, x: int, y: int, competition: str, max_width: int):
    """Render Persian competition text with a Latin-capable font for A/B/C/D."""
    level = None
    base = competition
    for suffix in (" A", " B", " C", " D"):
        if competition.endswith(suffix) and competition.startswith("لیگ ملت‌های اروپا"):
            level = suffix.strip()
            base = competition[:-2]
            break

    if level is None:
        font = _fit_font(draw, competition, max_width, [30, 28, 26, 24], True)
        draw.text((x, y), competition, font=font, fill=TEXT, anchor="rm",
                  direction="rtl", language="fa")
        return

    latin_font = _latin_font(24, True)
    persian_font = _fit_font(draw, base, max_width - 50, [30, 28, 26, 24], True)
    base_width = _text_width(draw, base, persian_font, "rtl")
    level_width = draw.textlength(level, font=latin_font, direction="ltr")
    gap = 10
    total_width = base_width + gap + level_width

    right_edge = x

    # The two fonts have different ascender/descender metrics. Drawing them
    # with the same y-coordinate makes the Latin letter visibly sit too high
    # or too low. Align the actual ink bounds around the same vertical center.
    base_bbox = draw.textbbox(
        (right_edge, y), base, font=persian_font, anchor="ra",
        direction="rtl", language="fa"
    )
    base_center = (base_bbox[1] + base_bbox[3]) / 2
    base_y = y + ((y) - base_center)
    draw.text((right_edge, base_y), base, font=persian_font, fill=TEXT,
              anchor="ra", direction="rtl", language="fa")

    level_right = right_edge - base_width - gap
    level_bbox = draw.textbbox(
        (level_right, y), level, font=latin_font, anchor="ra",
        direction="ltr"
    )
    level_center = (level_bbox[1] + level_bbox[3]) / 2
    level_y = y + ((y) - level_center)
    draw.text((level_right, level_y), level, font=latin_font, fill=TEXT,
              anchor="ra", direction="ltr")

    if total_width > max_width:
        return


def _competition_accent(match: dict) -> tuple[int, int, int]:
    """Stable pseudo-random vivid color per numeric competition ID."""
    key = str(match.get("leagueId") or match.get("competitionId") or match.get("tournamentId") or _competition_name(match))
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    hue = int.from_bytes(digest[:4], "big") / 2**32
    saturation = 0.62 + digest[4] / 255 * 0.18
    # Keep accents dark enough that white text remains readable.
    lightness = 0.36 + digest[5] / 255 * 0.09
    return tuple(round(v * 255) for v in colorsys.hls_to_rgb(hue, lightness, saturation))


def _competition_group_key(match: dict) -> tuple[str, str]:
    competition_id = str(match.get("leagueId") or match.get("competitionId") or match.get("tournamentId") or "")
    return competition_id, _competition_name(match)


def _draw_competition_box(image, draw, x1, y1, x2, matches, competition, compact=False):
    header_h = 58 if compact else 64
    row_h = COMPACT_MATCH_ROW_H if compact else MATCH_ROW_H
    box_h = header_h + len(matches) * row_h + max(0, len(matches)-1)
    y2 = y1 + box_h
    accent = _competition_accent(matches[0])
    draw.rounded_rectangle((x1,y1,x2,y2), radius=CARD_RADIUS, fill=CARD, outline=BORDER, width=2)
    draw.rounded_rectangle((x1+12,y1+13,x1+19,y1+header_h-12), radius=3, fill=accent)
    draw.rounded_rectangle((x1+29,y1+9,x2-12,y1+header_h-7), radius=12, fill=(26, 42, 65))
    _draw_competition_title(draw, x2-22, y1+header_h//2, competition, x2-x1-40)
    draw.line((x1+18,y1+header_h,x2-18,y1+header_h), fill=BORDER, width=2)
    for i, match in enumerate(matches):
        ry1 = y1 + header_h + i*(row_h+1)
        ry2 = ry1 + row_h
        if i:
            draw.line((x1+35,ry1,x2-35,ry1), fill=BORDER, width=1)
        _draw_match_row(image, draw, (x1+18,ry1,x2-18,ry2), match, accent, compact=compact)
    return y2

def _draw_card(image, draw, box, match, compact):
    _draw_competition_box(image, draw, box[0], box[1], box[2], [match], _competition_name(match))


def _group_matches(matches):
    groups = OrderedDict()
    for match in matches:
        groups.setdefault(_competition_group_key(match), []).append(match)
    return [(name, items) for (_id, name), items in groups.items()]


def _render_page(groups, day, page_no, page_total, output, cards_per_row):
    two_column = cards_per_row == 2
    row_h = COMPACT_MATCH_ROW_H if two_column else MATCH_ROW_H
    header_h = 58 if two_column else 64
    render_groups = groups

    if two_column:
        # render_fixtures() already assigned every group to a column while
        # enforcing the 10-match cap. Respect that assignment here instead of
        # rebalancing groups and accidentally putting 20 matches in one column.
        columns = [[], []]
        heights = [0, 0]
        for entry in groups:
            if len(entry) == 3:
                competition, items, target = entry
            else:
                competition, items = entry
                target = 0 if heights[0] <= heights[1] else 1
            target = 0 if int(target) <= 0 else 1
            columns[target].append((competition, items))
            comp_h = header_h + len(items) * row_h + max(0, len(items)-1)
            heights[target] += comp_h + (
                COMPETITION_GAP if len(columns[target]) > 1 else 0
            )
        content_h = max(heights)
    else:
        comp_heights = [header_h + len(items) * row_h + max(0, len(items)-1) for _, items in groups]
        content_h = sum(comp_heights) + max(0, len(groups)-1)*COMPETITION_GAP

    height = min(MAX_HEIGHT, max(MIN_HEIGHT, HEADER_H + 26 + content_h + 70))
    image = Image.new("RGB", (WIDTH, height), BG)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((MARGIN_X, 36, WIDTH-MARGIN_X, 43), radius=3, fill=(42, 112, 193))
    draw.line((MARGIN_X, HEADER_H-22, WIDTH-MARGIN_X, HEADER_H-22), fill=BORDER, width=2)
    draw.text((WIDTH - MARGIN_X, 68), ("نتایج روز قبل" if groups and groups[0][1][0].get("resultLabel") else "مسابقات امروز"), font=_font(56, True), fill=TEXT,
              anchor="ra", direction="rtl", language="fa")
    date_font = _font(25)
    date_parts = _jalali_date(day).split("/")
    date_x = WIDTH - MARGIN_X
    date_anchor_y = 145
    sample_box = draw.textbbox((0, date_anchor_y), "۱۴۰۵", font=date_font, anchor="ra", direction="ltr")
    digit_top, digit_bottom = sample_box[1], sample_box[3]
    slash_top = digit_top + 2
    slash_bottom = digit_bottom - 2
    for index, part in enumerate(reversed(date_parts)):
        draw.text((date_x, date_anchor_y), part, font=date_font, fill=MUTED, anchor="ra", direction="ltr")
        date_x -= draw.textlength(part, font=date_font, direction="ltr")
        if index < len(date_parts) - 1:
            date_x -= 9
            draw.line((date_x - 13, slash_bottom, date_x - 2, slash_top), fill=MUTED, width=3)
            date_x -= 22
    if page_total > 1:
        draw.text((MARGIN_X, 145), f"{_to_persian_digits(str(page_no))} / {_to_persian_digits(str(page_total))}",
                  font=_font(22, True), fill=MUTED, anchor="la", direction="ltr")

    if two_column:
        column_width = (WIDTH - 2*MARGIN_X - COLUMN_GAP) // 2
        for col, col_groups in enumerate(columns):
            x1 = MARGIN_X + col * (column_width + COLUMN_GAP)
            x2 = x1 + column_width
            y = HEADER_H
            for competition, items in col_groups:
                box_h = header_h + len(items) * row_h + max(0, len(items)-1)
                _draw_competition_box(image, draw, x1, y, x2, items, competition, compact=True)
                y += box_h + COMPETITION_GAP
    else:
        y = HEADER_H
        for competition, items in render_groups:
            box_h = header_h + len(items) * row_h + max(0, len(items)-1)
            _draw_competition_box(image, draw, MARGIN_X, y, WIDTH-MARGIN_X, items, competition, compact=False)
            y += box_h + COMPETITION_GAP

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "PNG", optimize=True)

def render_fixtures(matches: list[dict], day: dt.date, output: Path) -> None:
    if not matches:
        raise ValueError("Cannot render a fixture report with zero matches.")
    if not features.check("raqm"):
        raise RuntimeError("Pillow was built without libraqm; Persian RTL rendering cannot be trusted.")

    grouped = _group_matches(matches)

    # A competition card is never allowed to put more than 10 matches in one
    # column. If a competition itself has more than 10 matches, split it into
    # consecutive chunks and repeat the competition header for each chunk.
    groups = []
    for competition, items in grouped:
        for start in range(0, len(items), MAX_MATCHES_PER_COLUMN):
            groups.append(
                (competition, items[start:start + MAX_MATCHES_PER_COLUMN])
            )

    use_two_columns = len(matches) >= TWO_COLUMN_THRESHOLD
    cards_per_row = 2 if use_two_columns else 1
    row_h = COMPACT_MATCH_ROW_H if use_two_columns else MATCH_ROW_H
    header_h = 58 if use_two_columns else 64
    usable_h = MAX_HEIGHT - HEADER_H - 70

    pages = []
    current = []
    used = [0, 0] if use_two_columns else [0]
    match_counts = [0, 0] if use_two_columns else [0]

    for competition, items in groups:
        comp_h = header_h + len(items) * row_h + max(0, len(items)-1)
        if use_two_columns:
            target = None
            for candidate in sorted((0, 1), key=lambda col: (match_counts[col], used[col])):
                needed = comp_h + (COMPETITION_GAP if used[candidate] else 0)
                if match_counts[candidate] + len(items) <= MAX_MATCHES_PER_COLUMN and (
                    not used[candidate] or used[candidate] + needed <= usable_h
                ):
                    target = candidate
                    break

            if target is None:
                pages.append(current)
                current = []
                used = [0, 0]
                match_counts = [0, 0]
                target = 0

            current.append((competition, items, target))
            used[target] += comp_h + (COMPETITION_GAP if used[target] else 0)
            match_counts[target] += len(items)
        else:
            needed = comp_h + (COMPETITION_GAP if current else 0)
            if current and used[0] + needed > usable_h:
                pages.append(current)
                current = []
                used = [0]
            current.append((competition, items))
            used[0] += needed

    if current:
        pages.append(current)

    page_total = len(pages)
    if page_total == 1:
        if use_two_columns:
            _render_page(pages[0], day, 1, 1, output, 2)
        else:
            _render_page(pages[0], day, 1, 1, output, 1)
        return

    stem, suffix = output.stem, output.suffix or ".png"
    generated = []
    for index, page in enumerate(pages, start=1):
        path = output.with_name(f"{stem}-{index}{suffix}")
        if use_two_columns:
            _render_page(page, day, index, page_total, path, 2)
        else:
            _render_page(page, day, index, page_total, path, 1)
        generated.append(path)
    generated[0].replace(output)


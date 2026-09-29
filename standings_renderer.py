from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, features

from renderer import _competition_name, _font, _team_name


WIDTH = 1600
MARGIN_X = 90
HEADER_H = 220
BG = (9, 17, 33)
CARD = (20, 32, 52)
TEXT = (244, 248, 255)
MUTED = (166, 184, 207)
BORDER = (48, 67, 92)
ACCENT = (42, 112, 193)
ROW_H = 88
HEADER_ROW_H = 72
CARD_RADIUS = 26
LOGO_SIZE = 58
LOGO_DIR = Path("output/team_logos")
LOGO_DIR.mkdir(parents=True, exist_ok=True)


def _latin_font(size: int, bold: bool = False):
    candidates = [
        Path("/usr/share/fonts/truetype/dejavu/" + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")),
        Path("/usr/share/fonts/truetype/noto/" + ("NotoSans-Bold.ttf" if bold else "NotoSans-Regular.ttf")),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(path, size)
    return _font(size, bold)


def _persian_digits(value: Any) -> str:
    return str(value).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _team_logo(team_id: str):
    if not team_id:
        return None
    import requests
    url = f"https://images.fotmob.com/image_resources/logo/teamlogo/{team_id}_small.png"
    path = LOGO_DIR / f"{team_id}.png"
    try:
        if not path.exists():
            response = requests.get(url, timeout=8)
            response.raise_for_status()
            path.write_bytes(response.content)
        image = Image.open(path).convert("RGBA")
        image.thumbnail((LOGO_SIZE, LOGO_SIZE), Image.Resampling.LANCZOS)
        return image
    except Exception as error:
        print(f"[STANDINGS] logo {team_id}: {error}")
        return None


def _jalali_date(date_value):
    try:
        import jdatetime
        return jdatetime.date.fromgregorian(date=date_value).strftime("%Y/%m/%d")
    except Exception:
        return date_value.strftime("%Y/%m/%d")


def _draw_text(draw, xy, text, font, fill, anchor="mm", direction="rtl"):
    kwargs = {"anchor": anchor, "fill": fill}
    if direction:
        kwargs["direction"] = direction
        kwargs["language"] = "fa"
    draw.text(xy, str(text), font=font, **kwargs)


def _competition_display_name(competition_id: str, english_name: str) -> str:
    return _competition_name(
        {
            "leagueId": str(competition_id),
            "competitionName": english_name,
        }
    )


def _table_widths():
    # Keep the complete standard FotMob league columns inside the poster.
    return {
        "rank": 62,
        "team": 470,
        "played": 90,
        "wins": 90,
        "draws": 90,
        "losses": 90,
        "gf": 105,
        "ga": 105,
        "gd": 105,
        "points": 113,
    }


def _draw_table(draw, image, x1, y, x2, table):
    rows = table["rows"]
    widths = _table_widths()
    total = sum(widths.values())
    if x2 - x1 < total:
        raise ValueError("Standings card is narrower than its required columns.")

    # Header
    draw.rounded_rectangle(
        (x1, y, x2, y + HEADER_ROW_H),
        radius=18,
        fill=(27, 42, 65),
        outline=BORDER,
        width=1,
    )

    positions = {}
    cursor = x2
    for key in ("points", "gd", "ga", "gf", "losses", "draws", "wins", "played", "team", "rank"):
        cursor -= widths[key]
        positions[key] = (cursor, cursor + widths[key])

    labels = {
        "points": "امتیاز",
        "gd": "تفاضل",
        "ga": "گل‌خورده",
        "gf": "گل‌زده",
        "losses": "باخت",
        "draws": "مساوی",
        "wins": "برد",
        "played": "بازی",
        "team": "تیم",
        "rank": "#",
    }
    for key, (left, right) in positions.items():
        center = (left + right) / 2
        if key == "team":
            _draw_text(draw, (right - 18, y + HEADER_ROW_H / 2), labels[key], _font(27, True), TEXT, "rm")
        else:
            _draw_text(draw, (center, y + HEADER_ROW_H / 2), labels[key], _font(24, True), TEXT)

    row_y = y + HEADER_ROW_H
    for index, row in enumerate(rows):
        fill = CARD if index % 2 == 0 else (23, 37, 58)
        draw.rectangle((x1, row_y, x2, row_y + ROW_H), fill=fill)

        for key, (left, right) in positions.items():
            center = (left + right) / 2
            if key == "team":
                team_id = str(row.get("teamId") or "")
                logo = _team_logo(team_id)
                logo_x = right - 28 - LOGO_SIZE
                if logo:
                    image.alpha_composite(logo, (int(logo_x), int(row_y + (ROW_H - logo.height) / 2)))
                team_name = _team_name(
                    {
                        "id": team_id,
                        "name": row.get("teamName") or "—",
                    }
                )
                _draw_text(
                    draw,
                    (logo_x - 16, row_y + ROW_H / 2),
                    team_name,
                    _font(28, True),
                    TEXT,
                    "rm",
                )
                continue

            field = {
                "rank": "rank",
                "played": "played",
                "wins": "wins",
                "draws": "draws",
                "losses": "losses",
                "gf": "goalsFor",
                "ga": "goalsAgainst",
                "gd": "goalDiff",
                "points": "points",
            }[key]
            value = row.get(field)
            if value is None:
                value = "—"
            text = _persian_digits(value)
            font = _font(27, key in ("points", "rank"))
            _draw_text(draw, (center, row_y + ROW_H / 2), text, font, TEXT, "mm")

        draw.line((x1, row_y + ROW_H - 1, x2, row_y + ROW_H - 1), fill=BORDER, width=1)
        row_y += ROW_H

    return row_y


def render_standings(data: dict, day, output: Path) -> None:
    if not features.check("raqm"):
        raise RuntimeError("Pillow was built without libraqm; Persian RTL rendering cannot be trusted.")

    tables = data.get("tables") or []
    if not tables:
        raise ValueError("Cannot render standings without tables.")

    competition_id = str(data.get("competitionId") or "")
    english_name = str(data.get("competitionName") or "")
    competition = _competition_display_name(competition_id, english_name)
    season = str(data.get("season") or "فصل جاری")

    # A single league table currently fits comfortably in one poster. Multiple
    # real groups are stacked and keep their own explicit FotMob group labels.
    card_height = 0
    for table in tables:
        card_height += HEADER_ROW_H + ROW_H * len(table["rows"]) + 26
        if table.get("group"):
            card_height += 54

    height = max(760, HEADER_H + card_height + 90)
    image = Image.new("RGBA", (WIDTH, height), BG + (255,))
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((MARGIN_X, 34, WIDTH - MARGIN_X, 42), radius=4, fill=ACCENT)
    draw.line((MARGIN_X, HEADER_H - 22, WIDTH - MARGIN_X, HEADER_H - 22), fill=BORDER, width=2)

    _draw_text(draw, (WIDTH - MARGIN_X, 78), f"جدول {competition}", _font(52, True), TEXT, "ra")
    _draw_text(draw, (WIDTH - MARGIN_X, 142), season, _font(27), MUTED, "ra")

    try:
        jalali = _jalali_date(day)
    except Exception:
        jalali = str(day)
    _draw_text(draw, (MARGIN_X, 112), _persian_digits(jalali.replace("/", " / ")), _latin_font(24), MUTED, "la", "ltr")

    y = HEADER_H
    for index, table in enumerate(tables):
        x1, x2 = MARGIN_X, WIDTH - MARGIN_X
        group = str(table.get("group") or "").strip()

        extra = 0
        if group:
            _draw_text(draw, (x2 - 24, y + 26), group, _font(29, True), TEXT, "ra")
            extra = 54

        table_y = y + extra
        table_bottom = table_y + HEADER_ROW_H + ROW_H * len(table["rows"])
        draw.rounded_rectangle(
            (x1, y, x2, table_bottom + 18),
            radius=CARD_RADIUS,
            fill=CARD,
            outline=BORDER,
            width=2,
        )
        _draw_table(draw, image, x1 + 16, table_y + 2, x2 - 16, table)
        y = table_bottom + 44

    output.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output, "PNG", optimize=True)

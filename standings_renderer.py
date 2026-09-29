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


def _league_logo(competition_id: str):
    if not competition_id:
        return None
    import requests
    path = LOGO_DIR / f"league_{competition_id}.png"
    try:
        if not path.exists():
            base = "https://images." + "fotmob.com/image_resources/logo/"
            response = requests.get(base + "leaguelogo/" + str(competition_id) + ".png", timeout=8)
            response.raise_for_status()
            path.write_bytes(response.content)
        image = Image.open(path).convert("RGBA")

        # Ligue 1's logo is predominantly black, so invert its RGB colors
        # for better contrast against the dark standings header.
        if str(competition_id) == "53":
            from PIL import ImageOps
            alpha = image.getchannel("A")
            rgb = ImageOps.invert(image.convert("RGB"))
            image = Image.merge("RGBA", (*rgb.split(), alpha))

        image.thumbnail((72, 72), Image.Resampling.LANCZOS)
        return image
    except Exception as error:
        print(f"[STANDINGS] league logo {competition_id}: {error}")
        return None


def _qual_color(row: dict):
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    value = raw.get("qualColor") or raw.get("qualifyingColor") or row.get("qualColor")
    if not value:
        return None
    value = str(value).strip()
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        return None
    return tuple(int(value[i:i+2], 16) for i in (1, 3, 5))


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
        if direction == "rtl":
            kwargs["language"] = "fa"
    draw.text(xy, str(text), font=font, **kwargs)



def _group_display_name(value: Any) -> str:
    text = " ".join(str(value or "").replace("\xa0", " ").split()).strip()
    if not text:
        return ""

    # FotMob may return variants such as "Group E", "Grp E",
    # "Grp. E", or "Grp . E". Normalize all of them to Persian so the
    # renderer never has to display the English group abbreviation.
    match = re.fullmatch(
        r"(?:Group|Grp)\s*\.?\s*([A-Za-z0-9]+)",
        text,
        re.IGNORECASE,
    )
    if match:
        label = match.group(1)
        if label.isdigit():
            label = _persian_digits(label)
        return f"گروه {label}"

    # Also handle a few API variants where the group label is separated
    # from the word by punctuation.
    match = re.fullmatch(
        r"(?:Group|Grp)\s*\.\s*([A-Za-z0-9]+)",
        text,
        re.IGNORECASE,
    )
    if match:
        label = match.group(1)
        if label.isdigit():
            label = _persian_digits(label)
        return f"گروه {label}"

    return text

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
        "played": 96,
        "wins": 96,
        "draws": 96,
        "losses": 96,
        "gf": 110,
        "ga": 110,
        "gd": 110,
        "points": 117,
    }


def _draw_table(draw, image, x1, y, x2, table):
    rows = table["rows"]
    widths = _table_widths()
    total = sum(widths.values())
    if x2 - x1 < total:
        raise ValueError("Standings card is narrower than its required columns.")

    draw.rounded_rectangle(
        (x1, y, x2, y + HEADER_ROW_H),
        radius=18,
        fill=(27, 42, 65),
        outline=BORDER,
        width=1,
    )

    positions = {}
    cursor = x2
    for key in ("rank", "team", "played", "wins", "draws", "losses", "gf", "ga", "gd", "points"):
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
            _draw_text(draw, (right - 18, y + HEADER_ROW_H / 2), labels[key], _font(31, True), TEXT, "rm")
        elif key != "rank":
            _draw_text(draw, (center, y + HEADER_ROW_H / 2), labels[key], _font(30, True), TEXT)

    row_y = y + HEADER_ROW_H
    for index, row in enumerate(rows):
        fill = CARD if index % 2 == 0 else (23, 37, 58)
        draw.rectangle((x1, row_y, x2, row_y + ROW_H), fill=fill)

        for key, (left, right) in positions.items():
            center = (left + right) / 2
            if key == "team":
                team_id = str(row.get("teamId") or "")
                team_right = right - 18
                logo_x = team_right - LOGO_SIZE - 14
                logo = _team_logo(team_id)
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
                    (logo_x - 14, row_y + ROW_H / 2),
                    team_name,
                    _font(32, True),
                    TEXT,
                    "rm",
                )
                qual_color = _qual_color(row)
                if qual_color:
                    draw.rounded_rectangle(
                        (right - 8, row_y + 12, right - 2, row_y + ROW_H - 12),
                        radius=3,
                        fill=qual_color,
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
            font = _font(38, True)
            _draw_text(
                draw,
                (center, row_y + ROW_H / 2),
                text,
                font,
                TEXT,
                "mm",
                "ltr",
            )

        draw.line((x1, row_y + ROW_H - 1, x2, row_y + ROW_H - 1), fill=BORDER, width=1)
        row_y += ROW_H

    return row_y


def _draw_standings_title(draw, right_x: int, y: int, title_text: str):
    """Render a mixed Persian/Latin title in the poster's intended visual order.

    Titles such as «جدول جام جهانی گروه L» are laid out explicitly from
    visual left to visual right. Each Persian token still uses RTL shaping,
    while Latin group letters use a Latin-capable font.
    """
    text = str(title_text or "").replace("|", " ")
    tokens = re.findall(
        r"[A-Za-z0-9]+(?:[./:-][A-Za-z0-9]+)*|"
        r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+|"
        r"[^\w\s]",
        text,
    )
    if not tokens:
        return 0

    gap = 10
    measured = []

    for token in tokens:
        if re.fullmatch(r"[A-Za-z0-9]+(?:[./:-][A-Za-z0-9]+)*", token):
            font = _latin_font(42 if len(token) <= 2 else 46, True)
            direction = "ltr"
            language = None
        elif re.fullmatch(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+", token):
            font = _font(52, True)
            direction = "rtl"
            language = "fa"
        else:
            font = _latin_font(42, True)
            direction = "ltr"
            language = None

        kwargs = {"direction": direction}
        if language:
            kwargs["language"] = language
        bbox = draw.textbbox((0, 0), token, font=font, **kwargs)
        measured.append((token, font, direction, language, bbox[2] - bbox[0]))

    total_width = sum(item[4] for item in measured) + gap * (len(measured) - 1)
    x = float(right_x) - total_width

    # The title is a right-to-left sentence. PIL shapes each Persian token
    # correctly with direction="rtl", but explicit token placement must also
    # follow the visual RTL order. Therefore the logical token list is laid
    # out from right to left (the last token occupies the leftmost position).
    for token, font, direction, language, width in reversed(measured):
        token_right = x + width
        kwargs = {
            "anchor": "ra",
            "direction": direction,
            "fill": TEXT,
        }
        if language:
            kwargs["language"] = language

        bbox_kwargs = {"font": font, "anchor": "ra", "direction": direction}
        if language:
            bbox_kwargs["language"] = language
        bbox = draw.textbbox((token_right, y), token, **bbox_kwargs)
        ink_center = (bbox[1] + bbox[3]) / 2
        draw_y = y + (y - ink_center)
        draw.text((token_right, draw_y), token, font=font, **kwargs)
        x += width + gap

    return total_width


def render_standings(data: dict, day, output: Path, title_suffix: str | None = None) -> None:
    if not features.check("raqm"):
        raise RuntimeError("Pillow was built without libraqm; Persian RTL rendering cannot be trusted.")

    tables = data.get("tables") or []
    if not tables:
        raise ValueError("Cannot render standings without tables.")

    competition_id = str(data.get("competitionId") or "")
    english_name = str(data.get("competitionName") or "")
    competition = _competition_display_name(competition_id, english_name)
    season = str(data.get("season") or "فصل جاری")

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

    title_y = 108
    title_right = WIDTH - MARGIN_X
    title_text = f"جدول {competition}"
    if title_suffix:
        title_text = f"{title_text} {_group_display_name(title_suffix)}"
    title_width = _draw_standings_title(draw, title_right, title_y, title_text)

    season_text = season.replace("2026/2027", "2026/27") if season else ""
    season_font = _latin_font(27, True)

    season_gap = 20
    season_right = title_right - title_width - season_gap
    if season_text:
        _draw_text(
            draw,
            (season_right, title_y),
            season_text,
            season_font,
            MUTED,
            "rm",
            "ltr",
        )

    season_bbox = draw.textbbox(
        (0, 0),
        season_text,
        font=season_font,
        anchor="rm",
        direction="ltr",
        language="en",
    ) if season_text else (0, 0, 0, 0)
    season_width = season_bbox[2] - season_bbox[0]

    logo_gap = 18
    league_logo = _league_logo(competition_id)
    if league_logo:
        logo_x = season_right - season_width - logo_gap - league_logo.width
        logo_y = title_y - league_logo.height / 2
        image.alpha_composite(league_logo, (int(logo_x), int(logo_y)))

    y = HEADER_H
    for index, table in enumerate(tables):
        x1, x2 = MARGIN_X, WIDTH - MARGIN_X
        group = _group_display_name(table.get("group"))

        extra = 0
        if group:
            group_match = re.fullmatch(r"(گروه) ([A-Za-z0-9]+)", group)
            if group_match:
                group_word, group_label = group_match.groups()
                group_label_font = _latin_font(29, True) if group_label.isalpha() else _font(29, True)
                label_bbox = draw.textbbox(
                    (x2 - 24, y + 26),
                    group_label,
                    font=group_label_font,
                    anchor="ra",
                    direction="ltr",
                )
                label_width = label_bbox[2] - label_bbox[0]
                _draw_text(
                    draw,
                    (x2 - 24 - label_width - 10, y + 26),
                    group_word,
                    _font(29, True),
                    TEXT,
                    "ra",
                )
                draw.text(
                    (x2 - 24, y + 26),
                    group_label,
                    font=group_label_font,
                    fill=TEXT,
                    anchor="ra",
                    direction="ltr",
                )
            else:
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


def render_group_standings(data: dict, table: dict, day, output: Path) -> None:
    """Render exactly one group as an independent poster."""
    group = _group_display_name(table.get("group"))
    if not group:
        raise ValueError("Cannot render an individual group without a group name.")

    group_data = dict(data)
    group_data["tables"] = [table]
    render_standings(group_data, day, output, title_suffix=group)

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
ACTIVE_STAGE_BG = (27, 45, 69)
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

    if text.casefold() == "best 3rd placed teams":
        return "برترین تیم های سوم"

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


def _render_grouped_combined(data: dict, output: Path) -> None:
    """Render a compact multi-column poster for completed group stages."""
    tables = data.get("tables") or []
    real_groups = [
        t for t in tables
        if _group_display_name(t.get("group")).startswith("گروه ")
    ]
    auxiliary = [t for t in tables if t not in real_groups]
    if not real_groups:
        raise ValueError("No real group tables found for grouped combined rendering.")

    cols = 3
    gap_x = 28
    gap_y = 28
    card_w = (WIDTH - 2 * MARGIN_X - gap_x * (cols - 1)) // cols
    header_h = 54
    row_h = 64
    title_h = 150

    def card_height(table):
        return header_h + row_h * len(table["rows"]) + 18

    group_rows = (len(real_groups) + cols - 1) // cols
    group_heights = []
    for row_start in range(0, len(real_groups), cols):
        group_heights.append(
            max(card_height(t) for t in real_groups[row_start:row_start + cols])
        )

    aux_h = sum(58 + row_h * len(t["rows"]) + 18 for t in auxiliary)
    height = max(
        760,
        title_h + sum(group_heights)
        + gap_y * max(0, group_rows - 1)
        + (gap_y + aux_h if auxiliary else 0)
        + 70,
    )
    image = Image.new("RGBA", (WIDTH, height), BG + (255,))
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((MARGIN_X, 34, WIDTH - MARGIN_X, 42),
                           radius=4, fill=ACCENT)
    draw.line((MARGIN_X, title_h - 22, WIDTH - MARGIN_X, title_h - 22),
              fill=BORDER, width=2)

    competition_id = str(data.get("competitionId") or "")
    competition = _competition_display_name(
        competition_id, str(data.get("competitionName") or "")
    )
    _draw_standings_title(draw, WIDTH - MARGIN_X, 92, f"جدول {competition}")

    season = str(data.get("season") or "")
    if season:
        _draw_text(
            draw, (MARGIN_X, 92),
            season.replace("2026/2027", "2026/27"),
            _latin_font(24, True), MUTED, "lm", "ltr"
        )

    y = title_h
    for row_start in range(0, len(real_groups), cols):
        row_tables = real_groups[row_start:row_start + cols]
        row_h_total = group_heights[row_start // cols]

        for col, table in enumerate(row_tables):
            x = MARGIN_X + col * (card_w + gap_x)
            y0 = y
            y1 = y + row_h_total
            draw.rounded_rectangle(
                (x, y0, x + card_w, y1),
                radius=18, fill=CARD, outline=BORDER, width=2
            )

            group = _group_display_name(table.get("group"))
            match = re.fullmatch(r"گروه ([A-Za-z0-9]+)", group)
            label = match.group(1) if match else group
            font = _latin_font(27, True) if label.isalpha() else _font(27, True)
            _draw_text(draw, (x + card_w - 18, y0 + 27), "گروه",
                       _font(27, True), TEXT, "rm")
            draw.text((x + card_w - 18 - 12, y0 + 27), label,
                      font=font, fill=TEXT, anchor="rm", direction="ltr")

            rank_x = x + 34
            points_x = x + card_w - 34
            team_right = points_x - 74
            stats_right = team_right - 8
            row_y = y0 + header_h

            for i, row in enumerate(table["rows"]):
                draw.line((x + 12, row_y, x + card_w - 12, row_y),
                          fill=BORDER, width=1)
                _draw_text(
                    draw, (rank_x, row_y + row_h / 2),
                    _persian_digits(row.get("rank", i + 1)),
                    _font(25, True), TEXT, "mm", "ltr"
                )
                _draw_text(
                    draw, (points_x, row_y + row_h / 2),
                    _persian_digits(row.get("points", "—")),
                    _font(28, True), TEXT, "mm", "ltr"
                )

                team_id = str(row.get("teamId") or "")
                logo = _team_logo(team_id)
                logo_x = team_right - LOGO_SIZE
                if logo:
                    image.alpha_composite(
                        logo, (int(logo_x), int(row_y + (row_h - logo.height) / 2))
                    )
                team_name = _team_name({
                    "id": team_id, "name": row.get("teamName") or "—"
                })
                team_text_right = logo_x - 10
                team_text_left = x + 76
                team_font, team_direction, team_language = _fit_group_team_name(
                    draw, team_name, max(40, team_text_right - team_text_left)
                )
                team_kwargs = {
                    "anchor": "rm", "fill": TEXT, "direction": team_direction
                }
                if team_language:
                    team_kwargs["language"] = team_language
                draw.text(
                    (team_text_right, row_y + row_h / 2),
                    team_name, font=team_font, **team_kwargs
                )

                gd = row.get("goalDiff")
                gd_text = "—" if gd is None else _persian_digits(gd)
                _draw_text(draw, (stats_right, row_y + row_h / 2),
                           gd_text, _font(23, True), MUTED, "rm", "ltr")
                row_y += row_h

        y += row_h_total + gap_y

    for table in auxiliary:
        h = 58 + row_h * len(table["rows"]) + 18
        draw.rounded_rectangle(
            (MARGIN_X, y, WIDTH - MARGIN_X, y + h),
            radius=18, fill=CARD, outline=BORDER, width=2
        )
        title = _group_display_name(table.get("group")) or "جدول تکمیلی"
        _draw_text(draw, (WIDTH - MARGIN_X - 24, y + 29), title,
                   _font(31, True), TEXT, "rm")

        row_y = y + 58
        col_w = (WIDTH - 2 * MARGIN_X) / 4
        chunks = [table["rows"][i:i + 3]
                  for i in range(0, len(table["rows"]), 3)]
        for col, chunk in enumerate(chunks[:4]):
            cx = WIDTH - MARGIN_X - col_w * (col + 0.5)
            for j, row in enumerate(chunk):
                yy = row_y + j * row_h + row_h / 2
                _draw_text(draw, (cx + 30, yy),
                           _persian_digits(row.get("rank", "")),
                           _font(24, True), TEXT, "rm", "ltr")
                team_id = str(row.get("teamId") or "")
                logo = _team_logo(team_id)
                if logo:
                    image.alpha_composite(
                        logo, (int(cx - col_w / 2 + 24), int(yy - logo.height / 2))
                    )
                team_name = _team_name({
                    "id": team_id, "name": row.get("teamName") or "—"
                })
                team_text_right = cx - 8
                team_text_left = cx - col_w / 2 + 58
                team_font, team_direction, team_language = _fit_group_team_name(
                    draw, team_name, max(40, team_text_right - team_text_left)
                )
                team_kwargs = {
                    "anchor": "rm", "fill": TEXT, "direction": team_direction
                }
                if team_language:
                    team_kwargs["language"] = team_language
                draw.text(
                    (team_text_right, yy),
                    team_name, font=team_font, **team_kwargs
                )
                points = row.get("points")
                if points is not None:
                    _draw_text(draw, (cx - col_w / 2 + 86, yy),
                               _persian_digits(points), _font(24, True),
                               TEXT, "lm", "ltr")

    output.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output, "PNG", optimize=True)



def _is_placeholder_team(
    name: Any,
    team_id: str = "",
    tbd: bool = False,
    raw: Any = None,
) -> bool:
    """Detect bracket placeholders before any team-logo request is made."""
    candidates: list[str] = []
    cleaned = _clean_knockout_team_value(name)
    if cleaned:
        candidates.append(cleaned)

    if isinstance(raw, dict):
        for key in (
            "name", "teamName", "shortName", "longName",
            "homeTeamName", "awayTeamName", "homeName", "awayName",
        ):
            value = _clean_knockout_team_value(raw.get(key))
            if value:
                candidates.append(value)
        if raw.get("tbd") is True or raw.get("isTbd") is True:
            return True

    if tbd:
        return True

    patterns = (
        r"^TBD(?:\s+\d+)?$",
        r"^TBC(?:\s+\d+)?$",
        r"^TO BE DETERMINED$",
        r"^TO BE CONFIRMED$",
        r"^UNKNOWN$",
        r"^BYE$",
        r"^(?:WINNER|LOSER)\s+[A-Z0-9][A-Z0-9 ._-]*$",
        r"^\d+[A-Z](?:[A-Z]+)?$",
    )
    return any(
        any(re.fullmatch(pattern, value, re.IGNORECASE) for pattern in patterns)
        for value in candidates
    )


def _knockout_team_name(
    name: str,
    team_id: str,
    tbd: bool,
    raw: Any = None,
) -> str:
    """Render the actual FotMob placeholder token when one exists."""
    text = _clean_knockout_team_value(name)
    if text and _is_placeholder_team(text, team_id, tbd, raw):
        return text
    if tbd or not text:
        return "تعیین نشده"
    return _team_name({"id": team_id, "name": text})


def _clean_knockout_team_value(value: Any) -> str:
    if isinstance(value, dict):
        value = (
            value.get("name")
            or value.get("longName")
            or value.get("shortName")
            or value.get("teamName")
        )
    if value is None:
        return ""
    return " ".join(str(value).replace("\xa0", " ").split()).strip()


def _knockout_match_team(matchup: dict, side: str) -> tuple[str, str]:
    """Resolve a team from the normalized matchup and its raw FotMob data."""
    is_home = side == "home"
    name_key = "homeTeam" if is_home else "awayTeam"
    id_key = "homeTeamId" if is_home else "awayTeamId"
    name = _clean_knockout_team_value(matchup.get(name_key))
    team_id = str(matchup.get(id_key) or "")

    raw = matchup.get("raw")
    if isinstance(raw, dict):
        nested = raw.get("home" if is_home else "away")
        if isinstance(nested, dict):
            team_id = team_id or str(nested.get("id") or nested.get("teamId") or "")
            name = name or _clean_knockout_team_value(nested)

        for key in (
            "homeTeamName" if is_home else "awayTeamName",
            "homeName" if is_home else "awayName",
        ):
            name = name or _clean_knockout_team_value(raw.get(key))

    if not name:
        for match in matchup.get("matches") or []:
            if not isinstance(match, dict):
                continue
            nested = match.get("home" if is_home else "away")
            if isinstance(nested, dict):
                team_id = team_id or str(nested.get("id") or nested.get("teamId") or "")
                name = name or _clean_knockout_team_value(nested)
            name = name or _clean_knockout_team_value(
                match.get("homeTeamName" if is_home else "awayTeamName")
            )

    return name, team_id


def _knockout_stage_font_size(stage: str) -> int:
    return 31 if len(stage) <= 16 else 27


def _fit_group_team_name(draw, name: str, max_width: float):
    """Fit a group-table team name inside its measured cell without clipping."""
    is_persian = _knockout_name_is_persian(name)
    direction = "rtl" if is_persian else "ltr"
    language = "fa" if is_persian else None
    for size in (24, 23, 22, 21, 20, 19, 18, 17, 16):
        font = _font(size, True) if is_persian else _latin_font(size, True)
        kwargs = {"font": font, "direction": direction}
        if language:
            kwargs["language"] = language
        bbox = draw.textbbox((0, 0), name, **kwargs)
        if bbox[2] - bbox[0] <= max_width:
            return font, direction, language
    font = _font(16, True) if is_persian else _latin_font(16, True)
    return font, direction, language


def _knockout_match_score(matchup: dict) -> tuple[str, str | None, str | None]:
    """Return each team's normal score plus its shootout score."""
    home = matchup.get("homeScore")
    away = matchup.get("awayScore")
    if home is None or away is None:
        return "—", None, None

    score = f"{_persian_digits(home)} - {_persian_digits(away)}"
    penalty = matchup.get("penaltyScore")
    if (
        isinstance(penalty, dict)
        and penalty.get("home") is not None
        and penalty.get("away") is not None
    ):
        return (
            score,
            _persian_digits(penalty["home"]),
            _persian_digits(penalty["away"]),
        )

    return score, None, None


def _knockout_name_is_persian(name: str) -> bool:
    return any(
        "\u0600" <= ch <= "\u06ff"
        or "\u0750" <= ch <= "\u077f"
        or "\u08a0" <= ch <= "\u08ff"
        for ch in str(name)
    )


def _fit_knockout_name(draw, name: str, right: float, left: float):
    """Choose a font/direction that actually contains the team's glyphs."""
    is_persian = _knockout_name_is_persian(name)
    direction = "rtl" if is_persian else "ltr"
    language = "fa" if is_persian else None
    for size in (22, 21, 20, 19, 18, 17, 16, 15, 14):
        font = _font(size, True) if is_persian else _latin_font(size, True)
        bbox_kwargs = {
            "font": font,
            "anchor": "rm",
            "direction": direction,
        }
        if language:
            bbox_kwargs["language"] = language
        bbox = draw.textbbox((0, 0), name, **bbox_kwargs)
        if bbox[2] - bbox[0] <= max(30, right - left):
            return font, direction, language
    font = _font(14, True) if is_persian else _latin_font(14, True)
    return font, direction, language


def _draw_knockout_match(draw, image, x, y, w, h, matchup):
    draw.rounded_rectangle(
        (x, y, x + w, y + h), radius=16, fill=CARD, outline=BORDER, width=2
    )

    home_name_raw, home_id = _knockout_match_team(matchup, "home")
    away_name_raw, away_id = _knockout_match_team(matchup, "away")
    raw_matchup = matchup.get("raw") if isinstance(matchup.get("raw"), dict) else {}
    raw_home = raw_matchup.get("home") if isinstance(raw_matchup.get("home"), dict) else {}
    raw_away = raw_matchup.get("away") if isinstance(raw_matchup.get("away"), dict) else {}

    home_placeholder = _is_placeholder_team(
        home_name_raw, home_id, bool(matchup.get("tbdTeam1", False)), raw_home
    )
    away_placeholder = _is_placeholder_team(
        away_name_raw, away_id, bool(matchup.get("tbdTeam2", False)), raw_away
    )

    home_name = _knockout_team_name(
        home_name_raw, home_id, bool(matchup.get("tbdTeam1", False)), raw_home
    )
    away_name = _knockout_team_name(
        away_name_raw, away_id, bool(matchup.get("tbdTeam2", False)), raw_away
    )

    # FotMob assigns numeric IDs to some bracket placeholders. The semantic
    # placeholder check must happen before _team_logo so those IDs never
    # trigger HTTP requests for nonexistent team logos.
    home_logo = None if home_placeholder else _team_logo(home_id)
    away_logo = None if away_placeholder else _team_logo(away_id)

    score, home_penalty, away_penalty = _knockout_match_score(matchup)
    # Keep the score/shootout block clearly separated from the team-name area.
    # The shootout suffix is wider than the normal score, so reserve a fixed
    # left-side column for the complete "score (penalty)" block.
    score_x = x + 28
    name_right = x + w - 22
    score_column_right = x + 112
    home_y = y + 30
    away_y = y + 94

    def team_row(yy, name, logo, score_value, penalty_value):
        logo_width = logo.width if logo else 0
        if logo:
            logo_x = name_right - logo_width
            image.alpha_composite(logo, (int(logo_x), int(yy - logo.height / 2)))
            text_right = logo_x - 10
        else:
            text_right = name_right

        text_left = score_column_right + 14
        font, name_direction, name_language = _fit_knockout_name(
            draw, name, text_right, text_left
        )
        name_kwargs = {
            "anchor": "rm",
            "fill": TEXT,
            "direction": name_direction,
        }
        if name_language:
            name_kwargs["language"] = name_language
        draw.text((text_right, yy), name, font=font, **name_kwargs)
        # Do not draw the parentheses with the Persian font: on some
        # Linux font builds they become tofu squares. Draw the numeric score
        # with the Persian font and the punctuation with a Latin font that
        # contains both ASCII parentheses.
        main_score = _persian_digits(score_value) if score_value is not None else "—"
        main_font = _font(25, True)
        _draw_text(
            draw, (score_x, yy),
            main_score,
            main_font,
            TEXT,
            "lm",
            "ltr",
        )

        if penalty_value is not None:
            main_bbox = draw.textbbox(
                (score_x, yy), main_score,
                font=main_font, anchor="lm",
                direction="ltr", language="fa",
            )
            cursor_x = main_bbox[2] + 6
            punct_font = _latin_font(25, True)
            penalty_font = _font(25, True)

            _draw_text(draw, (cursor_x, yy), "(", punct_font, TEXT, "lm", "ltr")
            paren_width = draw.textlength("(", font=punct_font)
            cursor_x += paren_width

            penalty_text = _persian_digits(penalty_value)
            _draw_text(
                draw, (cursor_x, yy),
                penalty_text,
                penalty_font,
                TEXT,
                "lm",
                "ltr",
            )
            penalty_bbox = draw.textbbox(
                (cursor_x, yy), penalty_text,
                font=penalty_font, anchor="lm",
                direction="ltr", language="fa",
            )
            cursor_x = penalty_bbox[2] + 4
            _draw_text(draw, (cursor_x, yy), ")", punct_font, TEXT, "lm", "ltr")

    team_row(home_y, home_name, home_logo, matchup.get("homeScore"), home_penalty)
    team_row(away_y, away_name, away_logo, matchup.get("awayScore"), away_penalty)

def _knockout_stage_key(stage: dict) -> int:
    """Return the canonical tournament order for a knockout round."""
    label = str(stage.get("stage") or "").strip()
    keys = {
        "پلی‌آف": 10,
        "یک‌شصت‌وچهارم نهایی": 20,
        "یک‌شانزدهم نهایی": 30,
        "یک‌هشتم نهایی": 40,
        "یک‌چهارم نهایی": 50,
        "نیمه‌نهایی": 60,
        "فینال": 70,
        "رده‌بندی": 80,
    }
    if label in keys:
        return keys[label]

    count = int(stage.get("participantCount") or 0)
    if count >= 64:
        return 20
    if count == 32:
        return 30
    if count == 16:
        return 40
    if count == 8:
        return 50
    if count == 4:
        return 60
    if count == 2:
        return 70
    return 0


def _knockout_next_stage(stage: dict) -> dict | None:
    """Create the next bracket stage when FotMob has not published it yet."""
    label = str(stage.get("stage") or "").strip()
    next_labels = {
        "پلی‌آف": "یک‌شانزدهم نهایی",
        "یک‌شصت‌وچهارم نهایی": "یک‌شانزدهم نهایی",
        "یک‌شانزدهم نهایی": "یک‌هشتم نهایی",
        "یک‌هشتم نهایی": "یک‌چهارم نهایی",
        "یک‌چهارم نهایی": "نیمه‌نهایی",
        "نیمه‌نهایی": "فینال",
    }
    next_label = next_labels.get(label)
    if not next_label:
        count = int(stage.get("participantCount") or 0)
        next_label = {
            64: "یک‌شانزدهم نهایی",
            32: "یک‌هشتم نهایی",
            16: "یک‌چهارم نهایی",
            8: "نیمه‌نهایی",
            4: "فینال",
        }.get(count)
    if not next_label:
        return None

    current_matchups = stage.get("matchups") or []
    next_count = max(1, (len(current_matchups) + 1) // 2)
    return {
        "stage": next_label,
        "participantCount": max(2, next_count * 2),
        "matchups": [
            {
                "number": i + 1,
                "homeTeamId": "",
                "awayTeamId": "",
                "homeTeam": "",
                "awayTeam": "",
                "homeScore": None,
                "awayScore": None,
                "winner": "",
                "bestOf": 1,
                "tbdTeam1": True,
                "tbdTeam2": True,
                "matches": [],
                "aggregatedResult": {},
                "aggregatedWinner": None,
                "aggregatedLoser": None,
                "penaltyScore": None,
                "raw": {},
            }
            for i in range(next_count)
        ],
        "raw": {},
        "placeholder": True,
    }


def _make_knockout_placeholder_stage(label: str, match_count: int, participant_count: int) -> dict:
    """Create a blank bracket stage when FotMob omits an earlier round."""
    return {
        "stage": label,
        "participantCount": participant_count,
        "matchups": [
            {
                "number": i + 1,
                "homeTeamId": "",
                "awayTeamId": "",
                "homeTeam": "",
                "awayTeam": "",
                "homeScore": None,
                "awayScore": None,
                "winner": "",
                "bestOf": 1,
                "tbdTeam1": True,
                "tbdTeam2": True,
                "matches": [],
                "aggregatedResult": {},
                "aggregatedWinner": None,
                "aggregatedLoser": None,
                "penaltyScore": None,
                "raw": {},
            }
            for i in range(match_count)
        ],
        "raw": {},
        "placeholder": True,
    }


def _ensure_full_knockout_bracket(rounds: list[dict]) -> list[dict]:
    """Keep all available past rounds and extend the tree through the final."""
    if not rounds:
        return []

    # Remove duplicate stages while preserving the first real FotMob version.
    unique: list[dict] = []
    seen_keys: set[tuple] = set()
    for item in rounds:
        key = (
            str(item.get("stage") or ""),
            tuple(
                (
                    str(m.get("homeTeamId") or ""),
                    str(m.get("awayTeamId") or ""),
                    int(m.get("number") or 0),
                )
                for m in item.get("matchups") or []
            ),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique.append(item)

    unique.sort(key=lambda item: (_knockout_stage_key(item), len(unique)))
    # The final must be the right-most column. Add only genuinely missing
    # future rounds; never replace or discard rounds already returned by FotMob.
    for _ in range(8):
        last = unique[-1]
        if str(last.get("stage") or "") == "فینال":
            break
        nxt = _knockout_next_stage(last)
        if not nxt:
            break
        if any(str(item.get("stage") or "") == nxt["stage"] for item in unique):
            break
        unique.append(nxt)

    return unique


def _knockout_stage_is_active(round_data: dict) -> bool:
    """Detect a currently live/ongoing round from FotMob payloads."""
    def walk(value: Any) -> bool:
        if isinstance(value, dict):
            for key in ("isLive", "is_live", "ongoing", "inProgress", "in_progress", "live"):
                if value.get(key) is True:
                    return True
            for key in ("status", "matchStatus", "state"):
                raw = value.get(key)
                if isinstance(raw, str) and raw.casefold() in {
                    "live", "ongoing", "in progress", "inprogress", "started",
                    "1h", "2h", "et", "pen",
                }:
                    return True
            return any(
                walk(v) for v in value.values()
                if isinstance(v, (dict, list))
            )
        if isinstance(value, list):
            return any(walk(v) for v in value if isinstance(v, (dict, list)))
        return False

    return walk(round_data.get("raw", {})) or any(
        walk(m.get("raw", {})) for m in round_data.get("matchups", [])
    )


def render_knockout_standings(data: dict, day, output: Path, stage: dict | None = None) -> None:
    """Render a compact professional bracket that always reaches the final."""
    source_rounds = list(data.get("knockoutRounds") or [])
    if stage is not None and not source_rounds:
        source_rounds = [stage]
    elif stage is not None:
        # A stage argument identifies the current stage, but the poster should
        # still contain every published earlier stage plus all future columns.
        source_rounds = source_rounds[:]
    valid_rounds = [
        item for item in source_rounds
        if isinstance(item, dict) and item.get("matchups")
    ]

    # Domestic cups are intentionally represented from the Round of 16 onward.
    # FotMob can expose earlier qualifying/entry rounds (especially the FA Cup),
    # but those rounds are not part of the poster scope and can contain dozens
    # of matches. Keeping them would make the first bracket column enormous.
    domestic_cup_ids = {"132", "133", "141", "138", "134", "209"}
    if str(data.get("competitionId") or "") in domestic_cup_ids:
        knockout_from_r16 = [
            item for item in valid_rounds
            if _knockout_stage_key(item) >= 40
        ]
        if knockout_from_r16:
            valid_rounds = knockout_from_r16

        # FotMob's EFL Cup (133) currently omits Round Five from the
        # league knockout payload and exposes only QF -> SF -> Final.
        # Round Five is the 16-team/8-match stage, i.e. our Round of 16.
        # Keep the poster scope consistent by inserting that missing stage
        # only for EFL Cup; never invent it for other competitions.
        if str(data.get("competitionId") or "") == "133":
            has_r16 = any(_knockout_stage_key(item) == 40 for item in valid_rounds)
            if not has_r16 and valid_rounds:
                valid_rounds.insert(
                    0,
                    _make_knockout_placeholder_stage(
                        "یک‌هشتم نهایی",
                        match_count=8,
                        participant_count=16,
                    ),
                )

    rounds = _ensure_full_knockout_bracket(valid_rounds)
    if not rounds:
        raise ValueError("Cannot render knockout standings without matchups.")

    competition_id = str(data.get("competitionId") or "")
    competition = _competition_display_name(
        competition_id, str(data.get("competitionName") or "")
    )
    season = str(data.get("season") or "فصل جاری")

    # The first knockout round defines the vertical extent of the bracket.
    # It must occupy the full available poster height regardless of whether the
    # competition starts at the round of 16, quarterfinals, or a later stage.
    # Later rounds are then placed at the midpoint of the matches feeding them.
    cols = len(rounds)
    side = 42
    gap = 22
    card_h = 140
    usable_width = WIDTH - 2 * side - gap * (cols - 1)
    # Keep every knockout column inside the 1600px canvas; a fixed 245px minimum overflowed on long brackets.
    card_w = max(185, min(330, usable_width // cols))

    # Center the complete bracket as a single unit. When the competition has
    # fewer knockout stages (for example QF -> SF -> Final), the unused
    # horizontal space is therefore split equally between the left and right
    # sides instead of leaving the first round flush against the left edge.
    bracket_width = cols * card_w + gap * (cols - 1)
    side = max(42, (WIDTH - bracket_width) / 2)

    first_count = max(1, len(rounds[0].get("matchups") or []))
    body_top = HEADER_H + 70
    bottom_margin = 70
    top_center = body_top + card_h / 2
    bottom_center = max(
        top_center,
        1600 - bottom_margin - card_h / 2,
    )

    # A large first round (for example 16 matches) needs a taller poster so
    # the cards never overlap. For smaller first rounds, keep the standard
    # poster height and distribute those matches from top to bottom. This
    # means a 4-match quarterfinal bracket fills the same vertical canvas that
    # an 8-match round-of-16 bracket fills, instead of leaving the lower half
    # empty.
    min_step = card_h + 46
    required_height = int(
        body_top
        + card_h
        + bottom_margin
        + max(0, first_count - 1) * min_step
    )
    height = max(1600, required_height)
    bottom_center = height - bottom_margin - card_h / 2

    if first_count == 1:
        first_centers = [(top_center + bottom_center) / 2]
    else:
        first_step = (bottom_center - top_center) / (first_count - 1)
        first_centers = [
            top_center + i * first_step
            for i in range(first_count)
        ]

    all_centers: list[list[float]] = [first_centers]
    for ri in range(1, len(rounds)):
        previous = all_centers[-1]
        previous_count = len(previous)
        current_count = max(1, len(rounds[ri].get("matchups") or []))
        centers: list[float] = []

        # Map each next-round matchup to the contiguous source-match range
        # that feeds it. For the normal knockout shape this is exactly
        # (0,1), (2,3), ... and gives the desired midpoint geometry. The
        # proportional mapping also remains safe for unusual FotMob counts.
        for i in range(current_count):
            start = (i * previous_count) // current_count
            end = ((i + 1) * previous_count) // current_count - 1
            start = min(start, previous_count - 1)
            end = min(max(end, start), previous_count - 1)
            centers.append(
                (previous[start] + previous[end]) / 2
            )

        all_centers.append(centers)

    image = Image.new("RGBA", (WIDTH, height), BG + (255,))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (MARGIN_X, 34, WIDTH - MARGIN_X, 42), radius=4, fill=ACCENT
    )
    draw.line(
        (MARGIN_X, HEADER_H - 22, WIDTH - MARGIN_X, HEADER_H - 22),
        fill=BORDER, width=2
    )
    _draw_standings_title(
        draw, WIDTH - MARGIN_X, 108, f"نمودار حذفی {competition}"
    )
    _draw_text(
        draw, (MARGIN_X, 108),
        season.replace("2026/2027", "2026/27"),
        _latin_font(27, True), MUTED, "lm", "ltr"
    )

    positions: list[list[tuple[float, float, float, float]]] = []
    for ri, round_data in enumerate(rounds):
        x = side + ri * (card_w + gap)
        stage_name = str(round_data.get("stage") or "مرحله حذفی")
        if _knockout_stage_is_active(round_data):
            stage_top = body_top - 52
            stage_bottom = all_centers[ri][-1] + card_h / 2 + 26
            draw.rounded_rectangle(
                (x - 10, stage_top, x + card_w + 10, stage_bottom),
                radius=22, fill=ACTIVE_STAGE_BG, outline=BORDER, width=1
            )
        _draw_text(
            draw,
            (x + card_w / 2, body_top - 16),
            stage_name,
            _font(_knockout_stage_font_size(stage_name), True),
            TEXT,
            "ms",
        )

        ordered_matchups = sorted(
            round_data["matchups"],
            key=lambda m: int(m.get("number") or 0),
        )
        col_positions: list[tuple[float, float, float, float]] = []
        for mi, matchup in enumerate(ordered_matchups):
            center = all_centers[ri][mi]
            y = center - card_h / 2
            _draw_knockout_match(
                draw, image, x, y, card_w, card_h, matchup
            )
            col_positions.append((x, y, card_w, card_h))
        positions.append(col_positions)

    # Connect each source pair to the exact next-round card. The coordinates
    # are derived only from bracket order, never from score or winner fields.
    for ri in range(len(positions) - 1):
        current = positions[ri]
        nxt = positions[ri + 1]
        if not current or not nxt:
            continue
        for ni, target in enumerate(nxt):
            source_a = current[min(ni * 2, len(current) - 1)]
            source_b = current[min(ni * 2 + 1, len(current) - 1)]
            sx = source_a[0] + source_a[2]
            sy1 = source_a[1] + source_a[3] / 2
            sy2 = source_b[1] + source_b[3] / 2
            tx = target[0]
            ty = target[1] + target[3] / 2
            elbow = sx + gap / 2
            draw.line((sx, sy1, elbow, sy1), fill=BORDER, width=2)
            draw.line((sx, sy2, elbow, sy2), fill=BORDER, width=2)
            draw.line((elbow, sy1, elbow, sy2), fill=BORDER, width=2)
            draw.line((elbow, ty, tx, ty), fill=BORDER, width=2)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output, "PNG", optimize=True)


def render_standings(data: dict, day, output: Path, title_suffix: str | None = None) -> None:
    if not features.check("raqm"):
        raise RuntimeError("Pillow was built without libraqm; Persian RTL rendering cannot be trusted.")

    tables = data.get("tables") or []
    if not tables:
        raise ValueError("Cannot render standings without tables.")

    # Grouped competitions are rendered vertically, one complete table
    # after another. This preserves the original poster structure and
    # guarantees that every group and every auxiliary table remains visible.
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

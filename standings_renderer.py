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
                _draw_text(draw, (logo_x - 10, row_y + row_h / 2),
                           team_name, _font(24, True), TEXT, "rm")

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
                _draw_text(draw, (cx - 8, yy), team_name,
                           _font(23, True), TEXT, "rm")
                points = row.get("points")
                if points is not None:
                    _draw_text(draw, (cx - col_w / 2 + 86, yy),
                               _persian_digits(points), _font(24, True),
                               TEXT, "lm", "ltr")

    output.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output, "PNG", optimize=True)



def _knockout_team_name(name: str, team_id: str, tbd: bool) -> str:
    if tbd or not str(name or "").strip():
        return "تعیین نشده"
    return _team_name({"id": team_id, "name": name})


def _knockout_stage_font_size(stage: str) -> int:
    return 31 if len(stage) <= 16 else 27


def _knockout_match_score(matchup: dict) -> tuple[str, str | None]:
    """Return the displayed match/aggregate score and shootout score."""
    home = matchup.get("homeScore")
    away = matchup.get("awayScore")
    if home is None or away is None:
        return "—", None
    score = f"{_persian_digits(home)} - {_persian_digits(away)}"
    penalty = matchup.get("penaltyScore")
    if isinstance(penalty, dict) and penalty.get("home") is not None and penalty.get("away") is not None:
        penalty_text = f"({_persian_digits(penalty['home'])}) - ({_persian_digits(penalty['away'])})"
    else:
        penalty_text = None
    return score, penalty_text


def _draw_knockout_match(draw, image, x, y, w, h, matchup):
    draw.rounded_rectangle((x, y, x + w, y + h), radius=16, fill=CARD, outline=BORDER, width=2)
    number = _persian_digits(matchup.get("number", ""))
    _draw_text(draw, (x + w - 18, y + 18), f"#{number}", _latin_font(20, True), MUTED, "ra", "ltr")

    home_id = str(matchup.get("homeTeamId") or "")
    away_id = str(matchup.get("awayTeamId") or "")
    home_name = _knockout_team_name(matchup.get("homeTeam", ""), home_id, matchup.get("tbdTeam1", False))
    away_name = _knockout_team_name(matchup.get("awayTeam", ""), away_id, matchup.get("tbdTeam2", False))
    home_logo = _team_logo(home_id)
    away_logo = _team_logo(away_id)

    score, penalty = _knockout_match_score(matchup)
    score_x = x + 48
    name_right = x + w - 24
    row_h = 48
    home_y = y + 30
    away_y = y + 78

    def team_row(yy, name, logo, score_value):
        if logo:
            image.alpha_composite(logo, (int(name_right - logo.width - 12), int(yy - logo.height / 2)))
            text_right = name_right - logo.width - 22
        else:
            text_right = name_right
        _draw_text(draw, (text_right, yy), name, _font(22, True), TEXT, "rm")
        _draw_text(draw, (score_x, yy), _persian_digits(score_value) if score_value is not None else "—", _font(28, True), TEXT, "lm", "ltr")

    team_row(home_y, home_name, home_logo, matchup.get("homeScore"))
    team_row(away_y, away_name, away_logo, matchup.get("awayScore"))

    if penalty:
        _draw_text(draw, (x + w / 2, y + h - 11), f"پنالتی {penalty}", _font(18, True), MUTED, "ms")


def render_knockout_standings(data: dict, day, output: Path, stage: dict | None = None) -> None:
    """Render knockout data as a real bracket/tree, preserving FotMob home/away scores."""
    rounds = [stage] if stage is not None else list(data.get("knockoutRounds") or [])
    rounds = [item for item in rounds if isinstance(item, dict) and item.get("matchups")]
    if not rounds:
        raise ValueError("Cannot render knockout standings without matchups.")

    competition_id = str(data.get("competitionId") or "")
    competition = _competition_display_name(competition_id, str(data.get("competitionName") or ""))
    season = str(data.get("season") or "فصل جاری")

    # A bracket is read from the earliest round toward the final.  Each round
    # gets its own column and matchup boxes are vertically centred between the
    # boxes of the next round, with connector lines showing progression.
    # Keep FotMob's round order. Sorting by participantCount is unsafe because
    # playoff and round-of-16 stages can share the same participant count.
    cols = len(rounds)
    gap = 34
    side = 54
    card_w = max(250, min(300, (WIDTH - 2 * side - gap * (cols - 1)) // cols))
    card_h = 116
    header_h = HEADER_H
    body_top = header_h + 28
    body_bottom = body_top + max(760, (2 ** max(0, cols - 1)) * card_h)
    height = max(1600, body_bottom + 90)

    image = Image.new("RGBA", (WIDTH, height), BG + (255,))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((MARGIN_X, 34, WIDTH - MARGIN_X, 42), radius=4, fill=ACCENT)
    draw.line((MARGIN_X, HEADER_H - 22, WIDTH - MARGIN_X, HEADER_H - 22), fill=BORDER, width=2)
    _draw_standings_title(draw, WIDTH - MARGIN_X, 108, f"نمودار حذفی {competition}")
    _draw_text(draw, (MARGIN_X, 108), season.replace("2026/2027", "2026/27"), _latin_font(27, True), MUTED, "lm", "ltr")

    positions = []
    for ri, round_data in enumerate(rounds):
        x = side + ri * (card_w + gap)
        count = len(round_data["matchups"])
        stage_name = str(round_data.get("stage") or "مرحله حذفی")
        _draw_text(draw, (x + card_w / 2, body_top - 8), stage_name, _font(_knockout_stage_font_size(stage_name), True), TEXT, "ms")
        spacing = (body_bottom - body_top - count * card_h) / max(1, count - 1) if count > 1 else 0
        col_positions = []
        ordered_matchups = sorted(round_data["matchups"], key=lambda m: int(m.get("number") or 0))
        for mi, matchup in enumerate(ordered_matchups):
            y = body_top + mi * (card_h + spacing)
            _draw_knockout_match(draw, image, x, y, card_w, card_h, matchup)
            col_positions.append((x, y, card_w, card_h))
        positions.append(col_positions)

    # Connect each pair of matches to the next-round matchup. The draw order
    # is the stable bracket key supplied by FotMob, so scores never determine
    # visual ordering and therefore can never swap teams.
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

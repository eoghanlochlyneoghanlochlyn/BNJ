from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1600
MARGIN = 70
ROW_HEIGHT = 72
MIN_HEIGHT = 500


def _font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _team_name(value: object) -> str:
    if isinstance(value, dict):
        return str(
            value.get("name")
            or value.get("longName")
            or value.get("shortName")
            or "—"
        )
    return str(value or "—")


def _competition_name(match: dict) -> str:
    return str(
        match.get("competition")
        or match.get("competitionName")
        or match.get("league")
        or "نامشخص"
    )


def _kickoff(match: dict) -> str:
    start = match.get("startIran")
    if not start:
        return "—"
    try:
        return datetime.fromisoformat(start).strftime("%H:%M")
    except ValueError:
        return "—"


def render_fixtures(matches: list[dict], day: date, output: Path) -> None:
    if not matches:
        raise ValueError("Cannot render a fixture report with zero matches.")

    groups: dict[str, list[dict]] = {}
    for match in matches:
        groups.setdefault(_competition_name(match), []).append(match)

    rows = sum(len(items) + 1 for items in groups.values())
    height = max(MIN_HEIGHT, 190 + rows * ROW_HEIGHT + len(groups) * 30)

    image = Image.new("RGB", (WIDTH, height), "white")
    draw = ImageDraw.Draw(image)

    title_font = _font(52, True)
    subtitle_font = _font(22)
    competition_font = _font(32, True)
    match_font = _font(26)

    draw.text(
        (WIDTH - MARGIN, 55),
        "مسابقات امروز",
        font=title_font,
        anchor="ra",
        fill="black",
    )
    draw.text(
        (WIDTH - MARGIN, 120),
        day.isoformat(),
        font=subtitle_font,
        anchor="ra",
        fill="black",
    )

    y = 190
    for competition, items in groups.items():
        draw.text(
            (WIDTH - MARGIN, y),
            competition,
            font=competition_font,
            anchor="ra",
            fill="black",
        )
        y += ROW_HEIGHT

        for match in items:
            home = _team_name(match.get("home"))
            away = _team_name(match.get("away"))
            draw.text(
                (WIDTH - MARGIN, y),
                f"{home}  -  {away}",
                font=match_font,
                anchor="ra",
                fill="black",
            )
            draw.text(
                (MARGIN, y),
                _kickoff(match),
                font=match_font,
                anchor="la",
                fill="black",
            )
            y += ROW_HEIGHT

        y += 30

    # Hard safety check: a report must contain visible non-white pixels.
    if image.getbbox() is None:
        raise RuntimeError("Renderer produced an empty image.")
    if not any(pixel != (255, 255, 255) for pixel in image.getdata()):
        raise RuntimeError("Renderer produced a completely white image.")

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "PNG", optimize=True)

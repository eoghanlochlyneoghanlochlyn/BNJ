from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1600
MARGIN = 70
ROW_HEIGHT = 72


def _font(size: int, bold: bool = False):
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return ImageFont.truetype(path, size) if Path(path).exists() else ImageFont.load_default()


def render_fixtures(matches: list[dict], day: date, output: Path) -> None:
    groups: dict[str, list[dict]] = {}
    for match in matches:
        groups.setdefault(match.get("competition") or "نامشخص", []).append(match)

    rows = sum(len(items) + 1 for items in groups.values())
    height = max(500, 190 + rows * ROW_HEIGHT + len(groups) * 30)

    image = Image.new("RGB", (WIDTH, height), "white")
    draw = ImageDraw.Draw(image)

    draw.text((WIDTH - MARGIN, 55), "مسابقات امروز", font=_font(52, True), anchor="ra")
    draw.text((WIDTH - MARGIN, 120), day.isoformat(), font=_font(22), anchor="ra")

    y = 190
    for competition, items in groups.items():
        draw.text((WIDTH - MARGIN, y), competition, font=_font(32, True), anchor="ra")
        y += ROW_HEIGHT
        for match in items:
            time_text = ""
            start = match.get("startIran")
            if start:
                try:
                    time_text = datetime.fromisoformat(start).strftime("%H:%M")
                except ValueError:
                    pass
            home = match.get("home") or "—"
            away = match.get("away") or "—"
            draw.text((WIDTH - MARGIN, y), f"{home}  -  {away}", font=_font(26), anchor="ra")
            draw.text((MARGIN, y), time_text, font=_font(26), anchor="la")
            y += ROW_HEIGHT
        y += 30

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "PNG", optimize=True)

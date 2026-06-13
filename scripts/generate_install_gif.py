#!/usr/bin/env python3
"""Generate the README terminal quick-start animation."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "install.gif"
WIDTH, HEIGHT = 900, 360
FONT_PATH = "/System/Library/Fonts/Menlo.ttc"
FONT = ImageFont.truetype(FONT_PATH, 22)
SMALL_FONT = ImageFont.truetype(FONT_PATH, 17)

COMMANDS = [
    "$ git clone https://github.com/96528025/publishsafe.git",
    "$ cd publishsafe",
    "$ ./scripts/start.sh",
]
RESULTS = [
    "Cloning into 'publishsafe'...",
    "",
    "PublishSafe is starting...",
    "Open http://localhost:5173",
]


def draw_terminal(lines: list[str], cursor: bool = False) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#0d1117")
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((18, 18, WIDTH - 18, HEIGHT - 18), 14, fill="#161b22")
    draw.rectangle((18, 18, WIDTH - 18, 64), fill="#21262d")
    for x, color in ((43, "#ff5f56"), (67, "#ffbd2e"), (91, "#27c93f")):
        draw.ellipse((x - 7, 34, x + 7, 48), fill=color)
    draw.text((WIDTH // 2 - 55, 31), "PublishSafe", font=SMALL_FONT, fill="#8b949e")

    y = 91
    for line in lines:
        color = "#7ee787" if line.startswith("$") else "#c9d1d9"
        draw.text((48, y), line, font=FONT, fill=color)
        y += 43

    if cursor:
        cursor_x = 48 + int(draw.textlength(lines[-1], font=FONT))
        draw.rectangle((cursor_x + 3, y - 39, cursor_x + 14, y - 12), fill="#c9d1d9")
    return image


def main() -> None:
    frames: list[Image.Image] = []
    durations: list[int] = []
    visible: list[str] = []

    for command_index, command in enumerate(COMMANDS):
        for length in range(1, len(command) + 1, 2):
            frames.append(draw_terminal(visible + [command[:length]], cursor=True))
            durations.append(35)
        visible.append(command)
        frames.append(draw_terminal(visible, cursor=True))
        durations.append(450)

        if command_index == 0:
            visible.append(RESULTS[0])
        elif command_index == 2:
            visible.extend(RESULTS[2:])

    frames.append(draw_terminal(visible))
    durations.append(2500)
    frames[0].save(
        OUTPUT,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    print(f"Generated {OUTPUT}")


if __name__ == "__main__":
    main()

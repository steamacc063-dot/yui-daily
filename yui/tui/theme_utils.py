"""Theme name normalization, import, and resolution helpers."""

from __future__ import annotations

import re
import shutil
from collections.abc import Iterable
from pathlib import Path

from textual.color import Color
from textual.theme import Theme

from yui.config import CONFIG_DIR

DEFAULT_THEME = "textual-dark"
IMPORTED_THEME_DIR = CONFIG_DIR / "themes"

_THEME_ALIASES = {
    "dark": "textual-dark",
    "light": "textual-light",
    "default": DEFAULT_THEME,
}
_HEX_RE = re.compile(r"^(?:#|0x)?([0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def normalize_theme_name(value: str) -> str:
    """Normalize Ghostty-style theme names to Textual theme ids."""
    cleaned = value.strip().strip("'\"").replace("_", "-")
    if "/" in cleaned:
        cleaned = cleaned.rsplit("/", maxsplit=1)[-1]
    cleaned = "-".join(part for part in cleaned.lower().split())
    if not cleaned:
        return DEFAULT_THEME
    return _THEME_ALIASES.get(cleaned, cleaned)


def resolve_theme_name(requested: str, available_themes: Iterable[str]) -> str:
    """Resolve a requested theme name to an installed Textual theme."""
    normalized = normalize_theme_name(requested)
    available = {name.lower(): name for name in available_themes}
    return available.get(normalized, DEFAULT_THEME)


def import_ghostty_theme_file(
    source: str | Path,
    existing_names: Iterable[str],
) -> tuple[str, Theme]:
    """Import a Ghostty theme .txt file into ~/.yui/themes and build a Textual theme."""
    source_path = Path(source).expanduser().resolve()
    if not source_path.exists() or not source_path.is_file():
        raise ValueError(f"Theme file not found: {source_path}")

    raw = source_path.read_text(encoding="utf-8")
    existing = {name.lower() for name in existing_names}
    base = normalize_theme_name(source_path.stem) or "ghostty-theme"
    theme_name = _unique_name(base, existing)
    theme = parse_ghostty_theme_text(raw, theme_name)

    IMPORTED_THEME_DIR.mkdir(parents=True, exist_ok=True)
    destination = IMPORTED_THEME_DIR / f"{theme_name}.txt"
    shutil.copy2(source_path, destination)
    return theme_name, theme


def load_imported_theme(theme_name: str) -> Theme:
    """Load an imported Ghostty theme by name from ~/.yui/themes."""
    normalized = normalize_theme_name(theme_name)
    file_path = IMPORTED_THEME_DIR / f"{normalized}.txt"
    if not file_path.exists():
        raise ValueError(f"Imported theme file missing: {file_path}")
    raw = file_path.read_text(encoding="utf-8")
    return parse_ghostty_theme_text(raw, normalized)


def parse_ghostty_theme_text(text: str, theme_name: str) -> Theme:
    """Parse Ghostty theme text into a Textual Theme."""
    values: dict[str, str] = {}
    palette: dict[int, str] = {}

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        raw_key, raw_value = stripped.split("=", maxsplit=1)
        key = raw_key.strip().lower()
        value = _clean_value(raw_value)

        if key == "palette":
            if "=" in value:
                slot_text, color_text = value.split("=", maxsplit=1)
                try:
                    slot = int(slot_text.strip())
                except ValueError:
                    continue
                color = _normalize_color(color_text)
                if color:
                    palette[slot] = color
            continue

        if key.startswith("palette") and key[7:].isdigit():
            slot = int(key[7:])
            color = _normalize_color(value)
            if color:
                palette[slot] = color
            continue

        values[key] = value

    background = _normalize_color(values.get("background")) or "#121212"
    foreground = _normalize_color(values.get("foreground")) or palette.get(7) or "#E0E0E0"
    cursor = _normalize_color(values.get("cursor-color")) or palette.get(4) or foreground
    warning = palette.get(3) or "#FFA62B"
    error = palette.get(1) or "#BA3C5B"
    success = palette.get(2) or "#4EBF71"
    accent = palette.get(5) or cursor
    secondary = palette.get(6) or accent

    bg_color = Color.parse(background)
    is_dark = bg_color.brightness < 0.5
    if is_dark:
        surface = bg_color.lighten(0.08).hex
        panel = bg_color.lighten(0.14).hex
    else:
        surface = bg_color.darken(0.08).hex
        panel = bg_color.darken(0.14).hex

    return Theme(
        name=normalize_theme_name(theme_name),
        primary=cursor,
        secondary=secondary,
        warning=warning,
        error=error,
        success=success,
        accent=accent,
        foreground=foreground,
        background=background,
        surface=surface,
        panel=panel,
        dark=is_dark,
    )


def _clean_value(value: str) -> str:
    cleaned = value.strip().strip("'\"")
    if " #" in cleaned:
        cleaned = cleaned.split(" #", maxsplit=1)[0].rstrip()
    return cleaned


def _normalize_color(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip().strip("'\"")
    match = _HEX_RE.match(raw)
    if match:
        return f"#{match.group(1)}"
    try:
        return Color.parse(raw).hex
    except Exception:
        return None


def _unique_name(base: str, existing: set[str]) -> str:
    if base.lower() not in existing:
        return base
    idx = 2
    while f"{base}-{idx}".lower() in existing:
        idx += 1
    return f"{base}-{idx}"

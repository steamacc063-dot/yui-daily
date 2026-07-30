"""Entry point for ``python -m yui`` and the ``yui`` command."""

from __future__ import annotations

import argparse
from pathlib import Path

from yui.config import CONFIG_FILE, NexusConfig


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="yui",
        description="Yui Daily — a local-first agenda and task system",
    )
    parser.add_argument(
        "--vault",
        type=Path,
        help="Store tasks in this Obsidian vault (default: ~/.yui/vault)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset Yui's configuration; task Markdown files are never deleted",
    )
    args = parser.parse_args()

    if args.reset and CONFIG_FILE.exists():
        CONFIG_FILE.unlink()

    if args.vault:
        config = NexusConfig.load()
        config.obsidian_vault_path = str(args.vault.expanduser().resolve())
        config.save()

    from yui.tui.app import YuiApp

    YuiApp(vault_path=args.vault).run()


if __name__ == "__main__":
    main()

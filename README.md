# 結 Yui Daily

**A calm, local-first daily agenda and to-do system for the terminal.**

Yui turns a plain Markdown folder into a focused day planner. Capture tasks in
seconds, see overdue work beside today's timeline, and keep every change in
human-readable files that also work as an Obsidian vault.

```text
┌─ 結 YUI / DAILY SYSTEM ───────── THURSDAY · 30 JULY 2026 ── ● LOCAL ─┐
│ PLAN              │ DAILY AGENDA                       │ DAILY PULSE  │
│ T  TODAY  04      │ Thursday, July 30                 │ ██████░░ 60% │
│ >  TOMORROW  02   │ 3 open · make room for one day   │ 3 of 5 done  │
│ U  UPCOMING  07   │                                    │              │
│ I  INBOX  03      │ Add a task… @14:30 /30m #work    │ ON DECK      │
│ C  COMPLETED      │                                    │ Review brief │
│                   │ MORNING                            │ 14:30 · 30m  │
│ AREAS             │  09:00  ●  Plan the day           │ WORK · HIGH  │
│  · PERSONAL       │  10:30  ○  Draft first section    │              │
│  · WORK           │                                    │ SPACE finish │
│  · STUDIO         │ AFTERNOON                          │ P priority   │
│                   │  14:30  ○  Review roadmap         │ M tomorrow   │
└───────────────────┴────────────────────────────────────┴──────────────┘
```

## What it does

- **Today:** overdue and scheduled work in one timeline.
- **Inbox:** fast capture for tasks that still need a date.
- **Tomorrow and Upcoming:** plan forward without opening a calendar maze.
- **Completed:** a durable record of finished work.
- **Daily pulse:** completion progress and planned time at a glance.
- **Local persistence:** one Markdown note per task, with YAML frontmatter.
- **Offline by default:** no account, API key, agent, or network connection.

Existing Yui task notes remain readable. Older agent, channel, memory, and
session folders are left untouched and are no longer loaded into the main UI.

## Install and run

```bash
git clone https://github.com/steamacc063-dot/yui-daily.git
cd yui-daily
python3 -m pip install -e .
yui
```

Prefer a packaged download? Visit the minimal download page at
[steamacc063-dot.github.io/yui-daily](https://steamacc063-dot.github.io/yui-daily/).

Yui creates `~/.yui/vault` on first launch. To use another Obsidian vault:

```bash
yui --vault /path/to/your-vault
```

## Quick capture syntax

Press `N`, type the title, add any optional tokens, and press Enter.

```text
Review roadmap @14:30 /30m #work !high
Call Mara tomorrow @16:00 /20m #personal
Submit proposal ~2026-08-03 #studio !critical
```

| Token | Meaning |
|---|---|
| `@14:30` | Scheduled time |
| `/30m` | Estimated duration |
| `#work` | Area |
| `!high` | Priority: low, medium, high, or critical |
| `today` / `tomorrow` | Relative date |
| `~2026-08-03` | Exact date |

Plain text stays in the title. In Inbox, captures remain undated unless a date
token is supplied.

## Keyboard map

| Key | Action |
|---|---|
| `N` | Focus quick capture |
| `↑` / `↓` or `J` / `K` | Select a task |
| `Space` | Complete or reopen |
| `P` | Cycle priority |
| `M` | Move selected task to tomorrow |
| `E` | Edit task details and notes |
| `X` | Delete after confirmation |
| `T` | Today |
| `I` | Inbox |
| `U` | Upcoming |
| `C` | Completed |
| `[` / `]` | Previous / next day |
| `F1` | Show keyboard help |
| `Esc` | Quit |

## Data format

Tasks live in `tasks/<id>.md`:

```markdown
---
id: a1b2c3d4
title: Review roadmap
status: todo
priority: high
due_date: '2026-07-30'
scheduled_time: '14:30'
duration_minutes: 30
area: work
---
# ○ Review roadmap
```

The UI escapes task content before rendering it, and task fields are validated
at the storage boundary.

## Development

```bash
pytest -q
ruff check yui tests
```

Requires Python 3.11+ and uses [Textual](https://textual.textualize.io/) for the
terminal interface.

"""Productivity-domain tests for Yui's agenda and task workflow."""

from __future__ import annotations

from datetime import date, time
from pathlib import Path

import pytest

from yui.obsidian.tasks import TaskTracker
from yui.obsidian.vault import ObsidianVault
from yui.productivity import parse_quick_task


def make_tracker(tmp_path: Path) -> TaskTracker:
    vault = ObsidianVault(tmp_path)
    vault.ensure_structure()
    return TaskTracker(vault)


def test_quick_add_parses_time_duration_area_and_priority() -> None:
    draft = parse_quick_task(
        "Write launch brief @09:30 /45m #work !high",
        default_date=date(2026, 7, 30),
    )

    assert draft.title == "Write launch brief"
    assert draft.due_date == date(2026, 7, 30)
    assert draft.scheduled_time == time(9, 30)
    assert draft.duration_minutes == 45
    assert draft.area == "work"
    assert draft.priority == "high"


def test_quick_add_understands_tomorrow_and_rejects_empty_titles() -> None:
    draft = parse_quick_task(
        "Call Mara tomorrow @16:00",
        default_date=date(2026, 7, 30),
    )

    assert draft.title == "Call Mara"
    assert draft.due_date == date(2026, 7, 31)
    assert draft.scheduled_time == time(16, 0)

    with pytest.raises(ValueError, match="title"):
        parse_quick_task("@09:00 /30m", default_date=date(2026, 7, 30))


def test_task_round_trip_preserves_agenda_fields(tmp_path: Path) -> None:
    tracker = make_tracker(tmp_path)
    task = tracker.create(
        "Deep work",
        description="Draft the first two sections.",
        priority="high",
        tags=["writing"],
        due_date=date(2026, 7, 30),
        scheduled_time=time(10, 15),
        duration_minutes=75,
        area="studio",
    )

    restored = tracker.get(task.id)

    assert restored is not None
    assert restored.title == "Deep work"
    assert restored.description == "Draft the first two sections."
    assert restored.due_date == date(2026, 7, 30)
    assert restored.scheduled_time == time(10, 15)
    assert restored.duration_minutes == 75
    assert restored.area == "studio"


def test_agenda_orders_overdue_then_scheduled_then_anytime(tmp_path: Path) -> None:
    tracker = make_tracker(tmp_path)
    tracker.create("Anytime", due_date=date(2026, 7, 30))
    tracker.create(
        "Afternoon",
        due_date=date(2026, 7, 30),
        scheduled_time=time(14, 0),
    )
    tracker.create(
        "Morning",
        due_date=date(2026, 7, 30),
        scheduled_time=time(9, 0),
    )
    tracker.create("Overdue", due_date=date(2026, 7, 29), priority="critical")
    tracker.create("Old and done", due_date=date(2026, 7, 28), status="done")

    agenda = tracker.agenda(date(2026, 7, 30), include_overdue=True)

    assert [task.title for task in agenda] == [
        "Overdue",
        "Morning",
        "Afternoon",
        "Anytime",
    ]


def test_completion_and_daily_summary_are_persisted(tmp_path: Path) -> None:
    tracker = make_tracker(tmp_path)
    first = tracker.create(
        "Plan the day",
        due_date=date(2026, 7, 30),
        duration_minutes=15,
    )
    tracker.create(
        "Build the prototype",
        due_date=date(2026, 7, 30),
        duration_minutes=90,
    )

    completed = tracker.set_completed(first.id, completed=True)
    summary = tracker.daily_summary(date(2026, 7, 30))

    assert completed is not None
    assert completed.status == "done"
    assert completed.completed_at is not None
    assert summary == {
        "total": 2,
        "completed": 1,
        "remaining": 1,
        "planned_minutes": 105,
        "completion_percent": 50,
    }

    reopened = tracker.set_completed(first.id, completed=False)
    assert reopened is not None
    assert reopened.status == "todo"
    assert reopened.completed_at is None


def test_task_update_validates_fields_and_keeps_existing_values(tmp_path: Path) -> None:
    tracker = make_tracker(tmp_path)
    task = tracker.create(
        "Original",
        description="Keep this note",
        due_date=date(2026, 7, 30),
    )

    updated = tracker.update(
        task.id,
        title="Revised",
        scheduled_time=time(13, 45),
        duration_minutes=25,
    )

    assert updated is not None
    assert updated.title == "Revised"
    assert updated.description == "Keep this note"
    assert updated.scheduled_time == time(13, 45)
    assert updated.duration_minutes == 25

    with pytest.raises(ValueError, match="priority"):
        tracker.update(task.id, priority="impossible")

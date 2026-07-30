"""Regression tests for persisted datetime handling and task round-trips."""

from __future__ import annotations

from pathlib import Path

from yui.obsidian.memory import MemoryStore
from yui.obsidian.tasks import TaskTracker
from yui.obsidian.vault import ObsidianVault


def test_memory_decay_handles_offset_aware_timestamps(tmp_path: Path) -> None:
    """Memory decay should accept both naive and offset-aware persisted datetimes."""
    vault = ObsidianVault(tmp_path)
    vault.ensure_structure()
    store = MemoryStore(vault)

    vault.write_note(
        "memories/aware.md",
        "old memory",
        frontmatter={
            "id": "aware",
            "importance": 0.1,
            "tags": [],
            "source": "test",
            "created": "2024-01-01T10:00:00+02:00",
            "accessed": "2024-01-01T10:00:00+02:00",
            "access_count": 0,
        },
    )

    removed = store.decay(max_age_hours=1)

    assert removed == 1
    assert not vault.note_exists("memories/aware.md")


def test_task_list_all_handles_mixed_naive_and_aware_created_values(tmp_path: Path) -> None:
    """Task loading should normalize mixed persisted datetime formats."""
    vault = ObsidianVault(tmp_path)
    vault.ensure_structure()
    tracker = TaskTracker(vault)

    vault.write_note(
        "tasks/naive.md",
        "# ☐ Naive\n\n**Status:** todo\n",
        frontmatter={
            "id": "naive",
            "title": "Naive",
            "status": "todo",
            "priority": "medium",
            "assignee": "",
            "tags": [],
            "parent_id": "",
            "created": "2026-04-13T10:00:00",
            "updated": "2026-04-13T10:00:00",
        },
    )
    vault.write_note(
        "tasks/aware.md",
        "# ☐ Aware\n\n**Status:** todo\n",
        frontmatter={
            "id": "aware",
            "title": "Aware",
            "status": "todo",
            "priority": "medium",
            "assignee": "",
            "tags": [],
            "parent_id": "",
            "created": "2026-04-13T11:00:00+02:00",
            "updated": "2026-04-13T11:00:00+02:00",
        },
    )

    tasks = tracker.list_all()

    assert [task.id for task in tasks] == ["aware", "naive"]


def test_task_update_status_preserves_description_without_duplication(tmp_path: Path) -> None:
    """Updating task status should not embed the rendered note inside its description."""
    vault = ObsidianVault(tmp_path)
    vault.ensure_structure()
    tracker = TaskTracker(vault)

    task = tracker.create("Bug demo", "Original description")
    tracker.update_status(task.id, "done")
    updated = tracker.get(task.id)

    assert updated is not None
    assert updated.description == "Original description"


def test_task_update_preserves_a_legacy_handwritten_body(tmp_path: Path) -> None:
    """Updating metadata must not discard prose from a human-edited task note."""
    vault = ObsidianVault(tmp_path)
    vault.ensure_structure()
    tracker = TaskTracker(vault)
    vault.write_note(
        "tasks/legacy.md",
        "# Call the studio\n\nAsk about the Saturday slot and bring the old reference.",
        frontmatter={
            "id": "legacy",
            "title": "Call the studio",
            "status": "todo",
            "priority": "medium",
            "created": "2026-07-30T09:00:00+02:00",
            "updated": "2026-07-30T09:00:00+02:00",
        },
    )

    tracker.update_status("legacy", "done")
    updated = tracker.get("legacy")
    _, body = vault.read_note("tasks/legacy.md")

    assert updated is not None
    assert "Ask about the Saturday slot" in updated.description
    assert "Ask about the Saturday slot" in body


def test_task_list_skips_malformed_human_edited_frontmatter(tmp_path: Path) -> None:
    """One damaged Markdown note must not make the whole agenda unavailable."""
    vault = ObsidianVault(tmp_path)
    vault.ensure_structure()
    tracker = TaskTracker(vault)
    tracker.create("Healthy task")
    vault.write_note(
        "tasks/damaged.md",
        "# Damaged",
        frontmatter={
            "id": "damaged",
            "title": "Damaged",
            "status": "todo",
            "duration_minutes": "thirty",
        },
    )

    tasks = tracker.list_all()

    assert [task.title for task in tasks] == ["Healthy task"]
    assert tracker.get("damaged") is None

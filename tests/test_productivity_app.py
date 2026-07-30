"""Textual integration tests for the daily agenda workflow."""

from __future__ import annotations

from datetime import date

import pytest
from textual.widgets import Input, Static

from yui.tui.app import YuiApp
from yui.tui.widgets.task_editor import ConfirmDeleteScreen, TaskEditorScreen


@pytest.mark.asyncio
async def test_user_can_add_and_complete_a_task_from_today_view(tmp_path) -> None:
    app = YuiApp(vault_path=tmp_path, today_factory=lambda: date(2026, 7, 30))

    async with app.run_test(size=(120, 38)) as pilot:
        title = app.query_one("#view-title", Static)
        assert "Thursday, July 30" in str(title.content)

        quick_add = app.query_one("#quick-add", Input)
        quick_add.value = "Review roadmap @14:30 /30m #work !high"
        quick_add.focus()
        await pilot.press("enter")
        await pilot.pause()

        assert app.task_tracker is not None
        tasks = app.task_tracker.agenda(date(2026, 7, 30))
        assert [task.title for task in tasks] == ["Review roadmap"]
        assert "Review roadmap" in str(app.query_one("#agenda-list").render())

        await pilot.press("space")
        await pilot.pause()

        completed = app.task_tracker.get(tasks[0].id)
        assert completed is not None
        assert completed.status == "done"
        assert "1 of 1 complete" in str(app.query_one("#progress-copy", Static).content)


@pytest.mark.asyncio
async def test_navigation_switches_between_today_and_inbox(tmp_path) -> None:
    app = YuiApp(vault_path=tmp_path, today_factory=lambda: date(2026, 7, 30))

    async with app.run_test(size=(110, 34)) as pilot:
        assert app.current_view == "today"

        await pilot.press("i")
        await pilot.pause()

        assert app.current_view == "inbox"
        assert "Inbox" in str(app.query_one("#view-title", Static).content)


@pytest.mark.asyncio
async def test_inbox_title_words_do_not_become_implicit_date_tokens(tmp_path) -> None:
    app = YuiApp(vault_path=tmp_path, today_factory=lambda: date(2026, 7, 30))

    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.press("i")
        quick_add = app.query_one("#quick-add", Input)
        quick_add.value = "Write today's recap"
        quick_add.focus()
        await pilot.press("enter")
        await pilot.pause()

        assert app.task_tracker is not None
        tasks = app.task_tracker.inbox()
        assert [task.title for task in tasks] == ["Write today's recap"]
        assert tasks[0].due_date is None


@pytest.mark.asyncio
async def test_user_can_edit_task_details_and_confirm_deletion(tmp_path) -> None:
    app = YuiApp(vault_path=tmp_path, today_factory=lambda: date(2026, 7, 30))

    async with app.run_test(size=(120, 38)) as pilot:
        quick_add = app.query_one("#quick-add", Input)
        quick_add.value = "First title @09:00 /20m"
        quick_add.focus()
        await pilot.press("enter")
        await pilot.pause()

        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, TaskEditorScreen)

        app.screen.query_one("#edit-title", Input).value = "Revised title"
        app.screen.query_one("#edit-date", Input).value = "2026-07-31"
        app.screen.query_one("#edit-time", Input).value = "13:15"
        app.screen.query_one("#edit-duration", Input).value = "45"
        app.screen.query_one("#edit-area", Input).value = "studio"
        app.screen.query_one("#edit-priority", Input).value = "high"
        await pilot.click("#save-task")
        await pilot.pause()

        assert app.task_tracker is not None
        saved = app.task_tracker.list_all()
        assert len(saved) == 1
        assert saved[0].title == "Revised title"
        assert saved[0].due_date == date(2026, 7, 31)
        assert saved[0].duration_minutes == 45
        assert saved[0].area == "studio"

        app.current_task_id = saved[0].id
        app.current_view = "tomorrow"
        app.refresh_workspace(preferred_id=saved[0].id)
        app.query_one("#agenda-list").focus()
        await pilot.press("x")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDeleteScreen)

        await pilot.click("#confirm-delete")
        await pilot.pause()

        assert app.task_tracker.list_all() == []

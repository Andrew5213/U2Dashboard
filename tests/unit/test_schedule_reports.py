"""Relatórios (PDF/XLSX) e listagens sobre uma lista de cronograma de 3 níveis."""
from datetime import date, datetime, timedelta, timezone
from io import BytesIO

import openpyxl
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.database import Base
from src.repositories.cache_repository import (
    CacheRepository, _FIELD_DATA_CONCLUSAO_ID, _FIELD_VENCIMENTO_ID,
)
from src.services.report_service import (
    DisciplineReportService, ListReportService, PeriodicReportService, ProvinceReportService,
    _fmt_progress, _status_with_progress,
)
from src.services.report_xlsx_service import render_periodic_xlsx
from src.services.schedule_fields import date_to_ms

TODAY = datetime.now(timezone.utc).date()
CALENDAR_OPTIONS = [{"id": "u", "name": "Útil", "orderindex": 0}, {"id": "c", "name": "Corrido", "orderindex": 1}]


def _ms(moment: datetime) -> str:
    return str(int(moment.replace(tzinfo=timezone.utc).timestamp() * 1000))


def schedule_task(task_id, parent=None, percent=0, duration=None, corrido=False, status="planejando",
                  status_type="open", start=None, due=None, closed=None, updated=None, created=0, team=None):
    return {
        "id": task_id, "name": task_id, "parent": parent, "list": {"id": "L1"},
        "status": {"status": status, "type": status_type, "color": "#ff7800"},
        "start_date": str(date_to_ms(start)) if start else None,
        "due_date": str(date_to_ms(due)) if due else None,
        "date_created": str(1_780_000_000_000 + created),
        "date_updated": _ms(updated) if updated else None,
        "group_assignees": [{"id": "g", "name": team}] if team else [],
        "custom_fields": [
            {"id": "p", "name": "% Concluído", "type": "manual_progress",
             "value": {"current": str(percent), "percent_completed": percent / 100}},
            {"id": "d", "name": "Duração (dias)", "type": "number",
             "value": None if duration is None else str(duration)},
            {"id": "k", "name": "Calendário", "type": "drop_down",
             "type_config": {"options": CALENDAR_OPTIONS}, "value": 1 if corrido else 0},
            {"id": _FIELD_DATA_CONCLUSAO_ID, "name": "Data de Conclusão", "type": "date",
             "value": _ms(closed) if closed else None},
        ],
    }


def plain_task(task_id, parent=None, vencimento=None, created=0):
    return {
        "id": task_id, "name": task_id, "parent": parent, "list": {"id": "L2"},
        "status": {"status": "planejando", "type": "open"},
        "date_created": str(1_780_000_000_000 + created),
        "custom_fields": [
            {"id": _FIELD_VENCIMENTO_ID, "name": "Vencimento", "type": "date",
             "value": str(date_to_ms(vencimento)) if vencimento else None},
        ],
    }


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def repo(db) -> CacheRepository:
    """Site FM em miniatura (disciplina → grupo → tarefa) + uma lista comum de 2 níveis."""
    repo = CacheRepository(db)
    await repo.upsert_space({"id": "S", "name": "Space"})
    await repo.upsert_folder({"id": "F", "name": "LUBANGO"}, "S")
    await repo.upsert_list({"id": "L1", "name": "Site FM"}, "S", "F")
    await repo.upsert_list({"id": "L2", "name": "Estudios"}, "S", "F")
    now = datetime.utcnow()
    soon = TODAY + timedelta(days=3)
    for order, task in enumerate([
        schedule_task("Obra Civil", percent=50, duration=4, status="fazendo", status_type="custom",
                      start=TODAY - timedelta(days=2), due=soon, updated=now, team="PROEF"),
        schedule_task("Base do Gerador", "Obra Civil", percent=50, duration=4, status="fazendo",
                      status_type="custom", start=TODAY - timedelta(days=2), due=soon, updated=now),
        schedule_task("Concretagem", "Base do Gerador", percent=100, duration=2, status="complete",
                      status_type="done", start=TODAY - timedelta(days=2), due=TODAY - timedelta(days=1),
                      closed=now - timedelta(hours=2), updated=now, team="PROEF"),
        schedule_task("Cura do Concreto", "Base do Gerador", percent=40, duration=14, corrido=True,
                      status="fazendo", status_type="custom", start=TODAY, due=soon, updated=now, team="PROEF"),
        schedule_task("Logística", percent=0, duration=1.5, start=soon, due=soon),
    ]):
        await repo.upsert_task({**task, "date_created": str(1_780_000_000_000 + order)}, "L1")
    await repo.upsert_task(plain_task("Equipamentos", vencimento=soon), "L2")
    await repo.upsert_task(plain_task("Montagem", "Equipamentos", vencimento=soon, created=1), "L2")
    return repo


class TestListings:
    async def test_upcoming_lists_schedule_leaves_with_their_group(self, repo):
        names = [t["name"] for t in await repo.get_upcoming_tasks_by_folder("F", days=30)]
        assert "Base do Gerador / Cura do Concreto" in names
        assert "Logística" in names                 # disciplina sem filhos é a própria tarefa
        assert "Obra Civil" not in names            # resumo calculado
        assert "Base do Gerador" not in names

    async def test_plain_list_still_lists_the_top_level_task(self, repo):
        names = [t["name"] for t in await repo.get_upcoming_tasks_by_folder("F", days=30)]
        assert "Equipamentos" in names
        assert not any("Montagem" in name for name in names)

    async def test_space_listing_follows_the_same_rule(self, repo):
        names = [t["name"] for t in await repo.get_upcoming_tasks("S", 30)]
        assert "Base do Gerador / Cura do Concreto" in names and "Obra Civil" not in names


class TestPeriodUpdates:
    async def _tasks(self, repo) -> list[dict]:
        now = datetime.utcnow()
        folders = await repo.get_period_updates("S", now - timedelta(days=1), now + timedelta(minutes=1))
        return folders[0]["tasks"]

    async def test_leaves_nest_under_the_discipline_with_the_group_in_the_name(self, repo):
        tasks = await self._tasks(repo)
        assert {t["name"] for t in tasks} == {"Obra Civil"}
        by_category = {t["category"]: [s["name"] for s in t["subtasks"]] for t in tasks}
        assert by_category == {
            "concluded": ["Base do Gerador / Concretagem"],
            "updated": ["Base do Gerador / Cura do Concreto"],
        }

    async def test_summary_rewritten_by_the_engine_is_not_an_update_on_its_own(self, repo):
        # as tarefas voltam a "planejando": no período só a disciplina e o grupo,
        # ambos em "fazendo", têm data de atualização
        for leaf in ("Concretagem", "Cura do Concreto"):
            await repo.upsert_task(schedule_task(leaf, "Base do Gerador", duration=2), "L1")
        now = datetime.utcnow()
        folders = await repo.get_period_updates("S", now - timedelta(days=1), now + timedelta(minutes=1))
        assert folders == []

    async def test_open_schedule_task_shows_its_percent_beside_the_status(self, repo):
        updated = next(t for t in await self._tasks(repo) if t["category"] == "updated")
        assert _status_with_progress(updated["subtasks"][0]) == "fazendo 40%"
        assert _status_with_progress({"status": "complete", "progress_pct": 100}) == "complete"
        assert _status_with_progress({"status": "fazendo", "progress_pct": None}) == "fazendo"

    async def test_periodic_pdf_and_xlsx_render(self, repo, db):
        service = PeriodicReportService(db)
        assert (await service.generate_daily_pdf("S")).startswith(b"%PDF")
        now = datetime.utcnow()
        data = await service._build_data("S", now - timedelta(days=1), now, "Diario", "hoje")
        cells = [c for row in openpyxl.load_workbook(BytesIO(render_periodic_xlsx(data))).active.iter_rows(values_only=True) for c in row]
        assert "fazendo 40%" in cells


class TestListReport:
    async def test_rows_carry_level_dates_duration_and_percent(self, repo, db):
        data = await ListReportService(db)._build_data("L1")
        assert data["is_schedule"] is True
        rows = {r["name"]: r for r in data["rows"]}
        assert [r["level"] for r in data["rows"]] == [0, 1, 2, 2, 0]
        assert rows["Obra Civil"]["is_summary"] and rows["Base do Gerador"]["is_summary"]
        cure = rows["Cura do Concreto"]
        assert not cure["is_summary"]
        assert cure["duration_fmt"] == "14 d corr."
        assert cure["start_fmt"] == TODAY.strftime("%d/%m/%Y")
        assert cure["progress_pct"] == 40
        assert cure["assignees_str"] == "PROEF"
        assert rows["Logística"]["duration_fmt"] == "1,5 d"

    async def test_only_leaves_count_as_tasks_and_the_header_sums_the_list_up(self, repo, db):
        data = await ListReportService(db)._build_data("L1")
        assert data["total_disciplines"] == 2
        assert data["total_activities"] == 3        # 2 tarefas + a disciplina sem filhos
        start = (TODAY - timedelta(days=2)).strftime("%d/%m/%Y")
        end = (TODAY + timedelta(days=3)).strftime("%d/%m/%Y")
        assert start in data["schedule_summary"] and end in data["schedule_summary"]

    async def test_english_report_uses_dot_and_calendar_days(self, repo, db):
        rows = {r["name"]: r for r in (await ListReportService(db)._build_data("L1", lang="en"))["rows"]}
        assert rows["Cura do Concreto"]["duration_fmt"] == "14 cal. d"
        assert rows["Logística"]["duration_fmt"] == "1.5 d"

    async def test_list_without_dates_renders_blank_columns(self, db):
        repo = CacheRepository(db)
        await repo.upsert_space({"id": "S", "name": "Space"})
        await repo.upsert_folder({"id": "F", "name": "LUENA"}, "S")
        await repo.upsert_list({"id": "L1", "name": "Site FM"}, "S", "F")
        await repo.upsert_task(schedule_task("Obra Civil"), "L1")
        await repo.upsert_task(schedule_task("Fundação", "Obra Civil", duration=2, created=1), "L1")
        data = await ListReportService(db)._build_data("L1")
        assert data["rows"][1]["start_fmt"] == "-" and data["rows"][1]["end_fmt"] == "-"
        assert (await ListReportService(db).generate_pdf("L1")).startswith(b"%PDF")

    async def test_pdfs_render_for_list_and_discipline(self, repo, db):
        assert (await ListReportService(db).generate_pdf("L1")).startswith(b"%PDF")
        assert (await DisciplineReportService(db).generate_pdf("Obra Civil")).startswith(b"%PDF")
        assert (await DisciplineReportService(db).generate_pdf("Base do Gerador")).startswith(b"%PDF")

    async def test_discipline_report_counts_leaves_below_the_groups(self, repo, db):
        data = await DisciplineReportService(db)._build_data("Obra Civil")
        assert data["is_schedule"] is True and data["total_activities"] == 2
        assert [r["level"] for r in data["rows"]] == [0, 1, 2, 2]

    async def test_plain_list_keeps_the_old_layout(self, repo, db):
        data = await ListReportService(db)._build_data("L2")
        assert data["is_schedule"] is False and data["schedule_summary"] is None
        assert "level" not in data["rows"][0]
        assert (await ListReportService(db).generate_pdf("L2")).startswith(b"%PDF")


class TestProvinceReport:
    async def test_schedule_list_gets_schedule_columns_and_the_plain_list_does_not(self, repo, db):
        data = await ProvinceReportService(db)._build_data("F")
        lists = {lst["name"]: lst for lst in data["lists_detail"]}
        assert lists["Site FM"]["is_schedule"] and not lists["Estudios"]["is_schedule"]
        assert [(r["name"], r["level"]) for r in lists["Site FM"]["tasks"]] == [
            ("Obra Civil", 0), ("Base do Gerador", 1), ("Concretagem", 2), ("Cura do Concreto", 2), ("Logística", 0),
        ]
        assert "duration_fmt" not in lists["Estudios"]["tasks"][0]

    async def test_pdf_and_xlsx_render(self, repo, db):
        service = ProvinceReportService(db)
        assert (await service.generate_pdf("F")).startswith(b"%PDF")
        sheet = openpyxl.load_workbook(BytesIO(await service.generate_xlsx("F"))).active
        rows = [row for row in sheet.iter_rows(values_only=True) if row[1] in ("Disciplina", "Grupo", "Tarefa")]
        assert [(r[0].strip(), r[1]) for r in rows[:4]] == [
            ("Obra Civil", "Disciplina"), ("Base do Gerador", "Grupo"),
            ("Concretagem", "Tarefa"), ("Cura do Concreto", "Tarefa"),
        ]
        assert rows[3][2] == "14 d corr." and rows[3][5] == pytest.approx(0.4)


def test_progress_never_rounds_to_the_extremes():
    assert _fmt_progress(99.99) == "99%"
    assert _fmt_progress(0.2) == "1%"
    assert _fmt_progress(100) == "100%"
    assert _fmt_progress(0) == "0%"


class TestGanttReport:
    async def _data(self, db, folder_id="F", lang="pt") -> dict:
        from src.services.gantt_report_service import GanttReportService
        return await GanttReportService(db)._build_data(folder_id, lang)

    async def test_schedule_list_brings_every_level_with_its_dates(self, repo, db):
        data = await self._data(db)
        site = next(lst for lst in data["lists"] if lst["name"] == "Site FM")
        rows = {r["name"]: r for r in site["rows"]}
        assert [(r["name"], r["level"]) for r in site["rows"]] == [
            ("Obra Civil", 0), ("Base do Gerador", 1), ("Concretagem", 2), ("Cura do Concreto", 2), ("Logística", 0),
        ]
        assert rows["Obra Civil"]["is_summary"] and not rows["Cura do Concreto"]["is_summary"]
        assert (rows["Cura do Concreto"]["start"], rows["Cura do Concreto"]["end"]) == (TODAY, TODAY + timedelta(days=3))
        assert rows["Cura do Concreto"]["progress_pct"] == 40
        assert rows["Concretagem"]["is_done"] and not rows["Concretagem"]["is_overdue"]

    async def test_timeline_covers_whole_weeks_around_the_tasks(self, repo, db):
        data = await self._data(db)
        assert data["first_day"] == TODAY - timedelta(days=2)
        assert data["last_day"] == TODAY + timedelta(days=3)
        assert data["range_start"].weekday() == 0 and data["range_end"].weekday() == 6
        assert data["range_start"] <= data["first_day"] and data["range_end"] >= data["last_day"]
        assert data["total_tasks"] == 4             # 3 folhas do cronograma + Equipamentos

    async def test_plain_parent_without_dates_spans_its_children(self, db):
        repo = CacheRepository(db)
        await repo.upsert_space({"id": "S", "name": "Space"})
        await repo.upsert_folder({"id": "F", "name": "LUANDA"}, "S")
        await repo.upsert_list({"id": "L2", "name": "Estudio"}, "S", "F")
        await repo.upsert_list({"id": "L3", "name": "Vazia"}, "S", "F")
        await repo.upsert_task(plain_task("Obra Civil"), "L2")
        await repo.upsert_task(plain_task("Pintura", "Obra Civil", vencimento=TODAY - timedelta(days=5), created=1), "L2")
        await repo.upsert_task(plain_task("Piso", "Obra Civil", vencimento=TODAY + timedelta(days=2), created=2), "L2")
        await repo.upsert_task(plain_task("Sem data", "Obra Civil", created=3), "L2")
        await repo.upsert_task({**plain_task("Solta"), "list": {"id": "L3"}}, "L3")
        data = await self._data(db)
        rows = {r["name"]: r for r in data["lists"][0]["rows"]}
        assert set(rows) == {"Obra Civil", "Pintura", "Piso"}
        assert (rows["Obra Civil"]["start"], rows["Obra Civil"]["end"]) == (TODAY - timedelta(days=5), TODAY + timedelta(days=2))
        assert rows["Pintura"]["is_overdue"] and not rows["Piso"]["is_overdue"]
        assert data["undated_lists"] == ["Vazia"]

    async def test_pdf_renders_with_and_without_dates(self, repo, db):
        from src.services.gantt_report_service import GanttReportService
        assert (await GanttReportService(db).generate_pdf("F")).startswith(b"%PDF")
        assert (await GanttReportService(db).generate_pdf("F", lang="en")).startswith(b"%PDF")
        await repo.upsert_folder({"id": "F2", "name": "BENGUELA"}, "S")
        await repo.upsert_list({"id": "L9", "name": "Site FM"}, "S", "F2")
        await repo.upsert_task({**schedule_task("Obra Civil sem data"), "list": {"id": "L9"}}, "L9")
        data = await self._data(db, "F2")
        assert data["lists"] == [] and data["undated_lists"] == ["Site FM"]
        assert (await GanttReportService(db).generate_pdf("F2")).startswith(b"%PDF")

    async def test_long_schedule_renders_on_several_pages(self, db):
        from src.services.gantt_report_service import GanttReportService
        repo = CacheRepository(db)
        await repo.upsert_space({"id": "S", "name": "Space"})
        await repo.upsert_folder({"id": "F", "name": "LUENA"}, "S")
        await repo.upsert_list({"id": "L1", "name": "Site FM"}, "S", "F")
        await repo.upsert_task(schedule_task("Obra", start=TODAY, due=TODAY + timedelta(days=400)), "L1")
        for i in range(90):
            await repo.upsert_task(schedule_task(f"T{i}", "Obra", duration=3, start=TODAY + timedelta(days=4 * i),
                                                 due=TODAY + timedelta(days=4 * i + 3), created=i + 1), "L1")
        from src.services.gantt_report_service import _GanttReport
        data = await GanttReportService(db)._build_data("F")
        pdf = _GanttReport(data)
        pdf.add_page()
        pdf.build_title(data)
        pdf.build_lists(data["lists"])
        assert pdf.page_no() == 3
        assert not pdf._weekly()                    # mais de um ano: a grade passa a ser mensal
        assert (await GanttReportService(db).generate_pdf("F")).startswith(b"%PDF")

    async def test_unknown_folder_is_an_error(self, db):
        from src.services.gantt_report_service import GanttReportService
        with pytest.raises(ValueError):
            await GanttReportService(db).generate_pdf("nao-existe")

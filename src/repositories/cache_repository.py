import json
import unicodedata
from datetime import datetime, timezone
from sqlalchemy import select, delete, func, case, and_
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.cache_models import (
    ClickUpSpaceCache, ClickUpFolderCache, ClickUpListCache,
    ClickUpTaskCache, ClickUpUserCache, CacheRefreshLog, DisciplineWeight,
)


def _norm_status(status: str | None) -> str:
    if not status:
        return ""
    nfkd = unicodedata.normalize("NFKD", status)
    return nfkd.encode("ascii", "ignore").decode("ascii").strip().lower()


# Status que representam progresso real de uma atividade — usados para filtrar
# relatórios e o assistente de IA, que não devem mais mostrar tarefas recém-criadas
# (ainda em "planejando") como se fossem uma "mudança" digna de nota.
_REPORTABLE_ACTIVE_STATUSES = {"fazendo", "revisao", "em revisao", "aprovacao", "em aprovacao"}
_REPORTABLE_UPDATE_STATUSES = _REPORTABLE_ACTIVE_STATUSES | {"concluido", "complete"}


def _ms_to_dt(ms: str | int | None) -> datetime | None:
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).replace(tzinfo=None)
    except (ValueError, OverflowError, OSError):
        return None


# Custom fields "Vencimento" e "Data de Conclusão" (tipo date), adicionados pelo
# usuário a todas as listas do space com o mesmo field id (custom field a nível de
# Space). Passam a ser a fonte de verdade para due_date/date_closed no cache — têm
# prioridade sobre os campos nativos do ClickUp (due_date/date_closed), que ficam
# como fallback apenas para tasks que ainda não foram migradas para os novos campos.
# Se os fields forem recriados no ClickUp, os ids abaixo precisam ser atualizados
# (descobertos via GET /list/{id}/field).
_FIELD_VENCIMENTO_ID = "9c6f3a32-24a2-4163-b833-9f76bf0e900c"
_FIELD_DATA_CONCLUSAO_ID = "57217afa-f902-485e-bd14-6505c061cd01"


def _custom_field_value(task: dict, field_id: str) -> str | int | None:
    for cf in task.get("custom_fields") or []:
        if cf.get("id") == field_id:
            return cf.get("value")
    return None


def _leaf_tasks_clause():
    """Filtro para tarefas 'folha' (unidade real de progresso): subtasks, ou tasks de
    topo sem subtasks. Exclui tasks de topo que possuem subtasks, já que o progresso
    dessas é representado pelas próprias subtasks."""
    parent_ids = (
        select(ClickUpTaskCache.parent_task_id)
        .where(ClickUpTaskCache.parent_task_id.isnot(None))
        .distinct()
        .scalar_subquery()
    )
    return ClickUpTaskCache.task_id.notin_(parent_ids)


class CacheRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ─── Upserts ─────────────────────────────────────────────────────────────

    async def upsert_space(self, space: dict) -> None:
        stmt = sqlite_insert(ClickUpSpaceCache).values(
            space_id=str(space["id"]),
            name=space.get("name", ""),
            private=bool(space.get("private", False)),
            last_refreshed_at=datetime.utcnow(),
        )
        await self._db.execute(stmt.on_conflict_do_update(
            index_elements=["space_id"],
            set_={"name": stmt.excluded.name, "last_refreshed_at": stmt.excluded.last_refreshed_at},
        ))

    async def upsert_folder(self, folder: dict, space_id: str) -> None:
        stmt = sqlite_insert(ClickUpFolderCache).values(
            folder_id=str(folder["id"]),
            space_id=space_id,
            name=folder.get("name", ""),
            hidden=bool(folder.get("hidden", False)),
            task_count=int(folder.get("task_count", 0)),
            last_refreshed_at=datetime.utcnow(),
        )
        await self._db.execute(stmt.on_conflict_do_update(
            index_elements=["folder_id"],
            set_={
                "name": stmt.excluded.name,
                "hidden": stmt.excluded.hidden,
                "task_count": stmt.excluded.task_count,
                "last_refreshed_at": stmt.excluded.last_refreshed_at,
            },
        ))

    async def upsert_list(self, list_data: dict, space_id: str, folder_id: str | None) -> None:
        status_obj = list_data.get("status") or {}
        status_text = status_obj.get("status") if isinstance(status_obj, dict) else None
        stmt = sqlite_insert(ClickUpListCache).values(
            list_id=str(list_data["id"]),
            space_id=space_id,
            folder_id=folder_id,
            name=list_data.get("name", ""),
            status_text=status_text,
            task_count=int(list_data.get("task_count", 0)),
            last_refreshed_at=datetime.utcnow(),
        )
        await self._db.execute(stmt.on_conflict_do_update(
            index_elements=["list_id"],
            set_={
                "name": stmt.excluded.name,
                "status_text": stmt.excluded.status_text,
                "task_count": stmt.excluded.task_count,
                "last_refreshed_at": stmt.excluded.last_refreshed_at,
            },
        ))

    async def upsert_task(self, task: dict, list_id: str) -> None:
        status = task.get("status") or {}
        if isinstance(status, str):
            status_name, status_type, status_color = status, None, None
        else:
            status_name = status.get("status")
            status_type = status.get("type")
            status_color = status.get("color")

        assignees = task.get("assignees") or []
        group_assignees = task.get("group_assignees") or []
        assignees_json = json.dumps(
            [{"id": str(a.get("id", "")), "username": a.get("username", "")}
             for a in assignees if isinstance(a, dict)]
            + [{"id": "grp_" + str(g.get("id", "")), "username": g.get("name", "")}
               for g in group_assignees if isinstance(g, dict) and g.get("name")]
        )
        tags = task.get("tags") or []
        tags_json = json.dumps([t.get("name", t) if isinstance(t, dict) else t for t in tags])

        parent = task.get("parent")
        parent_task_id = str(parent) if parent else None

        actual_list = task.get("list") or {}
        actual_list_id = str(actual_list.get("id", list_id)) if actual_list else list_id

        due_date = _custom_field_value(task, _FIELD_VENCIMENTO_ID) or task.get("due_date")
        date_closed = _custom_field_value(task, _FIELD_DATA_CONCLUSAO_ID) or task.get("date_closed")

        stmt = sqlite_insert(ClickUpTaskCache).values(
            task_id=str(task["id"]),
            list_id=actual_list_id,
            parent_task_id=parent_task_id,
            name=task.get("name", ""),
            description=task.get("description") or None,
            status=status_name,
            status_type=status_type,
            status_color=status_color,
            assignees_json=assignees_json,
            tags_json=tags_json,
            due_date=_ms_to_dt(due_date),
            start_date=_ms_to_dt(task.get("start_date")),
            date_created=_ms_to_dt(task.get("date_created")),
            date_updated=_ms_to_dt(task.get("date_updated")),
            date_closed=_ms_to_dt(date_closed),
            url=task.get("url"),
            last_refreshed_at=datetime.utcnow(),
        )
        await self._db.execute(stmt.on_conflict_do_update(
            index_elements=["task_id"],
            set_={
                "name": stmt.excluded.name,
                "description": stmt.excluded.description,
                "status": stmt.excluded.status,
                "status_type": stmt.excluded.status_type,
                "status_color": stmt.excluded.status_color,
                "assignees_json": stmt.excluded.assignees_json,
                "tags_json": stmt.excluded.tags_json,
                "due_date": stmt.excluded.due_date,
                "start_date": stmt.excluded.start_date,
                "date_updated": stmt.excluded.date_updated,
                "date_closed": stmt.excluded.date_closed,
                "last_refreshed_at": stmt.excluded.last_refreshed_at,
            },
        ))

    async def upsert_user(self, user: dict) -> None:
        uid = user.get("id")
        if not uid:
            return
        stmt = sqlite_insert(ClickUpUserCache).values(
            user_id=str(uid),
            username=user.get("username") or user.get("email", "sem nome"),
            email=user.get("email"),
            color=user.get("color"),
            profile_picture=user.get("profilePicture"),
            last_refreshed_at=datetime.utcnow(),
        )
        await self._db.execute(stmt.on_conflict_do_update(
            index_elements=["user_id"],
            set_={
                "username": stmt.excluded.username,
                "email": stmt.excluded.email,
                "color": stmt.excluded.color,
                "profile_picture": stmt.excluded.profile_picture,
                "last_refreshed_at": stmt.excluded.last_refreshed_at,
            },
        ))

    async def delete_task(self, task_id: str) -> None:
        await self._db.execute(delete(ClickUpTaskCache).where(ClickUpTaskCache.task_id == task_id))

    async def get_task_list_id(self, task_id: str) -> str | None:
        result = await self._db.execute(
            select(ClickUpTaskCache.list_id).where(ClickUpTaskCache.task_id == task_id)
        )
        return result.scalar_one_or_none()

    async def mark_tasks_stale(self, list_id: str, seen_ids: set[str]) -> int:
        # Sem filtro de parent_task_id: `seen_ids` já inclui subtasks (get_tasks
        # busca com subtasks=true), então tasks E subtasks apagadas no ClickUp
        # precisam ser consideradas aqui, senão subtasks deletadas nunca são
        # removidas do cache mesmo num refresh completo.
        result = await self._db.execute(
            select(ClickUpTaskCache.task_id).where(ClickUpTaskCache.list_id == list_id)
        )
        existing = {row[0] for row in result.fetchall()}
        stale = existing - seen_ids
        if stale:
            await self._db.execute(delete(ClickUpTaskCache).where(ClickUpTaskCache.task_id.in_(stale)))
        return len(stale)

    async def mark_lists_stale(self, space_id: str, seen_ids: set[str]) -> int:
        """Remove do cache listas apagadas no ClickUp (não retornadas mais pela API),
        junto com suas tasks/subtasks e pesos de disciplina — SQLite não força FKs
        aqui, então essa limpeza precisa ser manual, na ordem filho → pai."""
        result = await self._db.execute(
            select(ClickUpListCache.list_id).where(ClickUpListCache.space_id == space_id)
        )
        existing = {row[0] for row in result.fetchall()}
        stale = existing - seen_ids
        if stale:
            await self._db.execute(delete(ClickUpTaskCache).where(ClickUpTaskCache.list_id.in_(stale)))
            await self._db.execute(delete(DisciplineWeight).where(DisciplineWeight.list_id.in_(stale)))
            await self._db.execute(delete(ClickUpListCache).where(ClickUpListCache.list_id.in_(stale)))
        return len(stale)

    async def mark_folders_stale(self, space_id: str, seen_ids: set[str]) -> int:
        """Remove do cache pastas apagadas no ClickUp. Listas/tasks dessas pastas já
        foram removidas por `mark_lists_stale` (a API para de retorná-las junto com a
        pasta apagada), então aqui só resta a linha da própria pasta."""
        result = await self._db.execute(
            select(ClickUpFolderCache.folder_id).where(ClickUpFolderCache.space_id == space_id)
        )
        existing = {row[0] for row in result.fetchall()}
        stale = existing - seen_ids
        if stale:
            await self._db.execute(delete(ClickUpFolderCache).where(ClickUpFolderCache.folder_id.in_(stale)))
        return len(stale)

    # ─── Leituras ────────────────────────────────────────────────────────────

    async def get_overview_kpis(self, space_id: str) -> dict:
        now = datetime.utcnow()
        _done = ClickUpTaskCache.status_type.in_(["done", "closed"])
        _active = ClickUpTaskCache.status_type.notin_(["done", "closed"])
        row = (await self._db.execute(
            select(
                func.count(ClickUpTaskCache.task_id).label("total"),
                func.sum(case((_done, 1), else_=0)).label("completed"),
                func.sum(case(
                    (and_(
                        ClickUpTaskCache.due_date.isnot(None),
                        ClickUpTaskCache.due_date < now,
                        _active,
                    ), 1), else_=0,
                )).label("overdue"),
                func.sum(case((ClickUpTaskCache.due_date.is_(None), 1), else_=0)).label("no_due"),
            )
            .join(ClickUpListCache, ClickUpTaskCache.list_id == ClickUpListCache.list_id)
            .where(and_(
                ClickUpListCache.space_id == space_id,
                _leaf_tasks_clause(),
            ))
        )).one()

        dist = {r[0] or "sem status": r[1] for r in (await self._db.execute(
            select(ClickUpTaskCache.status, func.count(ClickUpTaskCache.task_id))
            .join(ClickUpListCache, ClickUpTaskCache.list_id == ClickUpListCache.list_id)
            .where(and_(
                ClickUpListCache.space_id == space_id,
                _leaf_tasks_clause(),
            ))
            .group_by(ClickUpTaskCache.status)
        )).fetchall()}

        total_folders = (await self._db.execute(
            select(func.count(ClickUpFolderCache.folder_id)).where(ClickUpFolderCache.space_id == space_id)
        )).scalar() or 0
        total_lists = (await self._db.execute(
            select(func.count(ClickUpListCache.list_id)).where(ClickUpListCache.space_id == space_id)
        )).scalar() or 0

        total = row.total or 0
        completed = row.completed or 0
        return {
            "total_tasks": total,
            "completed_tasks": completed,
            "completion_rate": round(completed / total, 4) if total > 0 else 0.0,
            "overdue_tasks": row.overdue or 0,
            "tasks_without_due_date": row.no_due or 0,
            "total_folders": total_folders,
            "total_lists": total_lists,
            "status_distribution": dist,
        }

    async def get_folders_with_metrics(self, space_id: str) -> list[dict]:
        now = datetime.utcnow()
        _done = ClickUpTaskCache.status_type.in_(["done", "closed"])
        _active = ClickUpTaskCache.status_type.notin_(["done", "closed"])
        rows = (await self._db.execute(
            select(
                ClickUpFolderCache.folder_id,
                ClickUpFolderCache.name,
                func.count(ClickUpListCache.list_id.distinct()).label("total_lists"),
                func.count(ClickUpTaskCache.task_id).label("total_tasks"),
                func.sum(case((_done, 1), else_=0)).label("completed"),
                func.sum(case(
                    (and_(
                        ClickUpTaskCache.due_date.isnot(None),
                        ClickUpTaskCache.due_date < now,
                        _active,
                    ), 1), else_=0,
                )).label("overdue"),
            )
            .join(ClickUpListCache, ClickUpListCache.folder_id == ClickUpFolderCache.folder_id, isouter=True)
            .join(ClickUpTaskCache, and_(
                ClickUpTaskCache.list_id == ClickUpListCache.list_id,
                _leaf_tasks_clause(),
            ), isouter=True)
            .where(ClickUpFolderCache.space_id == space_id)
            .group_by(ClickUpFolderCache.folder_id, ClickUpFolderCache.name)
            .order_by(ClickUpFolderCache.name)
        )).fetchall()
        return [
            {
                "folder_id": r.folder_id,
                "name": r.name,
                "total_lists": r.total_lists or 0,
                "total_tasks": r.total_tasks or 0,
                "completed_tasks": r.completed or 0,
                "overdue_tasks": r.overdue or 0,
                "completion_rate": round((r.completed or 0) / r.total_tasks, 4) if r.total_tasks else 0.0,
            }
            for r in rows
        ]

    async def get_lists_with_metrics(self, folder_id: str | None, space_id: str | None = None) -> list[dict]:
        now = datetime.utcnow()
        _done = ClickUpTaskCache.status_type.in_(["done", "closed"])
        _active = ClickUpTaskCache.status_type.notin_(["done", "closed"])
        conditions = []
        if folder_id is not None:
            conditions.append(ClickUpListCache.folder_id == folder_id)
        else:
            conditions.append(ClickUpListCache.folder_id.is_(None))
        if space_id:
            conditions.append(ClickUpListCache.space_id == space_id)

        rows = (await self._db.execute(
            select(
                ClickUpListCache.list_id,
                ClickUpListCache.name,
                ClickUpListCache.folder_id,
                func.count(ClickUpTaskCache.task_id).label("total_tasks"),
                func.sum(case((_done, 1), else_=0)).label("completed"),
                func.sum(case(
                    (and_(
                        ClickUpTaskCache.due_date.isnot(None),
                        ClickUpTaskCache.due_date < now,
                        _active,
                    ), 1), else_=0,
                )).label("overdue"),
            )
            .join(ClickUpTaskCache, and_(
                ClickUpTaskCache.list_id == ClickUpListCache.list_id,
                _leaf_tasks_clause(),
            ), isouter=True)
            .where(and_(*conditions))
            .group_by(ClickUpListCache.list_id, ClickUpListCache.name, ClickUpListCache.folder_id)
            .order_by(ClickUpListCache.name)
        )).fetchall()
        return [
            {
                "list_id": r.list_id,
                "name": r.name,
                "folder_id": r.folder_id,
                "total_tasks": r.total_tasks or 0,
                "completed_tasks": r.completed or 0,
                "overdue_tasks": r.overdue or 0,
                "completion_rate": round((r.completed or 0) / r.total_tasks, 4) if r.total_tasks else 0.0,
            }
            for r in rows
        ]

    async def get_tasks_by_list(self, list_id: str, include_subtasks: bool = False) -> list[ClickUpTaskCache]:
        conds = [ClickUpTaskCache.list_id == list_id]
        if not include_subtasks:
            conds.append(ClickUpTaskCache.parent_task_id.is_(None))
        result = await self._db.execute(
            select(ClickUpTaskCache).where(and_(*conds)).order_by(ClickUpTaskCache.date_created)
        )
        return list(result.scalars().all())

    async def get_subtask_count_by_parent(self, list_id: str) -> dict[str, int]:
        rows = (await self._db.execute(
            select(ClickUpTaskCache.parent_task_id, func.count(ClickUpTaskCache.task_id))
            .where(and_(
                ClickUpTaskCache.list_id == list_id,
                ClickUpTaskCache.parent_task_id.isnot(None),
            ))
            .group_by(ClickUpTaskCache.parent_task_id)
        )).fetchall()
        return {r[0]: r[1] for r in rows if r[0]}

    async def get_task_with_subtasks(self, task_id: str) -> tuple[ClickUpTaskCache | None, list[ClickUpTaskCache]]:
        task = (await self._db.execute(
            select(ClickUpTaskCache).where(ClickUpTaskCache.task_id == task_id)
        )).scalar_one_or_none()
        if not task:
            return None, []
        subtasks = list((await self._db.execute(
            select(ClickUpTaskCache)
            .where(ClickUpTaskCache.parent_task_id == task_id)
            .order_by(ClickUpTaskCache.date_created)
        )).scalars().all())
        return task, subtasks

    async def get_assignee_task_stats(self, space_id: str) -> list[dict]:
        stmt = (
            select(ClickUpTaskCache)
            .join(ClickUpListCache, ClickUpTaskCache.list_id == ClickUpListCache.list_id)
            .where(and_(
                ClickUpListCache.space_id == space_id,
                _leaf_tasks_clause(),
            ))
        )
        tasks = list((await self._db.execute(stmt)).scalars().all())

        from collections import defaultdict
        now = datetime.utcnow()
        stats: dict = defaultdict(lambda: {"open": 0, "completed": 0, "overdue": 0})
        for task in tasks:
            try:
                assignees = json.loads(task.assignees_json or "[]")
            except Exception:
                assignees = []
            names = [a.get("username") for a in assignees if a.get("username")]
            is_done = task.status_type in ("done", "closed")
            is_overdue = task.due_date is not None and task.due_date < now and not is_done
            for name in names:
                if not name:
                    continue
                if is_done:
                    stats[name]["completed"] += 1
                else:
                    stats[name]["open"] += 1
                if is_overdue:
                    stats[name]["overdue"] += 1

        return [
            {"assignee": k, "open": v["open"], "completed": v["completed"], "overdue": v["overdue"]}
            for k, v in sorted(stats.items(), key=lambda x: -(x[1]["open"] + x[1]["completed"]))
        ]

    async def get_upcoming_tasks(self, space_id: str, days: int) -> list[dict]:
        from datetime import timedelta
        now = datetime.utcnow()
        cutoff = now + timedelta(days=days)
        stmt = (
            select(
                ClickUpTaskCache,
                ClickUpListCache.name.label("list_name"),
                ClickUpFolderCache.name.label("folder_name"),
            )
            .join(ClickUpListCache, ClickUpTaskCache.list_id == ClickUpListCache.list_id)
            .outerjoin(ClickUpFolderCache, ClickUpListCache.folder_id == ClickUpFolderCache.folder_id)
            .where(and_(
                ClickUpListCache.space_id == space_id,
                ClickUpTaskCache.due_date >= now,
                ClickUpTaskCache.due_date <= cutoff,
                ClickUpTaskCache.status_type.notin_(["done", "closed"]),
                ClickUpTaskCache.parent_task_id.is_(None),
            ))
            .order_by(ClickUpTaskCache.due_date)
            .limit(50)
        )
        rows = (await self._db.execute(stmt)).all()
        out = []
        for row in rows:
            task, list_name, folder_name = row[0], row[1], row[2]
            try:
                assignees = json.loads(task.assignees_json or "[]")
            except Exception:
                assignees = []
            out.append({
                "task_id": task.task_id,
                "name": task.name,
                "status": task.status,
                "status_color": task.status_color,
                "due_date": task.due_date.isoformat() if task.due_date else None,
                "assignees": [a.get("username") or "?" for a in assignees],
                "list_name": list_name,
                "folder_name": folder_name or "—",
                "url": task.url,
            })
        return out

    async def get_gantt_overview(self, space_id: str) -> list[dict]:
        """Retorna intervalo de datas (início → fim) de cada pasta, para o cronograma geral."""
        now = datetime.utcnow()
        _done = ClickUpTaskCache.status_type.in_(["done", "closed"])
        _active = ClickUpTaskCache.status_type.notin_(["done", "closed"])

        rows = (await self._db.execute(
            select(
                ClickUpFolderCache.folder_id,
                ClickUpFolderCache.name,
                func.min(
                    func.coalesce(ClickUpTaskCache.start_date, ClickUpTaskCache.date_created)
                ).label("start_date"),
                func.max(ClickUpTaskCache.due_date).label("due_date"),
                func.count(ClickUpTaskCache.task_id).label("total_tasks"),
                func.sum(case((_done, 1), else_=0)).label("completed_tasks"),
                func.sum(case(
                    (and_(
                        ClickUpTaskCache.due_date.isnot(None),
                        ClickUpTaskCache.due_date < now,
                        _active,
                    ), 1), else_=0,
                )).label("overdue_tasks"),
            )
            .join(ClickUpListCache, ClickUpListCache.folder_id == ClickUpFolderCache.folder_id)
            .join(ClickUpTaskCache, and_(
                ClickUpTaskCache.list_id == ClickUpListCache.list_id,
                _leaf_tasks_clause(),
            ))
            .where(ClickUpFolderCache.space_id == space_id)
            .group_by(ClickUpFolderCache.folder_id, ClickUpFolderCache.name)
            .order_by(func.min(func.coalesce(ClickUpTaskCache.start_date, ClickUpTaskCache.date_created)))
        )).fetchall()

        result = []
        for r in rows:
            total = r.total_tasks or 0
            completed = r.completed_tasks or 0
            overdue = r.overdue_tasks or 0
            result.append({
                "folder_id": r.folder_id,
                "name": r.name,
                "start_date": r.start_date.isoformat() if r.start_date else None,
                "due_date": r.due_date.isoformat() if r.due_date else None,
                "total_tasks": total,
                "completed_tasks": completed,
                "completion_rate": round(completed / total, 4) if total > 0 else 0.0,
                "overdue_tasks": overdue,
                "is_overdue": overdue > 0,
                "is_done": total > 0 and completed >= total,
            })
        return result

    async def get_gantt_tasks(self, list_id: str) -> list[ClickUpTaskCache]:
        stmt = (
            select(ClickUpTaskCache)
            .where(and_(
                ClickUpTaskCache.list_id == list_id,
                ClickUpTaskCache.parent_task_id.is_(None),
            ))
            .order_by(ClickUpTaskCache.due_date.nulls_last(), ClickUpTaskCache.name)
        )
        return list((await self._db.execute(stmt)).scalars().all())

    async def get_gantt_tasks_by_folder(self, folder_id: str) -> list[tuple]:
        stmt = (
            select(ClickUpTaskCache, ClickUpListCache.name.label("list_name"))
            .join(ClickUpListCache, ClickUpTaskCache.list_id == ClickUpListCache.list_id)
            .where(and_(
                ClickUpListCache.folder_id == folder_id,
                ClickUpTaskCache.parent_task_id.is_(None),
                ClickUpTaskCache.due_date.isnot(None),
            ))
            .order_by(ClickUpTaskCache.due_date)
        )
        return list((await self._db.execute(stmt)).all())

    async def get_gantt_task_subtasks(self, task_id: str) -> list[ClickUpTaskCache]:
        from sqlalchemy import or_
        stmt = (
            select(ClickUpTaskCache)
            .where(and_(
                or_(
                    ClickUpTaskCache.task_id == task_id,
                    ClickUpTaskCache.parent_task_id == task_id,
                ),
                ClickUpTaskCache.due_date.isnot(None),
            ))
            .order_by(ClickUpTaskCache.due_date)
        )
        return list((await self._db.execute(stmt)).scalars().all())

    async def get_folder_by_id(self, folder_id: str) -> ClickUpFolderCache | None:
        return (await self._db.execute(
            select(ClickUpFolderCache).where(ClickUpFolderCache.folder_id == folder_id)
        )).scalar_one_or_none()

    async def get_all_folders(self, space_id: str) -> list[ClickUpFolderCache]:
        return list((await self._db.execute(
            select(ClickUpFolderCache)
            .where(ClickUpFolderCache.space_id == space_id)
            .order_by(ClickUpFolderCache.name)
        )).scalars().all())

    async def get_folder_kpis(self, folder_id: str) -> dict:
        now = datetime.utcnow()
        _done = ClickUpTaskCache.status_type.in_(["done", "closed"])
        _active = ClickUpTaskCache.status_type.notin_(["done", "closed"])
        row = (await self._db.execute(
            select(
                func.count(ClickUpTaskCache.task_id).label("total"),
                func.sum(case((_done, 1), else_=0)).label("completed"),
                func.sum(case(
                    (and_(ClickUpTaskCache.due_date.isnot(None), ClickUpTaskCache.due_date < now, _active), 1), else_=0,
                )).label("overdue"),
                func.sum(case((ClickUpTaskCache.due_date.is_(None), 1), else_=0)).label("no_due"),
            )
            .join(ClickUpListCache, ClickUpTaskCache.list_id == ClickUpListCache.list_id)
            .where(and_(
                ClickUpListCache.folder_id == folder_id,
                _leaf_tasks_clause(),
            ))
        )).one()

        dist = {r[0] or "sem status": r[1] for r in (await self._db.execute(
            select(ClickUpTaskCache.status, func.count(ClickUpTaskCache.task_id))
            .join(ClickUpListCache, ClickUpTaskCache.list_id == ClickUpListCache.list_id)
            .where(and_(ClickUpListCache.folder_id == folder_id, _leaf_tasks_clause()))
            .group_by(ClickUpTaskCache.status)
        )).fetchall()}

        total = row.total or 0
        completed = row.completed or 0
        return {
            "total_tasks": total,
            "completed_tasks": completed,
            "completion_rate": round(completed / total, 4) if total > 0 else 0.0,
            "overdue_tasks": row.overdue or 0,
            "tasks_without_due_date": row.no_due or 0,
            "status_distribution": dist,
        }

    async def get_overdue_tasks_by_folder(self, folder_id: str, limit: int = 50) -> list[dict]:
        now = datetime.utcnow()
        stmt = (
            select(ClickUpTaskCache, ClickUpListCache.name.label("list_name"))
            .join(ClickUpListCache, ClickUpTaskCache.list_id == ClickUpListCache.list_id)
            .where(and_(
                ClickUpListCache.folder_id == folder_id,
                ClickUpTaskCache.due_date.isnot(None),
                ClickUpTaskCache.due_date < now,
                ClickUpTaskCache.status_type.notin_(["done", "closed"]),
                ClickUpTaskCache.parent_task_id.is_(None),
            ))
            .order_by(ClickUpTaskCache.due_date)
            .limit(limit)
        )
        out = []
        for row in (await self._db.execute(stmt)).all():
            task, list_name = row[0], row[1]
            try:
                assignees = json.loads(task.assignees_json or "[]")
            except Exception:
                assignees = []
            out.append({
                "task_id": task.task_id,
                "name": task.name,
                "due_date": task.due_date,
                "days_overdue": (now - task.due_date).days,
                "assignees": [a.get("username") or "?" for a in assignees],
                "list_name": list_name,
                "url": task.url,
            })
        return out

    async def get_upcoming_tasks_by_folder(self, folder_id: str, days: int = 30) -> list[dict]:
        from datetime import timedelta
        now = datetime.utcnow()
        cutoff = now + timedelta(days=days)
        stmt = (
            select(ClickUpTaskCache, ClickUpListCache.name.label("list_name"))
            .join(ClickUpListCache, ClickUpTaskCache.list_id == ClickUpListCache.list_id)
            .where(and_(
                ClickUpListCache.folder_id == folder_id,
                ClickUpTaskCache.due_date >= now,
                ClickUpTaskCache.due_date <= cutoff,
                ClickUpTaskCache.status_type.notin_(["done", "closed"]),
                ClickUpTaskCache.parent_task_id.is_(None),
            ))
            .order_by(ClickUpTaskCache.due_date)
        )
        out = []
        for row in (await self._db.execute(stmt)).all():
            task, list_name = row[0], row[1]
            try:
                assignees = json.loads(task.assignees_json or "[]")
            except Exception:
                assignees = []
            due_fmt = task.due_date.strftime("%d/%m/%Y") if task.due_date else "N/D"
            out.append({
                "task_id": task.task_id,
                "name": task.name,
                "status": task.status,
                "due_date_fmt": due_fmt,
                "assignees_str": ", ".join(a.get("username") or "?" for a in assignees) or "N/D",
                "list_name": list_name,
                "url": task.url,
            })
        return out

    async def get_assignee_stats_by_folder(self, folder_id: str) -> list[dict]:
        stmt = (
            select(ClickUpTaskCache)
            .join(ClickUpListCache, ClickUpTaskCache.list_id == ClickUpListCache.list_id)
            .where(and_(
                ClickUpListCache.folder_id == folder_id,
                _leaf_tasks_clause(),
            ))
        )
        tasks = list((await self._db.execute(stmt)).scalars().all())

        from collections import defaultdict
        now = datetime.utcnow()
        stats: dict = defaultdict(lambda: {"open": 0, "completed": 0, "overdue": 0})
        for task in tasks:
            try:
                assignees = json.loads(task.assignees_json or "[]")
            except Exception:
                assignees = []
            names = [a.get("username") for a in assignees if a.get("username")]
            is_done = task.status_type in ("done", "closed")
            is_overdue = task.due_date is not None and task.due_date < now and not is_done
            for name in names:
                if not name:
                    continue
                if is_done:
                    stats[name]["completed"] += 1
                else:
                    stats[name]["open"] += 1
                if is_overdue:
                    stats[name]["overdue"] += 1
        return [
            {"assignee": k, "open": v["open"], "completed": v["completed"], "overdue": v["overdue"]}
            for k, v in sorted(stats.items(), key=lambda x: -(x[1]["open"] + x[1]["completed"]))
        ]

    async def get_space(self, space_id: str) -> ClickUpSpaceCache | None:
        return (await self._db.execute(
            select(ClickUpSpaceCache).where(ClickUpSpaceCache.space_id == space_id)
        )).scalar_one_or_none()

    async def get_overdue_tasks_detail(self, space_id: str, limit: int = 30) -> list[dict]:
        now = datetime.utcnow()
        stmt = (
            select(
                ClickUpTaskCache,
                ClickUpListCache.name.label("list_name"),
                ClickUpFolderCache.name.label("folder_name"),
            )
            .join(ClickUpListCache, ClickUpTaskCache.list_id == ClickUpListCache.list_id)
            .outerjoin(ClickUpFolderCache, ClickUpListCache.folder_id == ClickUpFolderCache.folder_id)
            .where(and_(
                ClickUpListCache.space_id == space_id,
                ClickUpTaskCache.due_date.isnot(None),
                ClickUpTaskCache.due_date < now,
                ClickUpTaskCache.status_type.notin_(["done", "closed"]),
                ClickUpTaskCache.parent_task_id.is_(None),
            ))
            .order_by(ClickUpTaskCache.due_date)
            .limit(limit)
        )
        rows = (await self._db.execute(stmt)).all()
        out = []
        for row in rows:
            task, list_name, folder_name = row[0], row[1], row[2]
            try:
                assignees = json.loads(task.assignees_json or "[]")
            except Exception:
                assignees = []
            out.append({
                "task_id": task.task_id,
                "name": task.name,
                "due_date": task.due_date,
                "days_overdue": (now - task.due_date).days,
                "assignees": [a.get("username") or "?" for a in assignees],
                "list_name": list_name,
                "folder_name": folder_name or "—",
                "url": task.url,
            })
        return out

    async def get_tasks_by_status(
        self, space_id: str, status_filter: str | None = None, folder_id: str | None = None, limit: int = 50
    ) -> dict:
        """Retorna tarefas agrupadas por status atual. Filtra por status e/ou pasta opcionalmente."""
        conditions = [
            ClickUpListCache.space_id == space_id,
            ClickUpTaskCache.parent_task_id.is_(None),
        ]
        if folder_id:
            conditions.append(ClickUpFolderCache.folder_id == folder_id)
        if status_filter:
            from sqlalchemy import func as sqlfunc
            conditions.append(sqlfunc.lower(ClickUpTaskCache.status) == status_filter.strip().lower())

        stmt = (
            select(
                ClickUpTaskCache,
                ClickUpListCache.name.label("list_name"),
                ClickUpFolderCache.name.label("folder_name"),
            )
            .join(ClickUpListCache, ClickUpTaskCache.list_id == ClickUpListCache.list_id)
            .outerjoin(ClickUpFolderCache, ClickUpListCache.folder_id == ClickUpFolderCache.folder_id)
            .where(*conditions)
            .order_by(ClickUpTaskCache.status, ClickUpTaskCache.name)
            .limit(limit)
        )
        rows = (await self._db.execute(stmt)).all()

        by_status: dict[str, list[dict]] = {}
        for row in rows:
            task, list_name, folder_name = row[0], row[1], row[2]
            try:
                assignees = json.loads(task.assignees_json or "[]")
            except Exception:
                assignees = []
            entry = {
                "name": task.name,
                "status": task.status,
                "folder_name": folder_name or "—",
                "list_name": list_name,
                "assignees": [a.get("username") or "?" for a in assignees],
                "due_date": task.due_date.strftime("%d/%m/%Y") if task.due_date else None,
                "url": task.url,
            }
            key = (task.status or "sem status").lower()
            by_status.setdefault(key, []).append(entry)

        return {
            "filter": status_filter,
            "total": len(rows),
            "by_status": by_status,
        }

    async def get_recent_changes(self, space_id: str, since: datetime, limit: int = 40) -> dict:
        """Retorna tarefas concluídas e tarefas com progresso real (Fazendo/Revisão/
        Aprovação) desde `since`. Tarefas recém-criadas (ainda em "planejando") nunca
        aparecem aqui — só mudanças de status que representam progresso.

        O ClickUp só preenche date_closed ao arquivar — para capturar conclusões
        usa-se date_updated + status_type 'done'/'closed'.
        """
        _done_types = ("done", "closed")

        base = (
            select(
                ClickUpTaskCache,
                ClickUpListCache.name.label("list_name"),
                ClickUpFolderCache.name.label("folder_name"),
            )
            .join(ClickUpListCache, ClickUpTaskCache.list_id == ClickUpListCache.list_id)
            .outerjoin(ClickUpFolderCache, ClickUpListCache.folder_id == ClickUpFolderCache.folder_id)
            .where(
                ClickUpListCache.space_id == space_id,
                ClickUpTaskCache.parent_task_id.is_(None),
            )
        )

        def _row_to_dict(row) -> dict:
            task, list_name, folder_name = row[0], row[1], row[2]
            try:
                assignees = json.loads(task.assignees_json or "[]")
            except Exception:
                assignees = []
            return {
                "name": task.name,
                "status": task.status,
                "folder_name": folder_name or "—",
                "list_name": list_name,
                "assignees": [a.get("username") or "?" for a in assignees],
                "url": task.url,
            }

        # Tarefas concluídas no período (date_updated + status done/closed)
        completed_rows = (await self._db.execute(
            base.where(
                ClickUpTaskCache.date_updated >= since,
                ClickUpTaskCache.status_type.in_(_done_types),
            )
            .order_by(ClickUpTaskCache.date_updated.desc()).limit(limit)
        )).all()

        # Tarefas ativas atualizadas no período (exclui done/closed) — filtradas
        # abaixo para só manter status de progresso real
        active_rows = (await self._db.execute(
            base.where(
                ClickUpTaskCache.date_updated >= since,
                ClickUpTaskCache.status_type.notin_(_done_types),
            )
            .order_by(ClickUpTaskCache.date_updated.desc()).limit(limit * 3)
        )).all()

        # Agrupa por status para que a IA consiga responder "quais entraram em X"
        by_status: dict[str, list[dict]] = {}
        for row in active_rows:
            task = row[0]
            if _norm_status(task.status) not in _REPORTABLE_ACTIVE_STATUSES:
                continue
            status_name = (task.status or "sem status").lower()
            by_status.setdefault(status_name, []).append(_row_to_dict(row))

        return {
            "completed": [_row_to_dict(r) for r in completed_rows],
            "by_status": by_status,
        }

    async def get_last_refresh(self) -> CacheRefreshLog | None:
        return (await self._db.execute(
            select(CacheRefreshLog).order_by(CacheRefreshLog.created_at.desc()).limit(1)
        )).scalar_one_or_none()

    async def insert_refresh_log(
        self,
        space_id: str,
        trigger: str,
        status: str,
        folders_updated: int = 0,
        lists_updated: int = 0,
        tasks_updated: int = 0,
        duration_ms: int = 0,
        error_message: str | None = None,
    ) -> None:
        self._db.add(CacheRefreshLog(
            space_id=space_id,
            trigger=trigger,
            status=status,
            folders_updated=folders_updated,
            lists_updated=lists_updated,
            tasks_updated=tasks_updated,
            duration_ms=duration_ms,
            error_message=error_message,
        ))
        await self._db.commit()

    # ─── Discipline Weights ───────────────────────────────────────────────────

    async def get_discipline_weights(self, folder_id: str) -> dict[str, float]:
        rows = (await self._db.execute(
            select(DisciplineWeight)
            .join(ClickUpListCache, ClickUpListCache.list_id == DisciplineWeight.list_id)
            .where(ClickUpListCache.folder_id == folder_id)
        )).scalars().all()
        return {r.list_id: r.weight for r in rows}

    async def set_discipline_weights(self, weights: dict[str, float]) -> None:
        for list_id, weight in weights.items():
            stmt = sqlite_insert(DisciplineWeight).values(
                list_id=list_id, weight=weight, updated_at=datetime.utcnow()
            )
            await self._db.execute(stmt.on_conflict_do_update(
                index_elements=["list_id"],
                set_={"weight": stmt.excluded.weight, "updated_at": stmt.excluded.updated_at},
            ))
        await self._db.commit()

    async def delete_discipline_weights(self, folder_id: str) -> None:
        list_ids = [
            r[0] for r in (await self._db.execute(
                select(ClickUpListCache.list_id).where(ClickUpListCache.folder_id == folder_id)
            )).all()
        ]
        if list_ids:
            await self._db.execute(
                delete(DisciplineWeight).where(DisciplineWeight.list_id.in_(list_ids))
            )
            await self._db.commit()

    async def get_period_updates(self, space_id: str, since: datetime, until: datetime) -> list[dict]:
        """Tasks + subtasks concluídas ou com progresso real (Fazendo/Revisão/Aprovação/
        Concluído) no período, agrupadas por pasta. Tarefas recém-criadas que ainda
        estão em "planejando" (ou qualquer outro status fora dessa lista) são
        descartadas — não aparecem nos relatórios como se fossem uma atualização."""
        import json as _json
        import re as _re
        from sqlalchemy import or_
        from sqlalchemy.orm import aliased

        def _cat(task) -> tuple[str, object] | None:
            if task.date_closed is not None and since <= task.date_closed <= until:
                return "concluded", task.date_closed
            if (
                _norm_status(task.status) in _REPORTABLE_UPDATE_STATUSES
                and task.date_updated is not None
                and since <= task.date_updated <= until
            ):
                return "updated", task.date_updated
            return None

        def _asgn(task) -> str:
            try:
                a = _json.loads(task.assignees_json or "[]")
            except Exception:
                a = []
            return ", ".join(x.get("username") or "?" for x in a) or "N/D"

        def _desc(task) -> str:
            raw = (task.description or "").strip()
            clean = _re.sub(r"<[^>]+>", " ", raw).strip()
            return clean[:200] if len(clean) > 200 else clean

        date_cond = or_(
            and_(ClickUpTaskCache.date_closed >= since, ClickUpTaskCache.date_closed <= until),
            and_(ClickUpTaskCache.date_created >= since, ClickUpTaskCache.date_created <= until),
            and_(ClickUpTaskCache.date_updated >= since, ClickUpTaskCache.date_updated <= until),
        )

        # ── Parent tasks updated in period ────────────────────────────────────
        parent_rows = (await self._db.execute(
            select(
                ClickUpTaskCache,
                ClickUpListCache.name.label("list_name"),
                ClickUpFolderCache.folder_id.label("folder_id"),
                ClickUpFolderCache.name.label("folder_name"),
            )
            .join(ClickUpListCache, ClickUpTaskCache.list_id == ClickUpListCache.list_id)
            .join(ClickUpFolderCache, ClickUpListCache.folder_id == ClickUpFolderCache.folder_id)
            .where(and_(
                ClickUpListCache.space_id == space_id,
                ClickUpTaskCache.parent_task_id.is_(None),
                date_cond,
            ))
            .order_by(ClickUpFolderCache.name, ClickUpListCache.name, ClickUpTaskCache.name)
        )).all()

        parents: dict[str, dict] = {}
        folders: dict[str, dict] = {}

        for row in parent_rows:
            task, list_name, folder_id, folder_name = row[0], row[1], row[2], row[3]
            cat_result = _cat(task)
            if cat_result is None:
                continue
            cat, date_ref = cat_result
            t = {
                "task_id": task.task_id,
                "name": task.name or "",
                "status": task.status or "",
                "list_name": list_name or "",
                "assignees_str": _asgn(task),
                "description": _desc(task),
                "date_ref": date_ref,
                "category": cat,
                "subtasks": [],
            }
            parents[task.task_id] = t
            if folder_id not in folders:
                folders[folder_id] = {"folder_id": folder_id, "folder_name": folder_name or "", "tasks": []}
            folders[folder_id]["tasks"].append(t)

        # ── Subtasks updated in period (self-join to get parent name) ─────────
        ParentAlias = aliased(ClickUpTaskCache, name="parent_alias")
        sub_rows = (await self._db.execute(
            select(
                ClickUpTaskCache,
                ParentAlias.task_id.label("par_id"),
                ParentAlias.name.label("par_name"),
                ParentAlias.status.label("par_status"),
                ClickUpListCache.name.label("list_name"),
                ClickUpFolderCache.folder_id.label("folder_id"),
                ClickUpFolderCache.name.label("folder_name"),
            )
            .join(ParentAlias, ClickUpTaskCache.parent_task_id == ParentAlias.task_id)
            .join(ClickUpListCache, ClickUpTaskCache.list_id == ClickUpListCache.list_id)
            .join(ClickUpFolderCache, ClickUpListCache.folder_id == ClickUpFolderCache.folder_id)
            .where(and_(
                ClickUpListCache.space_id == space_id,
                ClickUpTaskCache.parent_task_id.isnot(None),
                date_cond,
            ))
            .order_by(ClickUpFolderCache.name, ClickUpListCache.name, ParentAlias.name, ClickUpTaskCache.name)
        )).all()

        # Containers criados sob demanda para tarefas-pai que não tiveram atualização
        # reportável própria, mas cujas subtarefas tiveram — mantém a mesma estrutura
        # aninhada (pai + subtarefas indentadas) em vez de uma linha solta "Pai > Sub".
        parent_shells: dict[tuple[str, str], dict] = {}

        for row in sub_rows:
            task, par_id, par_name, par_status, list_name, folder_id, folder_name = (
                row[0], row[1], row[2], row[3], row[4], row[5], row[6]
            )
            cat_result = _cat(task)
            if cat_result is None:
                continue
            cat, date_ref = cat_result
            sub = {
                "task_id": task.task_id,
                "name": task.name or "",
                "status": task.status or "",
                "assignees_str": _asgn(task),
                "date_ref": date_ref,
                "category": cat,
            }
            if par_id in parents:
                # Attach to existing parent entry
                parents[par_id]["subtasks"].append(sub)
                continue

            shell_key = (par_id, cat)
            if shell_key not in parent_shells:
                if folder_id not in folders:
                    folders[folder_id] = {"folder_id": folder_id, "folder_name": folder_name or "", "tasks": []}
                shell = {
                    "task_id": par_id,
                    "name": par_name or "",
                    "status": par_status or "",
                    "list_name": list_name or "",
                    "assignees_str": "N/D",
                    "description": "",
                    "date_ref": date_ref,
                    "category": cat,
                    "subtasks": [],
                }
                parent_shells[shell_key] = shell
                folders[folder_id]["tasks"].append(shell)
            parent_shells[shell_key]["subtasks"].append(sub)

        return [f for f in folders.values() if f["tasks"]]

    async def get_folder_tasks_for_evolution(self, folder_id: str) -> list[dict]:
        """
        Retorna listas com tarefas pai (sem subtarefas) incluindo datas de criação e
        fechamento — usado para reconstruir a curva de evolução temporal ponderada.
        """
        lists = await self.get_lists_with_metrics(folder_id)
        result: list[dict] = []
        for lst in lists:
            parent_tasks = await self.get_tasks_by_list(lst["list_id"], include_subtasks=False)
            tasks_data = []
            for t in parent_tasks:
                is_done = t.status_type in ("done", "closed")
                tasks_data.append({
                    "task_id": t.task_id,
                    "name": t.name or "",
                    "is_done": is_done,
                    "date_created": t.date_created,
                    "date_closed": t.date_closed or (t.date_updated if is_done else None),
                    "subtasks": [],
                })
            result.append({
                "list_id": lst["list_id"],
                "name": lst["name"],
                "total_tasks": lst["total_tasks"],
                "completed_tasks": lst["completed_tasks"],
                "overdue_tasks": lst["overdue_tasks"],
                "tasks": tasks_data,
            })
        return result

    async def get_tasks_for_weighted_progress(self, folder_id: str) -> list[dict]:
        """
        Retorna listas com tarefas e subtarefas para cálculo ponderado em dois níveis.
        Cada lista inclui: list_id, name, total_tasks, completed_tasks, overdue_tasks,
        tasks=[{task_id, name, is_done, subtasks=[{name, is_done}]}]
        """
        now = datetime.utcnow()
        lists = await self.get_lists_with_metrics(folder_id)
        result: list[dict] = []
        for lst in lists:
            all_tasks = await self.get_tasks_by_list(lst["list_id"], include_subtasks=True)
            parents: dict[str, dict] = {}
            subtasks_by_parent: dict[str, list] = {}
            for t in all_tasks:
                is_done = t.status_type in ("done", "closed")
                if t.parent_task_id is None:
                    parents[t.task_id] = {
                        "task_id": t.task_id,
                        "name": t.name or "",
                        "is_done": is_done,
                    }
                else:
                    subtasks_by_parent.setdefault(t.parent_task_id, []).append({
                        "task_id": t.task_id,
                        "name": t.name or "",
                        "is_done": is_done,
                    })
            tasks_with_subs = []
            for tid, task_data in parents.items():
                tasks_with_subs.append({**task_data, "subtasks": subtasks_by_parent.get(tid, [])})
            # overdue count for the list
            _active = ClickUpTaskCache.status_type.notin_(["done", "closed"])
            overdue_count = (await self._db.execute(
                select(func.count(ClickUpTaskCache.task_id))
                .where(and_(
                    ClickUpTaskCache.list_id == lst["list_id"],
                    ClickUpTaskCache.parent_task_id.is_(None),
                    ClickUpTaskCache.due_date.isnot(None),
                    ClickUpTaskCache.due_date < now,
                    _active,
                ))
            )).scalar() or 0
            result.append({
                "list_id": lst["list_id"],
                "name": lst["name"],
                "total_tasks": lst["total_tasks"],
                "completed_tasks": lst["completed_tasks"],
                "overdue_tasks": overdue_count,
                "tasks": tasks_with_subs,
            })
        return result

    async def get_weighted_progress(self, folder_id: str) -> dict:
        """Calcula progresso ponderado por disciplina para uma pasta."""
        lists = await self.get_lists_with_metrics(folder_id)
        weights = await self.get_discipline_weights(folder_id)
        total_weight = sum(weights.get(l["list_id"], 0.0) for l in lists)
        disciplines = []
        for lst in lists:
            w = weights.get(lst["list_id"])
            contribution = round(w * lst["completion_rate"], 4) if w is not None else None
            disciplines.append({
                "list_id": lst["list_id"],
                "name": lst["name"],
                "weight": w,
                "weight_pct": round(w * 100, 1) if w is not None else None,
                "completion_rate": lst["completion_rate"],
                "total_tasks": lst["total_tasks"],
                "completed_tasks": lst["completed_tasks"],
                "overdue_tasks": lst["overdue_tasks"],
                "weighted_contribution": contribution,
            })
        if total_weight > 0:
            weighted_progress = sum(
                weights.get(l["list_id"], 0.0) * l["completion_rate"] for l in lists
            ) / total_weight
        else:
            weighted_progress = None
        simple_n = len(lists)
        simple_progress = (
            sum(l["completion_rate"] for l in lists) / simple_n if simple_n else 0.0
        )
        return {
            "disciplines": disciplines,
            "weights_configured": total_weight > 0,
            "weights_sum": round(total_weight * 100, 1),
            "weighted_progress": round(weighted_progress, 4) if weighted_progress is not None else None,
            "simple_progress": round(simple_progress, 4),
        }

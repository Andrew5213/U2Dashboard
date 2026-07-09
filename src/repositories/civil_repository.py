from datetime import date, datetime
from sqlalchemy import select, func, delete, and_
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.civil_models import (
    CivilProject, CivilSite, CivilDailyReport,
    CivilResource, CivilActivity, CivilMaterial, CivilOccurrence,
    CivilQualityCheck, CivilPhoto, CivilNextDayPlan, CivilSignature,
)
from src.models.progress_models import (
    CivilProgressProfile, CivilProgressCategory, CivilProgressActivityDef,
    CivilSiteActivityQty, CivilProgressMeasurement,
)


class CivilRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ─── Projects ────────────────────────────────────────────────────────────

    async def create_project(self, name: str, description: str | None = None) -> CivilProject:
        proj = CivilProject(name=name, description=description)
        self._db.add(proj)
        await self._db.flush()
        return proj

    async def get_project(self, project_id: int) -> CivilProject | None:
        return await self._db.get(CivilProject, project_id)

    async def list_projects(self) -> list[CivilProject]:
        result = await self._db.execute(select(CivilProject).order_by(CivilProject.name))
        return list(result.scalars())

    async def update_project(self, project_id: int, name: str, description: str | None) -> CivilProject | None:
        proj = await self._db.get(CivilProject, project_id)
        if not proj:
            return None
        proj.name = name
        proj.description = description
        await self._db.flush()
        return proj

    # ─── Sites ───────────────────────────────────────────────────────────────

    async def create_site(
        self, project_id: int, name: str,
        province: str | None = None, profile_id: int | None = None,
        clickup_folder_id: str | None = None,
    ) -> CivilSite:
        site = CivilSite(
            project_id=project_id, name=name, province=province,
            profile_id=profile_id, clickup_folder_id=clickup_folder_id,
        )
        self._db.add(site)
        await self._db.flush()
        return site

    async def get_site(self, site_id: int) -> CivilSite | None:
        return await self._db.get(CivilSite, site_id)

    async def list_sites(self, project_id: int) -> list[CivilSite]:
        result = await self._db.execute(
            select(CivilSite)
            .where(CivilSite.project_id == project_id)
            .order_by(CivilSite.name)
        )
        return list(result.scalars())

    async def list_all_sites(self) -> list[CivilSite]:
        result = await self._db.execute(select(CivilSite).order_by(CivilSite.name))
        return list(result.scalars())

    async def update_site(
        self, site_id: int, name: str | None = None,
        province: str | None = None, profile_id: int | None = None,
    ) -> CivilSite | None:
        site = await self._db.get(CivilSite, site_id)
        if not site:
            return None
        if name is not None:
            site.name = name
        if province is not None:
            site.province = province
        site.profile_id = profile_id
        await self._db.flush()
        return site

    # ─── Daily Reports ───────────────────────────────────────────────────────

    async def next_report_number(self, site_id: int) -> int:
        result = await self._db.execute(
            select(func.max(CivilDailyReport.report_number))
            .where(CivilDailyReport.site_id == site_id)
        )
        return (result.scalar() or 0) + 1

    async def create_report(self, data: dict) -> CivilDailyReport:
        report = CivilDailyReport(**data)
        self._db.add(report)
        await self._db.flush()
        return report

    async def get_report(self, report_id: int) -> CivilDailyReport | None:
        return await self._db.get(CivilDailyReport, report_id)

    async def get_report_by_site_date(self, site_id: int, report_date: date) -> CivilDailyReport | None:
        result = await self._db.execute(
            select(CivilDailyReport).where(
                CivilDailyReport.site_id == site_id,
                CivilDailyReport.date == report_date,
            )
        )
        return result.scalar_one_or_none()

    async def list_reports(
        self, site_id: int | None = None, report_date: date | None = None,
        project_id: int | None = None,
        start_date: date | None = None, end_date: date | None = None,
    ) -> list[CivilDailyReport]:
        q = select(CivilDailyReport)
        if site_id:
            q = q.where(CivilDailyReport.site_id == site_id)
        if report_date:
            q = q.where(CivilDailyReport.date == report_date)
        if project_id:
            q = q.where(CivilDailyReport.project_id == project_id)
        if start_date:
            q = q.where(CivilDailyReport.date >= start_date)
        if end_date:
            q = q.where(CivilDailyReport.date <= end_date)
        q = q.order_by(CivilDailyReport.date.asc(), CivilDailyReport.report_number.asc())
        result = await self._db.execute(q)
        return list(result.scalars())

    async def list_reports_for_project_day(
        self, project_id: int, report_date: date,
    ) -> list[CivilDailyReport]:
        result = await self._db.execute(
            select(CivilDailyReport)
            .where(
                CivilDailyReport.project_id == project_id,
                CivilDailyReport.date == report_date,
            )
            .order_by(CivilDailyReport.site_id)
        )
        return list(result.scalars())

    async def update_report(self, report_id: int, data: dict) -> CivilDailyReport | None:
        report = await self._db.get(CivilDailyReport, report_id)
        if not report:
            return None
        for key, value in data.items():
            setattr(report, key, value)
        await self._db.flush()
        return report

    # ─── Child table helpers ─────────────────────────────────────────────────

    async def _delete_by_report(self, model, report_id: int) -> None:
        await self._db.execute(delete(model).where(model.report_id == report_id))

    async def _list_by_report(self, model, report_id: int) -> list:
        result = await self._db.execute(
            select(model).where(model.report_id == report_id)
        )
        return list(result.scalars())

    async def replace_resources(self, report_id: int, rows: list[dict]) -> list[CivilResource]:
        await self._delete_by_report(CivilResource, report_id)
        objs = [CivilResource(report_id=report_id, **r) for r in rows]
        self._db.add_all(objs)
        await self._db.flush()
        return objs

    async def get_resources(self, report_id: int) -> list[CivilResource]:
        return await self._list_by_report(CivilResource, report_id)

    async def replace_activities(self, report_id: int, rows: list[dict]) -> list[CivilActivity]:
        await self._delete_by_report(CivilActivity, report_id)
        objs = [CivilActivity(report_id=report_id, **r) for r in rows]
        self._db.add_all(objs)
        await self._db.flush()
        return objs

    async def get_activities(self, report_id: int) -> list[CivilActivity]:
        return await self._list_by_report(CivilActivity, report_id)

    async def replace_materials(self, report_id: int, rows: list[dict]) -> list[CivilMaterial]:
        await self._delete_by_report(CivilMaterial, report_id)
        objs = [CivilMaterial(report_id=report_id, **r) for r in rows]
        self._db.add_all(objs)
        await self._db.flush()
        return objs

    async def get_materials(self, report_id: int) -> list[CivilMaterial]:
        return await self._list_by_report(CivilMaterial, report_id)

    async def replace_occurrences(self, report_id: int, rows: list[dict]) -> list[CivilOccurrence]:
        await self._delete_by_report(CivilOccurrence, report_id)
        objs = [CivilOccurrence(report_id=report_id, **r) for r in rows]
        self._db.add_all(objs)
        await self._db.flush()
        return objs

    async def get_occurrences(self, report_id: int) -> list[CivilOccurrence]:
        return await self._list_by_report(CivilOccurrence, report_id)

    async def replace_quality_checks(self, report_id: int, rows: list[dict]) -> list[CivilQualityCheck]:
        await self._delete_by_report(CivilQualityCheck, report_id)
        objs = [CivilQualityCheck(report_id=report_id, **r) for r in rows]
        self._db.add_all(objs)
        await self._db.flush()
        return objs

    async def get_quality_checks(self, report_id: int) -> list[CivilQualityCheck]:
        return await self._list_by_report(CivilQualityCheck, report_id)

    async def add_photo(self, report_id: int, photo_data: dict) -> CivilPhoto:
        result = await self._db.execute(
            select(func.max(CivilPhoto.photo_number)).where(CivilPhoto.report_id == report_id)
        )
        photo_data = dict(photo_data)
        photo_data["photo_number"] = (result.scalar() or 0) + 1
        photo = CivilPhoto(report_id=report_id, **photo_data)
        self._db.add(photo)
        await self._db.flush()
        return photo

    async def get_photos(self, report_id: int) -> list[CivilPhoto]:
        return await self._list_by_report(CivilPhoto, report_id)

    async def replace_next_day_plans(self, report_id: int, rows: list[dict]) -> list[CivilNextDayPlan]:
        await self._delete_by_report(CivilNextDayPlan, report_id)
        objs = [CivilNextDayPlan(report_id=report_id, **r) for r in rows]
        self._db.add_all(objs)
        await self._db.flush()
        return objs

    async def get_next_day_plans(self, report_id: int) -> list[CivilNextDayPlan]:
        return await self._list_by_report(CivilNextDayPlan, report_id)

    async def replace_signatures(self, report_id: int, rows: list[dict]) -> list[CivilSignature]:
        await self._delete_by_report(CivilSignature, report_id)
        objs = [CivilSignature(report_id=report_id, **r) for r in rows]
        self._db.add_all(objs)
        await self._db.flush()
        return objs

    async def get_signatures(self, report_id: int) -> list[CivilSignature]:
        return await self._list_by_report(CivilSignature, report_id)

    # ─── Progress Profiles ───────────────────────────────────────────────────

    async def create_profile(self, name: str) -> CivilProgressProfile:
        profile = CivilProgressProfile(name=name)
        self._db.add(profile)
        await self._db.flush()
        return profile

    async def get_profile(self, profile_id: int) -> CivilProgressProfile | None:
        return await self._db.get(CivilProgressProfile, profile_id)

    async def list_profiles(self) -> list[CivilProgressProfile]:
        result = await self._db.execute(select(CivilProgressProfile).order_by(CivilProgressProfile.name))
        return list(result.scalars())

    # ─── Progress Categories ─────────────────────────────────────────────────

    async def create_category(
        self, profile_id: int, name: str, weight: float, sort_order: int = 0,
    ) -> CivilProgressCategory:
        cat = CivilProgressCategory(
            profile_id=profile_id, name=name, weight=weight, sort_order=sort_order
        )
        self._db.add(cat)
        await self._db.flush()
        return cat

    async def get_category(self, category_id: int) -> CivilProgressCategory | None:
        return await self._db.get(CivilProgressCategory, category_id)

    async def get_categories(self, profile_id: int) -> list[CivilProgressCategory]:
        result = await self._db.execute(
            select(CivilProgressCategory)
            .where(CivilProgressCategory.profile_id == profile_id)
            .order_by(CivilProgressCategory.sort_order, CivilProgressCategory.name)
        )
        return list(result.scalars())

    async def update_category(
        self, category_id: int, name: str | None = None, weight: float | None = None,
    ) -> CivilProgressCategory | None:
        cat = await self._db.get(CivilProgressCategory, category_id)
        if not cat:
            return None
        if name is not None:
            cat.name = name
        if weight is not None:
            cat.weight = weight
        await self._db.flush()
        return cat

    async def delete_category(self, category_id: int) -> bool:
        cat = await self._db.get(CivilProgressCategory, category_id)
        if not cat:
            return False
        await self._db.delete(cat)
        await self._db.flush()
        return True

    # ─── Activity Definitions ─────────────────────────────────────────────────

    async def create_activity_def(
        self, category_id: int, name: str, unit: str | None = None, sort_order: int = 0,
    ) -> CivilProgressActivityDef:
        act = CivilProgressActivityDef(
            category_id=category_id, name=name, unit=unit, sort_order=sort_order
        )
        self._db.add(act)
        await self._db.flush()
        return act

    async def get_activity_defs(self, category_id: int) -> list[CivilProgressActivityDef]:
        result = await self._db.execute(
            select(CivilProgressActivityDef)
            .where(CivilProgressActivityDef.category_id == category_id)
            .order_by(CivilProgressActivityDef.sort_order, CivilProgressActivityDef.name)
        )
        return list(result.scalars())

    async def get_activity_defs_for_profile(
        self, profile_id: int,
    ) -> list[tuple[CivilProgressActivityDef, CivilProgressCategory]]:
        result = await self._db.execute(
            select(CivilProgressActivityDef, CivilProgressCategory)
            .join(CivilProgressCategory)
            .where(CivilProgressCategory.profile_id == profile_id)
            .order_by(CivilProgressCategory.sort_order, CivilProgressActivityDef.sort_order)
        )
        return list(result.all())

    async def delete_activity_def(self, activity_def_id: int) -> bool:
        act = await self._db.get(CivilProgressActivityDef, activity_def_id)
        if not act:
            return False
        await self._db.delete(act)
        await self._db.flush()
        return True

    # ─── Site Activity Quantities ─────────────────────────────────────────────

    async def upsert_site_activity_qty(
        self, site_id: int, activity_def_id: int, total_qty: float,
    ) -> None:
        stmt = sqlite_insert(CivilSiteActivityQty).values(
            site_id=site_id, activity_def_id=activity_def_id, total_qty=total_qty,
        )
        await self._db.execute(stmt.on_conflict_do_update(
            index_elements=["site_id", "activity_def_id"],
            set_={"total_qty": stmt.excluded.total_qty},
        ))

    async def get_site_activity_qtys(self, site_id: int) -> dict[int, float]:
        result = await self._db.execute(
            select(CivilSiteActivityQty).where(CivilSiteActivityQty.site_id == site_id)
        )
        return {row.activity_def_id: row.total_qty for row in result.scalars()}

    # ─── Progress Measurements ────────────────────────────────────────────────

    async def upsert_measurement(
        self, site_id: int, activity_def_id: int, mdate: date,
        qty_yesterday: float, qty_today: float,
        marco: int | None = None, notes: str | None = None,
    ) -> None:
        stmt = sqlite_insert(CivilProgressMeasurement).values(
            site_id=site_id,
            activity_def_id=activity_def_id,
            date=mdate,
            qty_yesterday=qty_yesterday,
            qty_today=qty_today,
            marco=marco,
            notes=notes,
        )
        await self._db.execute(stmt.on_conflict_do_update(
            index_elements=["site_id", "activity_def_id", "date"],
            set_={
                "qty_yesterday": stmt.excluded.qty_yesterday,
                "qty_today": stmt.excluded.qty_today,
                "marco": stmt.excluded.marco,
                "notes": stmt.excluded.notes,
            },
        ))

    async def get_measurements_for_site_date(
        self, site_id: int, mdate: date,
    ) -> list[CivilProgressMeasurement]:
        result = await self._db.execute(
            select(CivilProgressMeasurement)
            .where(
                CivilProgressMeasurement.site_id == site_id,
                CivilProgressMeasurement.date == mdate,
            )
            .execution_options(populate_existing=True)
        )
        return list(result.scalars())

    async def get_measurements_for_date(self, mdate: date) -> list[CivilProgressMeasurement]:
        result = await self._db.execute(
            select(CivilProgressMeasurement)
            .where(CivilProgressMeasurement.date == mdate)
            .execution_options(populate_existing=True)
        )
        return list(result.scalars())

    async def get_last_measurement_qty(
        self, site_id: int, activity_def_id: int, before_date: date,
    ) -> float:
        """Retorna qty_today da medição mais recente antes de before_date (ou 0 se não houver)."""
        result = await self._db.execute(
            select(CivilProgressMeasurement.qty_today)
            .where(
                CivilProgressMeasurement.site_id == site_id,
                CivilProgressMeasurement.activity_def_id == activity_def_id,
                CivilProgressMeasurement.date < before_date,
            )
            .order_by(CivilProgressMeasurement.date.desc())
            .limit(1)
        )
        val = result.scalar()
        return float(val) if val is not None else 0.0

    async def get_last_measurement(
        self, site_id: int, activity_def_id: int, before_date: date,
    ) -> CivilProgressMeasurement | None:
        """Retorna a medição mais recente antes de before_date (ou None se não houver)."""
        result = await self._db.execute(
            select(CivilProgressMeasurement)
            .where(
                CivilProgressMeasurement.site_id == site_id,
                CivilProgressMeasurement.activity_def_id == activity_def_id,
                CivilProgressMeasurement.date < before_date,
            )
            .order_by(CivilProgressMeasurement.date.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def get_measurement_for_date(
        self, site_id: int, activity_def_id: int, mdate: date,
    ) -> CivilProgressMeasurement | None:
        result = await self._db.execute(
            select(CivilProgressMeasurement)
            .where(
                CivilProgressMeasurement.site_id == site_id,
                CivilProgressMeasurement.activity_def_id == activity_def_id,
                CivilProgressMeasurement.date == mdate,
            )
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def get_site_activity_catalog(self, site_id: int) -> list[dict]:
        """Retorna todas as activity_defs do perfil do site, com total_qty para aquele site."""
        stmt = (
            select(
                CivilProgressActivityDef.id,
                CivilProgressActivityDef.name,
                CivilProgressActivityDef.unit,
                CivilProgressActivityDef.sort_order,
                CivilProgressCategory.id.label("category_id"),
                CivilProgressCategory.name.label("category_name"),
                CivilProgressCategory.weight,
                CivilSiteActivityQty.total_qty,
            )
            .join(CivilProgressCategory, CivilProgressActivityDef.category_id == CivilProgressCategory.id)
            .join(CivilProgressProfile, CivilProgressCategory.profile_id == CivilProgressProfile.id)
            .join(
                CivilSite,
                and_(CivilSite.profile_id == CivilProgressProfile.id, CivilSite.id == site_id),
            )
            .outerjoin(
                CivilSiteActivityQty,
                and_(
                    CivilSiteActivityQty.activity_def_id == CivilProgressActivityDef.id,
                    CivilSiteActivityQty.site_id == site_id,
                ),
            )
            .order_by(CivilProgressCategory.sort_order, CivilProgressActivityDef.sort_order)
        )
        result = await self._db.execute(stmt)
        return [
            {
                "id": r.id,
                "name": r.name,
                "unit": r.unit,
                "category_id": r.category_id,
                "category_name": r.category_name,
                "weight": r.weight,
                "total_qty": r.total_qty,
            }
            for r in result.all()
        ]

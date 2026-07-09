import os
import uuid
from datetime import date as _date, datetime
from sqlalchemy.ext.asyncio import AsyncSession
from src.repositories.civil_repository import CivilRepository
from src.models.civil_models import (
    CivilActivity,
    CivilDailyReport,
    CIVIL_QUALITY_CHECKS,
    CIVIL_SIGNATURE_ROLES,
)


ACTIVITY_STATUS_COMPLETED = "Concluído"
ACTIVITY_STATUS_IN_PROGRESS = "Em curso"
ACTIVITY_STATUS_RESTRICTED = ("Suspenso", "Atrasado")


class CivilService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = CivilRepository(db)

    async def create_report(self, payload: dict) -> dict:
        """
        Cria um RDO completo com todas as tabelas filhas.
        Gera número sequencial, auto-cria checklist e assinaturas.
        Atividades com activity_def_id alimentam automaticamente as medições de progresso.
        """
        data = dict(payload)
        site_id = data["site_id"]

        resources = data.pop("resources", [])
        activities = data.pop("activities", [])
        materials = data.pop("materials", [])
        occurrences = data.pop("occurrences", [])
        quality_checks = data.pop("quality_checks", [])
        next_day_plans = data.pop("next_day_plans", [])
        signatures = data.pop("signatures", [])

        data["report_number"] = await self._repo.next_report_number(site_id)

        # Propaga project_id automaticamente a partir do site
        site = await self._repo.get_site(site_id)
        if site and "project_id" not in data:
            data["project_id"] = site.project_id

        report = await self._repo.create_report(data)

        if resources:
            await self._repo.replace_resources(report.id, resources)

        if activities:
            saved_acts = await self._repo.replace_activities(report.id, activities)
            await self._auto_fill_measurements(site_id, report.date, saved_acts)

        if materials:
            await self._repo.replace_materials(report.id, materials)

        if occurrences:
            await self._repo.replace_occurrences(report.id, occurrences)

        # Auto-create missing quality check rows
        provided_types = {q.get("check_type") for q in quality_checks}
        for ct in CIVIL_QUALITY_CHECKS:
            if ct not in provided_types:
                quality_checks.append({"check_type": ct, "result": None, "observations": None})
        await self._repo.replace_quality_checks(report.id, quality_checks)

        if next_day_plans:
            await self._repo.replace_next_day_plans(report.id, next_day_plans)

        # Auto-create missing signature rows
        provided_roles = {s.get("role") for s in signatures}
        for role in CIVIL_SIGNATURE_ROLES:
            if role not in provided_roles:
                signatures.append({"role": role, "name": None, "confirmed_at": None})
        await self._repo.replace_signatures(report.id, signatures)

        return await self.get_full_report(report.id)  # type: ignore[return-value]

    async def _auto_fill_measurements(
        self,
        site_id: int,
        report_date: _date,
        activities: list[CivilActivity],
    ) -> None:
        """Para cada atividade com activity_def_id, upserta a medição de progresso.
        Regra de precedência: maior valor de qty_today ganha."""
        for act in activities:
            if act.activity_def_id is None or act.qty_day is None:
                continue
            qty_yesterday = await self._repo.get_last_measurement_qty(
                site_id, act.activity_def_id, report_date
            )
            qty_today_auto = qty_yesterday + act.qty_day
            existing = await self._repo.get_measurement_for_date(
                site_id, act.activity_def_id, report_date
            )
            if existing is None or qty_today_auto > existing.qty_today:
                await self._repo.upsert_measurement(
                    site_id=site_id,
                    activity_def_id=act.activity_def_id,
                    mdate=report_date,
                    qty_yesterday=qty_yesterday,
                    qty_today=qty_today_auto,
                )

    async def get_full_report(self, report_id: int) -> dict | None:
        report = await self._repo.get_report(report_id)
        if not report:
            return None

        resources = await self._repo.get_resources(report_id)
        activities = await self._repo.get_activities(report_id)
        materials = await self._repo.get_materials(report_id)
        occurrences = await self._repo.get_occurrences(report_id)
        quality_checks = await self._repo.get_quality_checks(report_id)
        photos = await self._repo.get_photos(report_id)
        next_day_plans = await self._repo.get_next_day_plans(report_id)
        signatures = await self._repo.get_signatures(report_id)

        total_personnel = sum(r.quantity for r in resources)
        activities_completed = sum(1 for a in activities if a.status == ACTIVITY_STATUS_COMPLETED)
        activities_in_progress = sum(1 for a in activities if a.status == ACTIVITY_STATUS_IN_PROGRESS)
        restrictions_count = sum(1 for a in activities if a.status in ACTIVITY_STATUS_RESTRICTED)

        return {
            "id": report.id,
            "site_id": report.site_id,
            "report_number": report.report_number,
            "date": report.date.isoformat(),
            "province": report.province,
            "local_site": report.local_site,
            "responsible": report.responsible,
            "contractor": report.contractor,
            "supervisor": report.supervisor,
            "weather_conditions": report.weather_conditions,
            "general_situation": report.general_situation,
            "start_time": report.start_time,
            "end_time": report.end_time,
            "active_fronts": report.active_fronts,
            "activities_completed": activities_completed,
            "activities_in_progress": activities_in_progress,
            "restrictions_count": restrictions_count,
            "total_personnel": total_personnel,
            "safety_situation": report.safety_situation,
            "quality_situation": report.quality_situation,
            "short_comment": report.short_comment,
            "daily_conclusion": report.daily_conclusion,
            "created_at": report.created_at.isoformat(),
            "updated_at": report.updated_at.isoformat(),
            "resources": [
                {"id": r.id, "discipline": r.discipline, "quantity": r.quantity, "observations": r.observations}
                for r in resources
            ],
            "activities": [
                {
                    "id": a.id,
                    "activity_def_id": a.activity_def_id,
                    "front_site": a.front_site,
                    "civil_category": a.civil_category,
                    "activity_description": a.activity_description,
                    "unit": a.unit,
                    "qty_day": a.qty_day,
                    "status": a.status,
                    "observations": a.observations,
                }
                for a in activities
            ],
            "materials": [
                {
                    "id": m.id, "material_name": m.material_name, "unit": m.unit,
                    "qty_received": m.qty_received, "qty_applied": m.qty_applied,
                    "balance": round(m.qty_received - m.qty_applied, 4),
                    "observations": m.observations,
                }
                for m in materials
            ],
            "occurrences": [
                {
                    "id": o.id, "occurrence_type": o.occurrence_type, "description": o.description,
                    "impact": o.impact, "corrective_action": o.corrective_action,
                    "responsible": o.responsible,
                    "deadline": o.deadline.isoformat() if o.deadline else None,
                }
                for o in occurrences
            ],
            "quality_checks": [
                {"id": q.id, "check_type": q.check_type, "result": q.result, "observations": q.observations}
                for q in quality_checks
            ],
            "photos": [
                {
                    "id": p.id, "photo_number": p.photo_number, "description": p.description,
                    "location": p.location, "taken_at": p.taken_at,
                    "file_path": p.file_path, "original_filename": p.original_filename,
                    "url": f"/uploads/{p.file_path}" if p.file_path else None,
                }
                for p in photos
            ],
            "next_day_plans": [
                {
                    "id": n.id, "front_site": n.front_site, "planned_activity": n.planned_activity,
                    "responsible": n.responsible, "dependency": n.dependency,
                }
                for n in next_day_plans
            ],
            "signatures": [
                {
                    "id": s.id, "role": s.role, "name": s.name,
                    "confirmed_at": s.confirmed_at.isoformat() if s.confirmed_at else None,
                }
                for s in signatures
            ],
        }

    async def update_report(self, report_id: int, payload: dict) -> dict | None:
        data = {k: v for k, v in payload.items() if v is not None}

        resources = data.pop("resources", None)
        activities = data.pop("activities", None)
        materials = data.pop("materials", None)
        occurrences = data.pop("occurrences", None)
        quality_checks = data.pop("quality_checks", None)
        next_day_plans = data.pop("next_day_plans", None)
        signatures = data.pop("signatures", None)

        # Remove read-only / computed fields
        for f in ("id", "report_number", "site_id", "created_at", "updated_at", "total_personnel"):
            data.pop(f, None)

        # Convert date string back to date object if present
        if "date" in data and isinstance(data["date"], str):
            from datetime import date as _date
            data["date"] = _date.fromisoformat(data["date"])

        report = await self._repo.update_report(report_id, data)
        if not report:
            return None

        if resources is not None:
            await self._repo.replace_resources(report_id, resources)
        if activities is not None:
            saved_acts = await self._repo.replace_activities(report_id, activities)
            report_obj = await self._repo.get_report(report_id)
            if report_obj:
                await self._auto_fill_measurements(report_obj.site_id, report_obj.date, saved_acts)
        if materials is not None:
            await self._repo.replace_materials(report_id, materials)
        if occurrences is not None:
            await self._repo.replace_occurrences(report_id, occurrences)
        if quality_checks is not None:
            await self._repo.replace_quality_checks(report_id, quality_checks)
        if next_day_plans is not None:
            await self._repo.replace_next_day_plans(report_id, next_day_plans)
        if signatures is not None:
            await self._repo.replace_signatures(report_id, signatures)

        return await self.get_full_report(report_id)

    async def save_photo(
        self, report_id: int, file_bytes: bytes, original_filename: str,
        description: str | None, location: str | None, taken_at: str | None,
        photos_dir: str,
    ) -> dict:
        report = await self._repo.get_report(report_id)
        if not report:
            raise ValueError(f"Relatório {report_id} não encontrado")

        ext = os.path.splitext(original_filename)[1].lower() or ".jpg"
        stored_name = f"{report_id}_{uuid.uuid4().hex}{ext}"
        os.makedirs(photos_dir, exist_ok=True)
        with open(os.path.join(photos_dir, stored_name), "wb") as fh:
            fh.write(file_bytes)

        photo = await self._repo.add_photo(report_id, {
            "description": description,
            "location": location,
            "taken_at": taken_at,
            "file_path": stored_name,
            "original_filename": original_filename,
        })
        return {
            "id": photo.id,
            "photo_number": photo.photo_number,
            "description": photo.description,
            "location": photo.location,
            "taken_at": photo.taken_at,
            "file_path": photo.file_path,
            "original_filename": photo.original_filename,
            "url": f"/uploads/{photo.file_path}",
        }

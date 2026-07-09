"""
Cálculos EVM para controle de progresso de obra civil.

Hierarquia:
  Perfil → Categoria (peso) → Atividade (qty planejada por site)
  Medição diária: qty_yesterday, qty_today por (site, atividade, data)

Fórmulas:
  pct_hoje   = qty_hoje   / total_qty   (clamp 0..1)
  pct_ontem  = qty_ontem  / total_qty
  avanço_dia = pct_hoje - pct_ontem
  contribuição = peso_categoria × pct
  progresso_site = Σ contribuições de todas as atividades do site
  progresso_global = média dos progressos de sites com medição no dia
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.civil_repository import CivilRepository


# ─── Pure calculation functions (tested independently) ────────────────────────

def pct(qty: float, total: float) -> float:
    """Percentagem de execução de uma atividade, clamped em [0, 1]."""
    if total <= 0:
        return 0.0
    return min(qty / total, 1.0)


def activity_contribution(category_weight: float, pct_value: float) -> float:
    return category_weight * pct_value


def site_progress_from_contributions(contributions: list[float]) -> float:
    return sum(contributions)


def global_progress(site_progresses: list[float]) -> float:
    """Média simples dos progressos de sites com atividade no dia."""
    if not site_progresses:
        return 0.0
    return sum(site_progresses) / len(site_progresses)


# ─── Data classes for the service layer ──────────────────────────────────────

@dataclass
class ActivityRow:
    activity_def_id: int
    activity_name: str
    unit: str | None
    category_id: int
    category_name: str
    category_weight: float
    total_qty: float
    qty_yesterday: float
    qty_today: float
    marco: int | None
    pct_yesterday: float
    pct_today: float
    day_advance: float
    contribution_yesterday: float
    contribution_today: float
    notes: str | None


@dataclass
class SiteProgressResult:
    site_id: int
    site_name: str
    profile_id: int | None
    profile_name: str | None
    progress_yesterday: float
    progress_today: float
    day_advance: float
    has_measurements: bool
    activities: list[ActivityRow] = field(default_factory=list)


@dataclass
class GlobalProgressResult:
    date: date
    global_progress_yesterday: float
    global_progress_today: float
    global_day_advance: float
    active_fronts: int
    sites: list[SiteProgressResult] = field(default_factory=list)


# ─── Service ─────────────────────────────────────────────────────────────────

class ProgressService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = CivilRepository(db)

    async def get_site_progress(self, site_id: int, mdate: date) -> SiteProgressResult:
        site = await self._repo.get_site(site_id)
        if not site:
            raise ValueError(f"Site {site_id} não encontrado")

        profile = None
        if site.profile_id:
            profile = await self._repo.get_profile(site.profile_id)

        measurements = await self._repo.get_measurements_for_site_date(site_id, mdate)
        meas_map = {m.activity_def_id: m for m in measurements}
        qtys = await self._repo.get_site_activity_qtys(site_id)

        rows: list[ActivityRow] = []
        if site.profile_id:
            act_defs = await self._repo.get_activity_defs_for_profile(site.profile_id)
            for act_def, category in act_defs:
                total = qtys.get(act_def.id, 0.0)
                meas = meas_map.get(act_def.id)
                qty_y = meas.qty_yesterday if meas else 0.0
                qty_t = meas.qty_today if meas else 0.0
                p_y = pct(qty_y, total)
                p_t = pct(qty_t, total)
                rows.append(ActivityRow(
                    activity_def_id=act_def.id,
                    activity_name=act_def.name,
                    unit=act_def.unit,
                    category_id=category.id,
                    category_name=category.name,
                    category_weight=category.weight,
                    total_qty=total,
                    qty_yesterday=qty_y,
                    qty_today=qty_t,
                    marco=meas.marco if meas else None,
                    pct_yesterday=p_y,
                    pct_today=p_t,
                    day_advance=p_t - p_y,
                    contribution_yesterday=activity_contribution(category.weight, p_y),
                    contribution_today=activity_contribution(category.weight, p_t),
                    notes=meas.notes if meas else None,
                ))

        prog_y = site_progress_from_contributions([r.contribution_yesterday for r in rows])
        prog_t = site_progress_from_contributions([r.contribution_today for r in rows])

        return SiteProgressResult(
            site_id=site_id,
            site_name=site.name,
            profile_id=site.profile_id,
            profile_name=profile.name if profile else None,
            progress_yesterday=prog_y,
            progress_today=prog_t,
            day_advance=prog_t - prog_y,
            has_measurements=bool(meas_map),
            activities=rows,
        )

    async def get_site_progress_range(
        self, site_id: int, start_date: date, end_date: date,
    ) -> SiteProgressResult:
        """Progresso do site comparando o estado acumulado em start_date com end_date
        (carregando o último valor conhecido de cada atividade, mesmo sem medição exata
        naquelas datas). Usado para relatórios de período (ex.: semana) e para o resumo
        de progresso por site, onde a maioria dos sites não tem medição no dia exato."""
        site = await self._repo.get_site(site_id)
        if not site:
            raise ValueError(f"Site {site_id} não encontrado")

        profile = None
        if site.profile_id:
            profile = await self._repo.get_profile(site.profile_id)

        qtys = await self._repo.get_site_activity_qtys(site_id)

        rows: list[ActivityRow] = []
        has_measurements = False
        if site.profile_id:
            act_defs = await self._repo.get_activity_defs_for_profile(site.profile_id)
            for act_def, category in act_defs:
                total = qtys.get(act_def.id, 0.0)
                qty_start = await self._repo.get_last_measurement_qty(
                    site_id, act_def.id, start_date + timedelta(days=1)
                )
                end_meas = await self._repo.get_last_measurement(
                    site_id, act_def.id, end_date + timedelta(days=1)
                )
                qty_end = end_meas.qty_today if end_meas else 0.0
                if qty_start > 0 or qty_end > 0:
                    has_measurements = True
                p_s = pct(qty_start, total)
                p_e = pct(qty_end, total)
                rows.append(ActivityRow(
                    activity_def_id=act_def.id,
                    activity_name=act_def.name,
                    unit=act_def.unit,
                    category_id=category.id,
                    category_name=category.name,
                    category_weight=category.weight,
                    total_qty=total,
                    qty_yesterday=qty_start,
                    qty_today=qty_end,
                    marco=end_meas.marco if end_meas else None,
                    pct_yesterday=p_s,
                    pct_today=p_e,
                    day_advance=p_e - p_s,
                    contribution_yesterday=activity_contribution(category.weight, p_s),
                    contribution_today=activity_contribution(category.weight, p_e),
                    notes=end_meas.notes if end_meas else None,
                ))

        prog_s = site_progress_from_contributions([r.contribution_yesterday for r in rows])
        prog_e = site_progress_from_contributions([r.contribution_today for r in rows])

        return SiteProgressResult(
            site_id=site_id,
            site_name=site.name,
            profile_id=site.profile_id,
            profile_name=profile.name if profile else None,
            progress_yesterday=prog_s,
            progress_today=prog_e,
            day_advance=prog_e - prog_s,
            has_measurements=has_measurements,
            activities=rows,
        )

    async def get_project_progress_range(
        self, project_id: int, start_date: date, end_date: date,
    ) -> list[SiteProgressResult]:
        """Progresso de TODOS os sites de um projeto no período, inclusive os que não
        tiveram nenhuma medição (aparecem com progresso acumulado, mesmo que o avanço
        do período seja zero)."""
        sites = await self._repo.list_sites(project_id)
        return [
            await self.get_site_progress_range(site.id, start_date, end_date)
            for site in sites
        ]

    async def get_global_progress(self, mdate: date) -> GlobalProgressResult:
        sites = await self._repo.list_all_sites()
        site_results: list[SiteProgressResult] = []
        for site in sites:
            sp = await self.get_site_progress(site.id, mdate)
            site_results.append(sp)

        active = [s for s in site_results if s.has_measurements]
        g_y = global_progress([s.progress_yesterday for s in active])
        g_t = global_progress([s.progress_today for s in active])

        return GlobalProgressResult(
            date=mdate,
            global_progress_yesterday=g_y,
            global_progress_today=g_t,
            global_day_advance=g_t - g_y,
            active_fronts=len(active),
            sites=site_results,
        )

    async def get_site_activity_table(self, site_id: int, mdate: date) -> dict:
        """
        Retorna a tabela de atividades para o formulário de medições:
        atividades do perfil do site, com as medições do dia pré-preenchidas.
        """
        site = await self._repo.get_site(site_id)
        if not site:
            raise ValueError(f"Site {site_id} não encontrado")

        profile = None
        if site.profile_id:
            profile = await self._repo.get_profile(site.profile_id)

        measurements = await self._repo.get_measurements_for_site_date(site_id, mdate)
        meas_map = {m.activity_def_id: m for m in measurements}
        qtys = await self._repo.get_site_activity_qtys(site_id)

        categories: dict[int, dict] = {}
        if site.profile_id:
            act_defs = await self._repo.get_activity_defs_for_profile(site.profile_id)
            for act_def, cat in act_defs:
                if cat.id not in categories:
                    categories[cat.id] = {
                        "category_id": cat.id,
                        "category_name": cat.name,
                        "weight": cat.weight,
                        "activities": [],
                    }
                meas = meas_map.get(act_def.id)
                total = qtys.get(act_def.id, 0.0)
                categories[cat.id]["activities"].append({
                    "activity_def_id": act_def.id,
                    "name": act_def.name,
                    "unit": act_def.unit,
                    "total_qty": total,
                    "qty_yesterday": meas.qty_yesterday if meas else 0.0,
                    "qty_today": meas.qty_today if meas else 0.0,
                    "marco": meas.marco if meas else None,
                    "notes": meas.notes if meas else None,
                })

        return {
            "site_id": site_id,
            "site_name": site.name,
            "profile_id": site.profile_id,
            "profile_name": profile.name if profile else None,
            "date": mdate.isoformat(),
            "categories": list(categories.values()),
        }

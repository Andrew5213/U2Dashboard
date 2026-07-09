"""
Seed completo do ambiente de desenvolvimento.

Cria dev.db do zero e povoa:
  • Cache ClickUp (space, folders, lists, tasks, users) — para o Dashboard
  • Projetos e sites civis — para o RDO e Progresso
  • Perfis de progresso com categorias e atividades
  • Quantidades planejadas por site
  • 14 dias de relatórios diários (RDO) com atividades, recursos, materiais,
    ocorrências, checklist e assinaturas
  • Medições de progresso (auto-preenchidas pelo CivilService)

Uso:
    python scripts/seed_dev.py
    # depois inicie o servidor:
    scripts/start_dev.ps1
"""

import asyncio
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Garante que o root do projeto está no path E que as variáveis de ambiente
# fictícias existem ANTES de qualquer import que acione config.py
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("APP_ENV_FILE", ".env.dev")
os.environ.setdefault("CLICKUP_API_TOKEN", "dev_dummy")
os.environ.setdefault("CLICKUP_TEAM_ID", "0")
os.environ.setdefault("AIRBOX_API_KEY", "dev_dummy")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession  # noqa: E402

# Importa TODOS os modelos antes de criar as tabelas
from src.core.database import Base                        # noqa: E402
import src.models.sync_map                               # noqa: E402, F401
import src.models.cache_models                           # noqa: E402, F401
import src.models.civil_models                           # noqa: E402, F401
import src.models.progress_models                        # noqa: E402, F401

from src.models.cache_models import (                    # noqa: E402
    ClickUpSpaceCache, ClickUpFolderCache, ClickUpListCache,
    ClickUpTaskCache, ClickUpUserCache, CacheRefreshLog,
)
from src.repositories.civil_repository import CivilRepository  # noqa: E402
from src.services.civil_service import CivilService            # noqa: E402

DEV_DB = "sqlite+aiosqlite:///./dev.db"
TODAY = date(2026, 7, 7)
NOW = datetime(2026, 7, 7, 9, 0, 0)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def ago(days: int) -> datetime:
    return NOW - timedelta(days=days)


def agodate(days: int) -> date:
    return TODAY - timedelta(days=days)


def future(days: int) -> datetime:
    return NOW + timedelta(days=days)


# ─── ClickUp Cache ────────────────────────────────────────────────────────────

async def seed_clickup_cache(db: AsyncSession) -> None:
    print("  Seeding ClickUp cache...")

    # ── Espaço ─────────────────────────────────────────────────────────────
    db.add(ClickUpSpaceCache(
        space_id="DEV-SPC-001",
        name="U2 Broadcast Angola [DEV]",
        private=False,
        last_refreshed_at=NOW,
    ))

    # ── Usuários ───────────────────────────────────────────────────────────
    users = [
        ("DEV-USR-001", "Carlos Mendes",  "carlos.mendes@u2broadcast.co.ao",  "#e44c4c"),
        ("DEV-USR-002", "Ana Ferreira",   "ana.ferreira@u2broadcast.co.ao",   "#4c9ee4"),
        ("DEV-USR-003", "João Santos",    "joao.santos@u2broadcast.co.ao",    "#4ce462"),
        ("DEV-USR-004", "Maria Gomes",    "maria.gomes@u2broadcast.co.ao",    "#e4c44c"),
        ("DEV-USR-005", "Pedro Nunes",    "pedro.nunes@u2broadcast.co.ao",    "#a44ce4"),
    ]
    for uid, uname, email, color in users:
        db.add(ClickUpUserCache(
            user_id=uid, username=uname, email=email,
            color=color, last_refreshed_at=NOW,
        ))

    # ── Pasta/Folder → Province ────────────────────────────────────────────
    folders = [
        ("DEV-FLD-LUA", "Luanda",   48),
        ("DEV-FLD-BEN", "Benguela", 30),
        ("DEV-FLD-HUA", "Huambo",   18),
    ]
    for fid, fname, tcount in folders:
        db.add(ClickUpFolderCache(
            folder_id=fid, space_id="DEV-SPC-001",
            name=fname, task_count=tcount, last_refreshed_at=NOW,
        ))

    # ── Listas por pasta ───────────────────────────────────────────────────
    lists_def = [
        # (list_id, folder_id, name, task_count)
        ("DEV-LST-LUA01", "DEV-FLD-LUA", "Estúdio Norte",       16),
        ("DEV-LST-LUA02", "DEV-FLD-LUA", "Estúdio Sul",         16),
        ("DEV-LST-LUA03", "DEV-FLD-LUA", "FM Site Bairro Azul", 16),
        ("DEV-LST-BEN01", "DEV-FLD-BEN", "Estúdio Benguela",    15),
        ("DEV-LST-BEN02", "DEV-FLD-BEN", "FM Site Lobito",      15),
        ("DEV-LST-HUA01", "DEV-FLD-HUA", "Estúdio Huambo",      18),
    ]
    for lid, fid, lname, tcount in lists_def:
        db.add(ClickUpListCache(
            list_id=lid, space_id="DEV-SPC-001", folder_id=fid,
            name=lname, task_count=tcount, last_refreshed_at=NOW,
        ))

    # ── Tarefas (disciplinas + subtarefas) ─────────────────────────────────
    await _seed_tasks(db)

    # ── Log de refresh ─────────────────────────────────────────────────────
    db.add(CacheRefreshLog(
        space_id="DEV-SPC-001", trigger="seed_dev",
        status="success", folders_updated=3, lists_updated=6,
        tasks_updated=96, duration_ms=142, created_at=NOW,
    ))

    await db.flush()
    print("    OK Cache ClickUp inserida")


async def _seed_tasks(db: AsyncSession) -> None:
    """Cria disciplinas (tarefas) e atividades (subtarefas) por lista."""

    # Mapeamento de lista → nível de avanço (0-4: iniciante → quase completo)
    list_level = {
        "DEV-LST-LUA01": 4,   # Luanda Norte — avançado
        "DEV-LST-LUA02": 3,   # Luanda Sul — bom progresso
        "DEV-LST-LUA03": 2,   # FM Bairro Azul — médio
        "DEV-LST-BEN01": 2,   # Benguela — médio
        "DEV-LST-BEN02": 1,   # Lobito — início
        "DEV-LST-HUA01": 0,   # Huambo — recém-começou
    }

    # Disciplines: (nome, subtarefas)
    disciplines = [
        ("Obras Civis",            ["Fundação", "Alvenaria", "Reboco", "Pavimentos"]),
        ("Instalações Elétricas",  ["Quadro Eléctrico", "Cablagem", "Iluminação"]),
        ("Telecomunicações",       ["Antenas", "Cabos RF", "Equipamentos TX"]),
        ("Sistemas de Áudio",      ["Tratamento Acústico", "Cabeamento de Áudio", "Consola"]),
        ("AVAC e Mecânicas",       ["Unidades Fan-Coil", "Canalização", "Exaustão"]),
        ("Acabamentos",            ["Pintura", "Serralharia", "Mobiliário Técnico"]),
    ]

    # Mapeamento de nível → status das disciplinas
    # nível 4: disciplinas 0-3 concluídas, 4-5 em andamento
    # nível 3: disciplinas 0-1 concluídas, 2-4 em andamento, 5 pendente
    # nível 2: disciplina 0 em revisão, 1-2 em andamento, 3-5 pendente
    # nível 1: disciplina 0 em andamento, resto pendente
    # nível 0: tudo pendente
    def task_status(level: int, idx: int) -> tuple[str, str, str]:
        """Retorna (status, status_type, status_color)."""
        if level == 4:
            if idx < 4:
                return "Concluído", "closed", "#008000"
            return "Em revisão", "custom", "#f0b429"
        if level == 3:
            if idx < 2:
                return "Concluído", "closed", "#008000"
            if idx < 5:
                return "Em andamento", "custom", "#4194f6"
            return "Pendente", "open", "#87909e"
        if level == 2:
            if idx == 0:
                return "Em revisão", "custom", "#f0b429"
            if idx < 3:
                return "Em andamento", "custom", "#4194f6"
            return "Pendente", "open", "#87909e"
        if level == 1:
            if idx == 0:
                return "Em andamento", "custom", "#4194f6"
            return "Pendente", "open", "#87909e"
        return "Pendente", "open", "#87909e"

    def sub_status(task_status_type: str, sub_idx: int) -> tuple[str, str, str]:
        if task_status_type == "closed":
            return "Concluído", "closed", "#008000"
        if task_status_type == "open":
            return "Pendente", "open", "#87909e"
        if sub_idx == 0:
            return "Concluído", "closed", "#008000"
        if sub_idx == 1:
            return "Em andamento", "custom", "#4194f6"
        return "Pendente", "open", "#87909e"

    # Assignees pool
    assignees_pool = [
        [{"id": "DEV-USR-003", "username": "João Santos"}],
        [{"id": "DEV-USR-005", "username": "Pedro Nunes"}],
        [{"id": "DEV-USR-001", "username": "Carlos Mendes"}],
        [{"id": "DEV-USR-003", "username": "João Santos"},
         {"id": "DEV-USR-005", "username": "Pedro Nunes"}],
    ]

    task_counter = 1
    sub_counter = 1

    for list_id, level in list_level.items():
        for d_idx, (disc_name, subtasks) in enumerate(disciplines):
            st, stype, scolor = task_status(level, d_idx)
            t_id = f"DEV-TSK-{task_counter:04d}"
            task_counter += 1

            due_dt = None
            date_closed = None
            date_created = ago(60)

            if stype == "closed":
                date_closed = ago(level * 3 + d_idx)
                due_dt = ago(level * 3 + d_idx + 5)
            elif stype == "custom":
                due_dt = future(14 - d_idx * 2)
            else:
                due_dt = future(30 + d_idx * 5)

            assignees = assignees_pool[(d_idx + task_counter) % len(assignees_pool)]

            db.add(ClickUpTaskCache(
                task_id=t_id, list_id=list_id, parent_task_id=None,
                name=disc_name, description=f"Disciplina: {disc_name}",
                status=st, status_type=stype, status_color=scolor,
                assignees_json=json.dumps(assignees),
                tags_json="[]",
                due_date=due_dt,
                start_date=ago(50),
                date_created=date_created,
                date_updated=ago(1),
                date_closed=date_closed,
                url=f"https://app.clickup.com/t/{t_id}",
                last_refreshed_at=NOW,
            ))

            # Subtarefas
            for s_idx, sub_name in enumerate(subtasks):
                ss, sstype, sscolor = sub_status(stype, s_idx)
                s_id = f"DEV-SUB-{sub_counter:04d}"
                sub_counter += 1

                sub_closed = None
                if sstype == "closed":
                    sub_closed = ago(level * 2 + s_idx + 1)

                db.add(ClickUpTaskCache(
                    task_id=s_id, list_id=list_id, parent_task_id=t_id,
                    name=sub_name, description=None,
                    status=ss, status_type=sstype, status_color=sscolor,
                    assignees_json=json.dumps(assignees),
                    tags_json="[]",
                    due_date=due_dt,
                    start_date=None,
                    date_created=date_created,
                    date_updated=ago(1),
                    date_closed=sub_closed,
                    url=f"https://app.clickup.com/t/{s_id}",
                    last_refreshed_at=NOW,
                ))


# ─── Projetos, Sites e Perfis Civil ──────────────────────────────────────────

async def seed_civil(db: AsyncSession) -> dict:
    """Cria projetos, perfis, sites, quantidades. Retorna IDs para o seed de RDOs."""
    print("  Seeding projetos e perfis civis...")
    repo = CivilRepository(db)

    # ── Projetos ────────────────────────────────────────────────────────────
    proj_estudios = await repo.create_project(
        "Projecto Estúdios FM Angola",
        "Instalação de estúdios de rádio FM nas principais províncias.",
    )
    proj_torres = await repo.create_project(
        "Projecto Torres FM — Região Norte",
        "Montagem de torres de transmissão FM no corredor norte.",
    )
    await db.flush()

    # ── Perfil Estúdio FM ──────────────────────────────────────────────────
    pf_studio = await repo.create_profile("Perfil Estúdio FM")
    await db.flush()

    cat_civil   = await repo.create_category(pf_studio.id, "Obra Civil",              weight=0.35, sort_order=1)
    cat_eletric = await repo.create_category(pf_studio.id, "Instalações Elétricas",   weight=0.25, sort_order=2)
    cat_acustic = await repo.create_category(pf_studio.id, "Acústica",                weight=0.20, sort_order=3)
    cat_mec     = await repo.create_category(pf_studio.id, "Instalações Mecânicas",   weight=0.12, sort_order=4)
    cat_acab    = await repo.create_category(pf_studio.id, "Acabamentos",             weight=0.08, sort_order=5)
    await db.flush()

    a_fund  = await repo.create_activity_def(cat_civil.id,   "Fundações",           unit="m3",  sort_order=1)
    a_alv   = await repo.create_activity_def(cat_civil.id,   "Alvenaria",           unit="m2",  sort_order=2)
    a_reb   = await repo.create_activity_def(cat_civil.id,   "Reboco",              unit="m2",  sort_order=3)
    a_pav   = await repo.create_activity_def(cat_civil.id,   "Pavimentos",          unit="m2",  sort_order=4)
    a_qe    = await repo.create_activity_def(cat_eletric.id, "Quadros Eléctricos",  unit="un",  sort_order=1)
    a_cab   = await repo.create_activity_def(cat_eletric.id, "Cablagem Eléctrica",  unit="ml",  sort_order=2)
    a_ilum  = await repo.create_activity_def(cat_eletric.id, "Iluminação",          unit="un",  sort_order=3)
    a_pain  = await repo.create_activity_def(cat_acustic.id, "Painéis Acústicos",   unit="m2",  sort_order=1)
    a_porta = await repo.create_activity_def(cat_acustic.id, "Portas Acústicas",    unit="un",  sort_order=2)
    a_avac  = await repo.create_activity_def(cat_mec.id,     "AVAC",                unit="un",  sort_order=1)
    a_hidr  = await repo.create_activity_def(cat_mec.id,     "Hidráulica",          unit="ml",  sort_order=2)
    a_pint  = await repo.create_activity_def(cat_acab.id,    "Pintura",             unit="m2",  sort_order=1)
    a_carp  = await repo.create_activity_def(cat_acab.id,    "Carpintaria/Serralharia", unit="ml", sort_order=2)
    await db.flush()

    # ── Perfil Torre FM ────────────────────────────────────────────────────
    pf_torre = await repo.create_profile("Perfil Torre FM")
    await db.flush()

    tcat_civil = await repo.create_category(pf_torre.id, "Obra Civil",         weight=0.40, sort_order=1)
    tcat_metal = await repo.create_category(pf_torre.id, "Estrutura Metálica", weight=0.35, sort_order=2)
    tcat_inst  = await repo.create_category(pf_torre.id, "Instalações",        weight=0.25, sort_order=3)
    await db.flush()

    ta_fund  = await repo.create_activity_def(tcat_civil.id, "Fundação da Torre",    unit="m3", sort_order=1)
    ta_plat  = await repo.create_activity_def(tcat_civil.id, "Plataforma de Acesso", unit="m2", sort_order=2)
    ta_mont  = await repo.create_activity_def(tcat_metal.id, "Montagem da Torre",    unit="m",  sort_order=1)
    ta_anc   = await repo.create_activity_def(tcat_metal.id, "Ancoragem e Fixações", unit="un", sort_order=2)
    ta_cab   = await repo.create_activity_def(tcat_inst.id,  "Cablagem Principal",   unit="ml", sort_order=1)
    ta_ater  = await repo.create_activity_def(tcat_inst.id,  "Sistema de Aterramento", unit="ml", sort_order=2)
    await db.flush()

    # ── Sites ──────────────────────────────────────────────────────────────
    site_lua = await repo.create_site(proj_estudios.id, "Estúdio Luanda Norte",  "Luanda",   pf_studio.id)
    site_ben = await repo.create_site(proj_estudios.id, "Estúdio Benguela",      "Benguela", pf_studio.id)
    site_hua = await repo.create_site(proj_estudios.id, "Estúdio Huambo",        "Huambo",   pf_studio.id)
    site_mal = await repo.create_site(proj_torres.id,  "Torre FM Malange",       "Malange",  pf_torre.id)
    site_cno = await repo.create_site(proj_torres.id,  "Torre FM Cuanza Norte",  "Cuanza Norte", pf_torre.id)
    await db.flush()

    # ── Quantidades planejadas por site ────────────────────────────────────
    # Luanda Norte (estúdio grande)
    lua_qtys = {
        a_fund.id: 80,   a_alv.id: 1200, a_reb.id: 850,  a_pav.id: 520,
        a_qe.id: 8,      a_cab.id: 2100, a_ilum.id: 128,
        a_pain.id: 640,  a_porta.id: 24,
        a_avac.id: 6,    a_hidr.id: 320,
        a_pint.id: 1100, a_carp.id: 430,
    }
    for act_id, qty in lua_qtys.items():
        await repo.upsert_site_activity_qty(site_lua.id, act_id, float(qty))

    # Benguela (estúdio médio)
    ben_qtys = {
        a_fund.id: 55,   a_alv.id: 800,  a_reb.id: 560,  a_pav.id: 340,
        a_qe.id: 6,      a_cab.id: 1400, a_ilum.id: 85,
        a_pain.id: 420,  a_porta.id: 16,
        a_avac.id: 4,    a_hidr.id: 210,
        a_pint.id: 720,  a_carp.id: 280,
    }
    for act_id, qty in ben_qtys.items():
        await repo.upsert_site_activity_qty(site_ben.id, act_id, float(qty))

    # Huambo (estúdio pequeno)
    hua_qtys = {
        a_fund.id: 40,   a_alv.id: 580,  a_reb.id: 400,  a_pav.id: 240,
        a_qe.id: 4,      a_cab.id: 900,  a_ilum.id: 60,
        a_pain.id: 280,  a_porta.id: 10,
        a_avac.id: 2,    a_hidr.id: 140,
        a_pint.id: 500,  a_carp.id: 180,
    }
    for act_id, qty in hua_qtys.items():
        await repo.upsert_site_activity_qty(site_hua.id, act_id, float(qty))

    # Malange (torre grande)
    mal_qtys = {
        ta_fund.id: 120, ta_plat.id: 200,
        ta_mont.id: 60,  ta_anc.id: 48,
        ta_cab.id: 1500, ta_ater.id: 300,
    }
    for act_id, qty in mal_qtys.items():
        await repo.upsert_site_activity_qty(site_mal.id, act_id, float(qty))

    # Cuanza Norte (torre menor)
    cno_qtys = {
        ta_fund.id: 85,  ta_plat.id: 140,
        ta_mont.id: 45,  ta_anc.id: 36,
        ta_cab.id: 1100, ta_ater.id: 220,
    }
    for act_id, qty in cno_qtys.items():
        await repo.upsert_site_activity_qty(site_cno.id, act_id, float(qty))

    await db.flush()
    print("    OK Projetos, sites e perfis inseridos")

    return {
        "proj_estudios": proj_estudios, "proj_torres": proj_torres,
        "site_lua": site_lua, "site_ben": site_ben,
        "site_hua": site_hua, "site_mal": site_mal, "site_cno": site_cno,
        # activity defs estúdio
        "a_fund": a_fund, "a_alv": a_alv, "a_reb": a_reb, "a_pav": a_pav,
        "a_qe": a_qe, "a_cab": a_cab, "a_ilum": a_ilum,
        "a_pain": a_pain, "a_porta": a_porta,
        "a_avac": a_avac, "a_hidr": a_hidr,
        "a_pint": a_pint, "a_carp": a_carp,
        # activity defs torre
        "ta_fund": ta_fund, "ta_plat": ta_plat,
        "ta_mont": ta_mont, "ta_anc": ta_anc,
        "ta_cab": ta_cab,   "ta_ater": ta_ater,
    }


# ─── Relatórios Diários ───────────────────────────────────────────────────────

async def seed_reports(db: AsyncSession, ids: dict) -> None:
    print("  Seeding relatórios diários (RDOs)...")
    svc = CivilService(db)

    # ── Luanda Norte — 14 dias ──────────────────────────────────────────────
    lua_schedule = [
        # (day_offset, [actividades_do_dia])
        # Fase 1: Fundações + Alvenaria (dias 13-9)
        (13, [
            {"activity_description": "Fundações", "activity_def_id": ids["a_fund"].id, "unit": "m3", "qty_day": 6.0, "status": "em_andamento", "front_site": "Bloco A"},
            {"activity_description": "Alvenaria",  "activity_def_id": ids["a_alv"].id,  "unit": "m2", "qty_day": 80.0, "status": "em_andamento", "front_site": "Bloco A"},
        ]),
        (12, [
            {"activity_description": "Fundações", "activity_def_id": ids["a_fund"].id, "unit": "m3", "qty_day": 6.0, "status": "em_andamento", "front_site": "Bloco A"},
            {"activity_description": "Alvenaria",  "activity_def_id": ids["a_alv"].id,  "unit": "m2", "qty_day": 85.0, "status": "em_andamento", "front_site": "Bloco A"},
        ]),
        (11, [
            {"activity_description": "Fundações", "activity_def_id": ids["a_fund"].id, "unit": "m3", "qty_day": 5.0, "status": "em_andamento"},
            {"activity_description": "Alvenaria",  "activity_def_id": ids["a_alv"].id,  "unit": "m2", "qty_day": 90.0, "status": "em_andamento"},
        ]),
        # Fase 2: Alvenaria + Reboco (dias 10-7)
        (10, [
            {"activity_description": "Alvenaria",  "activity_def_id": ids["a_alv"].id,  "unit": "m2", "qty_day": 90.0, "status": "em_andamento"},
            {"activity_description": "Reboco",     "activity_def_id": ids["a_reb"].id,  "unit": "m2", "qty_day": 55.0, "status": "iniciado", "front_site": "Bloco A"},
        ]),
        (9, [
            {"activity_description": "Alvenaria",  "activity_def_id": ids["a_alv"].id,  "unit": "m2", "qty_day": 85.0, "status": "em_andamento"},
            {"activity_description": "Reboco",     "activity_def_id": ids["a_reb"].id,  "unit": "m2", "qty_day": 60.0, "status": "em_andamento"},
        ]),
        (8, [
            {"activity_description": "Alvenaria",  "activity_def_id": ids["a_alv"].id,  "unit": "m2", "qty_day": 80.0, "status": "em_andamento"},
            {"activity_description": "Reboco",     "activity_def_id": ids["a_reb"].id,  "unit": "m2", "qty_day": 65.0, "status": "em_andamento"},
            {"activity_description": "Cablagem Eléctrica", "activity_def_id": ids["a_cab"].id, "unit": "ml", "qty_day": 120.0, "status": "iniciado"},
        ]),
        (7, [
            {"activity_description": "Reboco",     "activity_def_id": ids["a_reb"].id,  "unit": "m2", "qty_day": 70.0, "status": "em_andamento"},
            {"activity_description": "Cablagem Eléctrica", "activity_def_id": ids["a_cab"].id, "unit": "ml", "qty_day": 140.0, "status": "em_andamento"},
        ]),
        # Fase 3: Reboco + Elétrica + Acústica (dias 6-3)
        (6, [
            {"activity_description": "Reboco",     "activity_def_id": ids["a_reb"].id,  "unit": "m2", "qty_day": 70.0, "status": "em_andamento"},
            {"activity_description": "Cablagem Eléctrica", "activity_def_id": ids["a_cab"].id, "unit": "ml", "qty_day": 150.0, "status": "em_andamento"},
            {"activity_description": "Painéis Acústicos", "activity_def_id": ids["a_pain"].id, "unit": "m2", "qty_day": 40.0, "status": "iniciado"},
        ]),
        (5, [
            {"activity_description": "Reboco",     "activity_def_id": ids["a_reb"].id,  "unit": "m2", "qty_day": 68.0, "status": "em_andamento"},
            {"activity_description": "Painéis Acústicos", "activity_def_id": ids["a_pain"].id, "unit": "m2", "qty_day": 48.0, "status": "em_andamento"},
            {"activity_description": "Quadros Eléctricos", "activity_def_id": ids["a_qe"].id, "unit": "un", "qty_day": 2.0, "status": "instalado"},
        ]),
        (4, [
            {"activity_description": "Pavimentos", "activity_def_id": ids["a_pav"].id,  "unit": "m2", "qty_day": 40.0, "status": "iniciado"},
            {"activity_description": "Painéis Acústicos", "activity_def_id": ids["a_pain"].id, "unit": "m2", "qty_day": 52.0, "status": "em_andamento"},
            {"activity_description": "Iluminação", "activity_def_id": ids["a_ilum"].id, "unit": "un", "qty_day": 15.0, "status": "instalado"},
        ]),
        # Fase 4: Finalização (dias 3-1)
        (3, [
            {"activity_description": "Pavimentos", "activity_def_id": ids["a_pav"].id,  "unit": "m2", "qty_day": 45.0, "status": "em_andamento"},
            {"activity_description": "Portas Acústicas", "activity_def_id": ids["a_porta"].id, "unit": "un", "qty_day": 4.0, "status": "instalado"},
            {"activity_description": "Iluminação", "activity_def_id": ids["a_ilum"].id, "unit": "un", "qty_day": 16.0, "status": "instalado"},
        ]),
        (2, [
            {"activity_description": "Pavimentos", "activity_def_id": ids["a_pav"].id,  "unit": "m2", "qty_day": 42.0, "status": "em_andamento"},
            {"activity_description": "AVAC",       "activity_def_id": ids["a_avac"].id, "unit": "un", "qty_day": 2.0,  "status": "instalado"},
            {"activity_description": "Pintura",    "activity_def_id": ids["a_pint"].id, "unit": "m2", "qty_day": 80.0, "status": "iniciado"},
        ]),
        (1, [
            {"activity_description": "Pintura",    "activity_def_id": ids["a_pint"].id, "unit": "m2", "qty_day": 90.0, "status": "em_andamento"},
            {"activity_description": "Carpintaria/Serralharia", "activity_def_id": ids["a_carp"].id, "unit": "ml", "qty_day": 35.0, "status": "iniciado"},
            {"activity_description": "Verificação de instalações eléctricas — teste de continuidade", "status": "concluido", "civil_category": "Instalações Elétricas"},
        ]),
    ]

    lua_resources_cycle = [
        [{"discipline": "Civil/Alvenaria", "quantity": 6}, {"discipline": "Engenharia/Supervisão", "quantity": 1}],
        [{"discipline": "Civil/Alvenaria", "quantity": 5}, {"discipline": "Apoio/Limpeza", "quantity": 2}, {"discipline": "Engenharia/Supervisão", "quantity": 1}],
        [{"discipline": "Civil/Alvenaria", "quantity": 6}, {"discipline": "Pintura/Acabamentos", "quantity": 3}, {"discipline": "Engenharia/Supervisão", "quantity": 1}],
        [{"discipline": "Civil/Alvenaria", "quantity": 4}, {"discipline": "Acústica Civil", "quantity": 2}, {"discipline": "Engenharia/Supervisão", "quantity": 1}],
    ]

    lua_materials_cycle = [
        [{"material_name": "Blocos de betão 20×20×40", "unit": "un",  "qty_received": 500, "qty_applied": 480}],
        [{"material_name": "Cimento CEM II 42.5",       "unit": "saco","qty_received": 80,  "qty_applied": 75}],
        [{"material_name": "Areia fina",                 "unit": "m3", "qty_received": 5,   "qty_applied": 4.5}],
        [{"material_name": "Varão de aço Ø10mm",        "unit": "kg", "qty_received": 250, "qty_applied": 220},
         {"material_name": "Cabo FRX 3×2.5mm²",         "unit": "ml", "qty_received": 200, "qty_applied": 195}],
    ]

    lua_occurrences_cycle = [
        [],
        [{"occurrence_type": "atraso_material", "description": "Atraso na entrega de cimento — fornecedor avisou com 2 dias de antecedência.", "impact": "Atraso de 1 dia no cronograma de reboco.", "corrective_action": "Compra de emergência no mercado local.", "responsible": "Carlos Mendes"}],
        [],
        [{"occurrence_type": "clima", "description": "Chuva intensa durante 3h interrompeu serviços no exterior.", "impact": "Redução de 30% da produtividade.", "corrective_action": "Realocação de equipa para trabalhos interiores."}],
        [], [], [], [], [], [], [], [], [],
    ]

    for i, (day_offset, activities) in enumerate(lua_schedule):
        rdo_date = agodate(day_offset)
        resources = lua_resources_cycle[i % len(lua_resources_cycle)]
        materials = lua_materials_cycle[i % len(lua_materials_cycle)]
        occurrences = lua_occurrences_cycle[i % len(lua_occurrences_cycle)]

        resp = "Eng. António Sebastião" if day_offset % 3 != 0 else "Eng. Carlos Mendes"
        weather = ["Ensolarado", "Nublado", "Chuvoso", "Ensolarado"][i % 4]

        await svc.create_report({
            "site_id": ids["site_lua"].id,
            "date": rdo_date,
            "province": "Luanda",
            "local_site": "Rua Major Kanhangulo, nº 45",
            "responsible": resp,
            "contractor": "Construtora ANGOBUILD Lda.",
            "supervisor": "Eng. Maria Gomes",
            "weather_conditions": weather,
            "general_situation": "Normal",
            "start_time": "07:30",
            "end_time": "17:00",
            "active_fronts": min(3, 1 + i // 4),
            "activities_completed": max(0, i - 3),
            "activities_in_progress": min(4, 1 + i // 3),
            "restrictions_count": 1 if occurrences else 0,
            "safety_situation": "Sem ocorrências",
            "quality_situation": "Conforme",
            "short_comment": f"Avanço normal das frentes activas. Dia {14 - day_offset + 1} de actividade.",
            "daily_conclusion": "Produção dentro do previsto. Equipa motivada.",
            "resources": resources,
            "activities": activities,
            "materials": materials,
            "occurrences": occurrences,
            "quality_checks": [
                {"check_type": "epi",                "result": True,  "observations": None},
                {"check_type": "limpeza",            "result": True,  "observations": None},
                {"check_type": "conformidade_projeto","result": True,  "observations": None},
                {"check_type": "ensaios",            "result": i > 5, "observations": None},
                {"check_type": "nao_conformidades",  "result": False, "observations": "Nenhuma não-conformidade registada." if i > 3 else None},
            ],
            "next_day_plans": [
                {"planned_activity": acts[0]["activity_description"] if acts else "Continuação das atividades",
                 "front_site": acts[0].get("front_site", "Geral"), "responsible": resp}
                for acts in [activities[:1]]
            ],
            "signatures": [
                {"role": "responsavel_obra",     "name": resp,              "confirmed_at": datetime.combine(rdo_date, datetime.min.time()).replace(hour=17)},
                {"role": "fiscal_supervisor",    "name": "Eng. Maria Gomes","confirmed_at": datetime.combine(rdo_date, datetime.min.time()).replace(hour=17, minute=30)},
                {"role": "representante_cliente", "name": None,             "confirmed_at": None},
            ],
        })
        await db.commit()

    print(f"    OK Luanda Norte: {len(lua_schedule)} RDOs criados")

    # ── Benguela — 7 dias ───────────────────────────────────────────────────
    ben_schedule = [
        (7, [{"activity_description": "Fundações", "activity_def_id": ids["a_fund"].id, "unit": "m3", "qty_day": 5.0, "status": "em_andamento"}]),
        (6, [{"activity_description": "Fundações", "activity_def_id": ids["a_fund"].id, "unit": "m3", "qty_day": 5.0, "status": "em_andamento"},
             {"activity_description": "Alvenaria",  "activity_def_id": ids["a_alv"].id,  "unit": "m2", "qty_day": 50.0, "status": "iniciado"}]),
        (5, [{"activity_description": "Alvenaria",  "activity_def_id": ids["a_alv"].id,  "unit": "m2", "qty_day": 60.0, "status": "em_andamento"},
             {"activity_description": "Cablagem Eléctrica", "activity_def_id": ids["a_cab"].id, "unit": "ml", "qty_day": 80.0, "status": "iniciado"}]),
        (4, [{"activity_description": "Alvenaria",  "activity_def_id": ids["a_alv"].id,  "unit": "m2", "qty_day": 65.0, "status": "em_andamento"},
             {"activity_description": "Cablagem Eléctrica", "activity_def_id": ids["a_cab"].id, "unit": "ml", "qty_day": 90.0, "status": "em_andamento"}]),
        (3, [{"activity_description": "Alvenaria",  "activity_def_id": ids["a_alv"].id,  "unit": "m2", "qty_day": 60.0, "status": "em_andamento"},
             {"activity_description": "Reboco",     "activity_def_id": ids["a_reb"].id,  "unit": "m2", "qty_day": 35.0, "status": "iniciado"}]),
        (2, [{"activity_description": "Reboco",     "activity_def_id": ids["a_reb"].id,  "unit": "m2", "qty_day": 40.0, "status": "em_andamento"},
             {"activity_description": "Limpeza e preparação da área — serviço avulso"}]),
        (1, [{"activity_description": "Reboco",     "activity_def_id": ids["a_reb"].id,  "unit": "m2", "qty_day": 42.0, "status": "em_andamento"},
             {"activity_description": "Painéis Acústicos", "activity_def_id": ids["a_pain"].id, "unit": "m2", "qty_day": 20.0, "status": "iniciado"}]),
    ]
    for day_offset, activities in ben_schedule:
        await svc.create_report({
            "site_id": ids["site_ben"].id,
            "date": agodate(day_offset),
            "province": "Benguela",
            "local_site": "Av. de Portugal, nº 12, Benguela",
            "responsible": "Eng. Pedro Nunes",
            "contractor": "BENGUELA OBRAS E CONSTRUÇÕES Lda.",
            "supervisor": "Eng. Ana Ferreira",
            "weather_conditions": "Ensolarado",
            "general_situation": "Normal",
            "start_time": "08:00", "end_time": "17:30",
            "active_fronts": 2,
            "activities_in_progress": len(activities),
            "safety_situation": "Sem ocorrências",
            "quality_situation": "Conforme",
            "resources": [
                {"discipline": "Civil/Alvenaria", "quantity": 5},
                {"discipline": "Engenharia/Supervisão", "quantity": 1},
            ],
            "activities": activities,
            "materials": [{"material_name": "Blocos de betão 20×20×40", "unit": "un", "qty_received": 400, "qty_applied": 390}],
            "quality_checks": [
                {"check_type": "epi",                "result": True,  "observations": None},
                {"check_type": "limpeza",            "result": True,  "observations": None},
                {"check_type": "conformidade_projeto","result": True,  "observations": None},
                {"check_type": "ensaios",            "result": False, "observations": None},
                {"check_type": "nao_conformidades",  "result": False, "observations": None},
            ],
            "signatures": [
                {"role": "responsavel_obra",     "name": "Eng. Pedro Nunes", "confirmed_at": None},
                {"role": "fiscal_supervisor",    "name": "Eng. Ana Ferreira","confirmed_at": None},
                {"role": "representante_cliente", "name": None,              "confirmed_at": None},
            ],
        })
        await db.commit()
    print(f"    OK Benguela: {len(ben_schedule)} RDOs criados")

    # ── Torre FM Malange — 5 dias ───────────────────────────────────────────
    mal_schedule = [
        (5, [{"activity_description": "Fundação da Torre", "activity_def_id": ids["ta_fund"].id, "unit": "m3", "qty_day": 12.0, "status": "em_andamento"}]),
        (4, [{"activity_description": "Fundação da Torre", "activity_def_id": ids["ta_fund"].id, "unit": "m3", "qty_day": 14.0, "status": "em_andamento"},
             {"activity_description": "Plataforma de Acesso", "activity_def_id": ids["ta_plat"].id, "unit": "m2", "qty_day": 18.0, "status": "iniciado"}]),
        (3, [{"activity_description": "Fundação da Torre", "activity_def_id": ids["ta_fund"].id, "unit": "m3", "qty_day": 12.0, "status": "em_andamento"},
             {"activity_description": "Plataforma de Acesso", "activity_def_id": ids["ta_plat"].id, "unit": "m2", "qty_day": 22.0, "status": "em_andamento"}]),
        (2, [{"activity_description": "Plataforma de Acesso", "activity_def_id": ids["ta_plat"].id, "unit": "m2", "qty_day": 20.0, "status": "em_andamento"},
             {"activity_description": "Montagem da Torre",    "activity_def_id": ids["ta_mont"].id, "unit": "m",  "qty_day": 5.0,  "status": "iniciado"}]),
        (1, [{"activity_description": "Montagem da Torre",    "activity_def_id": ids["ta_mont"].id, "unit": "m",  "qty_day": 7.0,  "status": "em_andamento"},
             {"activity_description": "Cablagem Principal",   "activity_def_id": ids["ta_cab"].id,  "unit": "ml", "qty_day": 80.0, "status": "iniciado"}]),
    ]
    for day_offset, activities in mal_schedule:
        await svc.create_report({
            "site_id": ids["site_mal"].id,
            "date": agodate(day_offset),
            "province": "Malange",
            "local_site": "Estrada Nacional 230, km 12, Malange",
            "responsible": "Eng. João Santos",
            "contractor": "METALTORRE ANGOLA Lda.",
            "supervisor": "Eng. Carlos Mendes",
            "weather_conditions": "Nublado",
            "general_situation": "Normal",
            "start_time": "07:00", "end_time": "16:30",
            "active_fronts": 2,
            "activities_in_progress": len(activities),
            "safety_situation": "Sem ocorrências",
            "quality_situation": "Conforme",
            "resources": [
                {"discipline": "Civil/Alvenaria", "quantity": 4},
                {"discipline": "Carpintaria/Serralharia", "quantity": 3},
                {"discipline": "Engenharia/Supervisão", "quantity": 1},
            ],
            "activities": activities,
            "materials": [{"material_name": "Betão armado B25", "unit": "m3", "qty_received": 15, "qty_applied": 14}],
            "quality_checks": [
                {"check_type": "epi",                "result": True,  "observations": None},
                {"check_type": "limpeza",            "result": True,  "observations": None},
                {"check_type": "conformidade_projeto","result": True,  "observations": None},
                {"check_type": "ensaios",            "result": False, "observations": None},
                {"check_type": "nao_conformidades",  "result": False, "observations": None},
            ],
            "signatures": [
                {"role": "responsavel_obra",     "name": "Eng. João Santos",  "confirmed_at": None},
                {"role": "fiscal_supervisor",    "name": "Eng. Carlos Mendes","confirmed_at": None},
                {"role": "representante_cliente", "name": None,               "confirmed_at": None},
            ],
        })
        await db.commit()
    print(f"    OK Torre FM Malange: {len(mal_schedule)} RDOs criados")


# ─── Ponto de entrada ─────────────────────────────────────────────────────────

async def main() -> None:
    print("\nIniciando seed do ambiente de desenvolvimento (dev.db)...\n")

    # Garante diretório de uploads dev
    os.makedirs("./dev_uploads", exist_ok=True)

    engine = create_async_engine(DEV_DB, echo=False)

    # Recria todas as tabelas do zero
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    print("  OK Tabelas recriadas")

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as db:
        await seed_clickup_cache(db)
        await db.commit()

        ids = await seed_civil(db)
        await db.commit()

        await seed_reports(db, ids)

    await engine.dispose()

    print("\ndev.db populado com sucesso!")
    print("   Para iniciar o servidor dev:")
    print("   .\\scripts\\start_dev.ps1\n")


if __name__ == "__main__":
    asyncio.run(main())

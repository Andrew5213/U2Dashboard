from datetime import date, datetime
from sqlalchemy import (
    String, DateTime, Integer, Float, Text,
    ForeignKey, Date, Boolean, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column
from src.core.database import Base


CIVIL_DISCIPLINES = [
    "Engenharia/Supervisão",
    "Civil/Alvenaria",
    "Pintura/Acabamentos",
    "Carpintaria/Serralharia",
    "Acústica Civil",
    "Impermeabilização/Cobertura",
    "Apoio/Limpeza",
    "Outros",
]

CIVIL_QUALITY_CHECKS = [
    "epi",
    "limpeza",
    "conformidade_projeto",
    "ensaios",
    "nao_conformidades",
]

CIVIL_SIGNATURE_ROLES = [
    "responsavel_obra",
    "fiscal_supervisor",
    "representante_cliente",
]


class CivilProject(Base):
    __tablename__ = "civil_project"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class CivilSite(Base):
    __tablename__ = "civil_site"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("civil_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    province: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # FK resolved at runtime; civil_progress_profile is imported in main.py
    profile_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("civil_progress_profile.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CivilDailyReport(Base):
    __tablename__ = "civil_daily_report"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("civil_site.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("civil_project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    report_number: Mapped[int] = mapped_column(Integer, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # 1.1 Identificação
    province: Mapped[str | None] = mapped_column(String(100), nullable=True)
    local_site: Mapped[str | None] = mapped_column(String(255), nullable=True)
    responsible: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contractor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supervisor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    weather_conditions: Mapped[str | None] = mapped_column(String(50), nullable=True)
    general_situation: Mapped[str | None] = mapped_column(String(50), nullable=True)
    start_time: Mapped[str | None] = mapped_column(String(10), nullable=True)
    end_time: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # 1.2 Resumo do dia
    active_fronts: Mapped[int] = mapped_column(Integer, default=0)
    activities_completed: Mapped[int] = mapped_column(Integer, default=0)
    activities_in_progress: Mapped[int] = mapped_column(Integer, default=0)
    restrictions_count: Mapped[int] = mapped_column(Integer, default=0)
    safety_situation: Mapped[str | None] = mapped_column(String(50), nullable=True)
    quality_situation: Mapped[str | None] = mapped_column(String(50), nullable=True)
    short_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 1.10 Conclusão
    daily_conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("site_id", "date", name="uq_civil_report_site_date"),
    )


class CivilResource(Base):
    """1.3 Recursos mobilizados — linha por disciplina."""
    __tablename__ = "civil_resource"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("civil_daily_report.id", ondelete="CASCADE"), nullable=False, index=True
    )
    discipline: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)


class CivilActivity(Base):
    """1.4 Atividades civis executadas no dia."""
    __tablename__ = "civil_activity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("civil_daily_report.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # FK opcional ao catálogo de atividades — quando preenchido alimenta automaticamente a medição de progresso
    activity_def_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("civil_progress_activity_def.id", ondelete="SET NULL"), nullable=True
    )
    front_site: Mapped[str | None] = mapped_column(String(255), nullable=True)
    civil_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    activity_description: Mapped[str] = mapped_column(String(500), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    qty_day: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)


class CivilMaterial(Base):
    """1.5 Materiais recebidos/aplicados — balance calculado na resposta."""
    __tablename__ = "civil_material"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("civil_daily_report.id", ondelete="CASCADE"), nullable=False, index=True
    )
    material_name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    qty_received: Mapped[float] = mapped_column(Float, default=0.0)
    qty_applied: Mapped[float] = mapped_column(Float, default=0.0)
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)


class CivilOccurrence(Base):
    """1.6 Ocorrências, impedimentos e riscos."""
    __tablename__ = "civil_occurrence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("civil_daily_report.id", ondelete="CASCADE"), nullable=False, index=True
    )
    occurrence_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    impact: Mapped[str | None] = mapped_column(String(255), nullable=True)
    corrective_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    responsible: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)


class CivilQualityCheck(Base):
    """1.7 Checklist qualidade, segurança e conformidade (5 itens fixos)."""
    __tablename__ = "civil_quality_check"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("civil_daily_report.id", ondelete="CASCADE"), nullable=False, index=True
    )
    check_type: Mapped[str] = mapped_column(String(50), nullable=False)
    result: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)


class CivilPhoto(Base):
    """1.8 Evidências fotográficas."""
    __tablename__ = "civil_photo"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("civil_daily_report.id", ondelete="CASCADE"), nullable=False, index=True
    )
    photo_number: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    taken_at: Mapped[str | None] = mapped_column(String(10), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)


class CivilNextDayPlan(Base):
    """1.9 Planeamento para o dia seguinte."""
    __tablename__ = "civil_next_day_plan"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("civil_daily_report.id", ondelete="CASCADE"), nullable=False, index=True
    )
    front_site: Mapped[str | None] = mapped_column(String(255), nullable=True)
    planned_activity: Mapped[str] = mapped_column(String(500), nullable=False)
    responsible: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dependency: Mapped[str | None] = mapped_column(String(255), nullable=True)


class CivilSignature(Base):
    """1.11 Assinaturas (3 papéis fixos)."""
    __tablename__ = "civil_signature"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("civil_daily_report.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    signature_image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

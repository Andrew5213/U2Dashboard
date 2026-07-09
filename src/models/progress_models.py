from datetime import date, datetime
from sqlalchemy import (
    String, DateTime, Integer, Float, Text,
    ForeignKey, Date, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column
from src.core.database import Base


class CivilProgressProfile(Base):
    """Perfil de site (ex.: 'Site TX c/ torre', 'Site TX s/ torre', 'Luanda')."""
    __tablename__ = "civil_progress_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CivilProgressCategory(Base):
    """Categoria dentro de um perfil com peso configurável."""
    __tablename__ = "civil_progress_category"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("civil_progress_profile.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class CivilProgressActivityDef(Base):
    """Definição de atividade civil dentro de uma categoria."""
    __tablename__ = "civil_progress_activity_def"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("civil_progress_category.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class CivilSiteActivityQty(Base):
    """Quantidade total planejada de uma atividade em um site específico."""
    __tablename__ = "civil_site_activity_qty"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # FK to civil_site resolves at runtime; both models imported in main.py
    site_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("civil_site.id", ondelete="CASCADE"), nullable=False
    )
    activity_def_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("civil_progress_activity_def.id", ondelete="CASCADE"), nullable=False
    )
    total_qty: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("site_id", "activity_def_id", name="uq_site_activity_qty"),
    )


class CivilProgressMeasurement(Base):
    """Medição diária: qty acumulada até ontem e até hoje, por atividade por site."""
    __tablename__ = "civil_progress_measurement"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("civil_site.id", ondelete="CASCADE"), nullable=False, index=True
    )
    activity_def_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("civil_progress_activity_def.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    qty_yesterday: Mapped[float] = mapped_column(Float, default=0.0)
    qty_today: Mapped[float] = mapped_column(Float, default=0.0)
    # marco 0–4 para atividades não-quantitativas (opcional)
    marco: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "site_id", "activity_def_id", "date",
            name="uq_measurement_site_activity_date",
        ),
    )

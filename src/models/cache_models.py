from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Integer, Float, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from src.core.database import Base


class ClickUpSpaceCache(Base):
    __tablename__ = "clickup_space_cache"

    space_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    private: Mapped[bool] = mapped_column(Boolean, default=False)
    last_refreshed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ClickUpFolderCache(Base):
    __tablename__ = "clickup_folder_cache"

    folder_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(100), ForeignKey("clickup_space_cache.space_id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    task_count: Mapped[int] = mapped_column(Integer, default=0)
    last_refreshed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ClickUpListCache(Base):
    __tablename__ = "clickup_list_cache"

    list_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(100), ForeignKey("clickup_space_cache.space_id"), nullable=False, index=True)
    folder_id: Mapped[str | None] = mapped_column(String(100), ForeignKey("clickup_folder_cache.folder_id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status_text: Mapped[str | None] = mapped_column(String(100), nullable=True)
    task_count: Mapped[int] = mapped_column(Integer, default=0)
    last_refreshed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ClickUpTaskCache(Base):
    __tablename__ = "clickup_task_cache"

    task_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    list_id: Mapped[str] = mapped_column(String(100), ForeignKey("clickup_list_cache.list_id"), nullable=False, index=True)
    parent_task_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    status_color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    assignees_json: Mapped[str] = mapped_column(Text, default="[]")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    start_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    date_created: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    date_updated: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    date_closed: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_refreshed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ClickUpUserCache(Base):
    __tablename__ = "clickup_user_cache"

    user_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    profile_picture: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_refreshed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class CacheRefreshLog(Base):
    __tablename__ = "cache_refresh_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    space_id: Mapped[str] = mapped_column(String(100), nullable=False)
    trigger: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    folders_updated: Mapped[int] = mapped_column(Integer, default=0)
    lists_updated: Mapped[int] = mapped_column(Integer, default=0)
    tasks_updated: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DisciplineWeight(Base):
    """Peso de cada disciplina (Lista) dentro de uma Pasta/Província."""
    __tablename__ = "discipline_weights"

    list_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("clickup_list_cache.list_id"), primary_key=True
    )
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

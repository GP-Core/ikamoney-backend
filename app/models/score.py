"""Historial del Índice de Salud Financiera (tabla score_historial de T18).

Solo se agregan filas; nunca se actualizan. Cada fila es una foto del score en un momento,
con la versión de las reglas que lo calculó y su desglose por factor.
"""
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.comunes import Id, Marcas, SmallUns, fk


class ScoreHistorial(Base, Marcas):
    __tablename__ = "score_historial"
    __table_args__ = (
        CheckConstraint("puntaje <= 100", name="ck_score_puntaje"),
        Index("ix_score_usuario_fecha", "usuario_id", "calculado_en"),
    )
    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    usuario_id: Mapped[int] = fk("usuario.id")
    calculado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    puntaje: Mapped[int] = mapped_column(SmallUns, nullable=False)          # 0 a 100
    version_modelo: Mapped[str] = mapped_column(String(20), nullable=False)
    componentes: Mapped[dict] = mapped_column(JSON, nullable=False)          # desglose por factor
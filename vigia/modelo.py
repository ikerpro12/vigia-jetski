"""Estructuras de datos compartidas por todo el programa."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Optional


class Nivel(IntEnum):
    """Niveles de aviso, con los mismos colores que usa AEMET."""

    VERDE = 0
    AMARILLO = 1
    NARANJA = 2
    ROJO = 3

    @property
    def etiqueta(self) -> str:
        return {
            Nivel.VERDE: "VERDE",
            Nivel.AMARILLO: "AMARILLO",
            Nivel.NARANJA: "NARANJA",
            Nivel.ROJO: "ROJO",
        }[self]

    @property
    def emoji(self) -> str:
        return {
            Nivel.VERDE: "🟢",
            Nivel.AMARILLO: "🟡",
            Nivel.NARANJA: "🟠",
            Nivel.ROJO: "🔴",
        }[self]


@dataclass
class Lectura:
    """Una previsión horaria de una sola fuente.

    Todos los campos meteorológicos son opcionales: cada fuente aporta lo que
    sabe y el consenso se encarga de juntarlo.
    """

    instante: datetime
    altura_ola_m: Optional[float] = None
    periodo_ola_s: Optional[float] = None
    direccion_ola_grados: Optional[float] = None
    viento_nudos: Optional[float] = None
    racha_nudos: Optional[float] = None
    direccion_viento_grados: Optional[float] = None
    lluvia_mm: Optional[float] = None
    prob_lluvia_pct: Optional[float] = None
    temperatura_mar_c: Optional[float] = None
    uv: Optional[float] = None

    def tiene_datos(self) -> bool:
        return any(
            valor is not None
            for valor in (
                self.altura_ola_m,
                self.viento_nudos,
                self.racha_nudos,
            )
        )


@dataclass
class RespuestaFuente:
    """Lo que devuelve una fuente: sus lecturas, o el error que la tumbó."""

    nombre: str
    lecturas: list[Lectura] = field(default_factory=list)
    error: Optional[str] = None
    # Texto libre (boletines de AEMET, por ejemplo) que se adjunta al aviso.
    boletin: Optional[str] = None
    # Aviso oficial vigente y relevante para nuestra zona. Si viene relleno,
    # manda sobre los modelos: sube el nivel por sí solo.
    aviso_oficial: Optional[str] = None
    # Cuota consumida hoy, para las fuentes que la reportan (Stormglass).
    peticiones_usadas: Optional[int] = None
    # Efemérides del día: hasta cuándo hay luz para salir.
    amanecer: Optional[datetime] = None
    atardecer: Optional[datetime] = None
    uv_max: Optional[float] = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.lecturas)


@dataclass
class Consenso:
    """Previsión combinada de varias fuentes para una hora concreta."""

    instante: datetime
    altura_ola_m: Optional[float] = None
    altura_ola_min_m: Optional[float] = None
    altura_ola_max_m: Optional[float] = None
    # Valor prudente (percentil 75) para decidir si se escala el aviso.
    altura_ola_p75_m: Optional[float] = None
    periodo_ola_s: Optional[float] = None
    viento_nudos: Optional[float] = None
    racha_nudos: Optional[float] = None
    racha_max_nudos: Optional[float] = None
    direccion_viento_grados: Optional[float] = None
    # De donde VIENE la ola. Se descargaba y se tiraba, y esa era justo la
    # pieza que faltaba para no dejar pasar un mar de fondo con viento flojo
    # de tierra.
    direccion_ola_grados: Optional[float] = None
    lluvia_mm: Optional[float] = None
    prob_lluvia_pct: Optional[float] = None
    temperatura_mar_c: Optional[float] = None
    uv: Optional[float] = None
    fuentes_ola: int = 0
    fuentes_viento: int = 0


@dataclass
class Evaluacion:
    """Veredicto para una hora: qué nivel y por qué."""

    instante: datetime
    nivel: Nivel
    motivos: list[str] = field(default_factory=list)
    viento_de_mar: bool = False

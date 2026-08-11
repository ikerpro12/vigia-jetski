"""Registro de fuentes.

Añadir una fuente nueva es añadir una función `(Config) -> RespuestaFuente`
a esta lista. Todas se consultan en paralelo y ninguna puede tumbar al resto.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from ..config import Config
from ..modelo import RespuestaFuente
from .aemet import boletin_aemet
from .met_norway import viento_met_norway
from .open_meteo import (
    lluvia_open_meteo,
    olas_open_meteo,
    temperatura_mar_open_meteo,
    viento_open_meteo,
)
from .siete_timer import viento_7timer
from .stormglass import olas_stormglass

Fuente = Callable[[Config], RespuestaFuente]

# Fuentes gratuitas, sin clave y sin registro: se consultan siempre.
# Entre Open-Meteo (5 modelos de ola + 5 de viento), MET Norway y 7Timer salen
# más de diez modelos numéricos distintos votando en cada hora.
FUENTES_LIBRES: list[Fuente] = [
    olas_open_meteo,
    viento_open_meteo,
    lluvia_open_meteo,
    temperatura_mar_open_meteo,
    viento_met_norway,
    viento_7timer,
    boletin_aemet,
]

# Fuentes con cuota: solo cuando merece la pena gastarla.
FUENTES_CON_CUOTA: list[Fuente] = [olas_stormglass]


def consultar_todas(cfg: Config, con_cuota: bool = False) -> list[RespuestaFuente]:
    """Lanza las fuentes a la vez y recoge lo que sobreviva.

    `con_cuota` decide si se gasta una petición de Stormglass en esta pasada.
    Con 9 peticiones al día y una comprobación cada 5-30 minutos, no se puede
    llamar siempre: se reserva para los partes diarios y para cuando la mar ya
    pinta mal, que es cuando una segunda opinión de oleaje vale de algo.
    """
    fuentes = list(FUENTES_LIBRES)
    if con_cuota:
        fuentes += FUENTES_CON_CUOTA

    def _seguro(fuente: Fuente) -> RespuestaFuente:
        try:
            return fuente(cfg)
        except Exception as exc:  # noqa: BLE001 - una fuente rota no para el aviso
            return RespuestaFuente(
                nombre=getattr(fuente, "__name__", "desconocida"),
                error=f"excepción inesperada: {exc!r}",
            )

    with ThreadPoolExecutor(max_workers=len(fuentes)) as pool:
        return list(pool.map(_seguro, fuentes))

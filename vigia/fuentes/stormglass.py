"""Stormglass: segunda opinión de OLEAJE (opcional, requiere clave gratuita).

El plan gratuito da unas 10 peticiones al día, así que solo se consulta si hay
clave configurada. Devuelve varios modelos (NOAA, MeteoFrance, ...) y aquí se
promedian, lo que ya es una mini-redundancia por sí sola.
"""

from __future__ import annotations

from datetime import timedelta
from statistics import median
from urllib.parse import urlencode

from ..config import Config
from ..modelo import Lectura, RespuestaFuente
from .base import ErrorFuente, ahora, hora_local, pedir_json

ENDPOINT = "https://api.stormglass.io/v2/weather/point"


# 'sg' es el valor ya mezclado por Stormglass a partir del resto: incluirlo
# sería contar dos veces los mismos modelos.
DERIVADOS = {"sg"}


def _consenso_modelos(valor) -> float | None:
    """Stormglass devuelve {'noaa': 0.25, 'dwd': 0.53, 'ecmwf': 0.16, ...}.

    Se usa la MEDIANA de los modelos reales: el 10/08/2026 esta llamada
    devolvía 0,16 / 0,23 / 0,25 / 0,53 m, y la media (0,29) se iba detrás del
    valor alto de DWD mientras que la mediana (0,24) refleja lo que dicen casi
    todos.
    """
    if not isinstance(valor, dict):
        return None
    numeros = [
        v
        for clave, v in valor.items()
        if isinstance(v, (int, float)) and clave not in DERIVADOS
    ]
    if not numeros:
        return None
    return float(median(numeros))


def olas_stormglass(cfg: Config) -> RespuestaFuente:
    nombre = "Stormglass (olas)"
    if not cfg.stormglass_key:
        return RespuestaFuente(nombre=nombre, error="sin clave configurada")

    inicio = ahora(cfg.zona_horaria)
    parametros = {
        "lat": cfg.latitud,
        "lng": cfg.longitud,
        "params": "waveHeight,wavePeriod,windSpeed,gust,windDirection",
        "start": int(inicio.timestamp()),
        "end": int((inicio + timedelta(hours=cfg.horas_vista + 6)).timestamp()),
    }
    try:
        datos = pedir_json(
            f"{ENDPOINT}?{urlencode(parametros)}",
            cabeceras={"Authorization": cfg.stormglass_key},
            tiempo_espera=cfg.tiempo_espera,
        )
    except ErrorFuente as exc:
        return RespuestaFuente(nombre=nombre, error=str(exc))

    # Stormglass informa de su propio contador de cuota: es más fiable que
    # llevar la cuenta por nuestro lado.
    meta = datos.get("meta") or {}
    usados, tope = meta.get("requestCount"), meta.get("dailyQuota")

    horas = datos.get("hours") or []
    if not horas:
        return RespuestaFuente(
            nombre=nombre, error="sin datos horarios", peticiones_usadas=usados
        )

    lecturas: list[Lectura] = []
    for hora in horas:
        viento_ms = _consenso_modelos(hora.get("windSpeed"))
        racha_ms = _consenso_modelos(hora.get("gust"))
        lecturas.append(
            Lectura(
                instante=hora_local(hora["time"], cfg.zona_horaria),
                altura_ola_m=_consenso_modelos(hora.get("waveHeight")),
                periodo_ola_s=_consenso_modelos(hora.get("wavePeriod")),
                # Stormglass da m/s; se convierte a nudos.
                viento_nudos=viento_ms * 1.943844 if viento_ms else None,
                racha_nudos=racha_ms * 1.943844 if racha_ms else None,
                direccion_viento_grados=_consenso_modelos(hora.get("windDirection")),
            )
        )

    detalle = f"{nombre} [{usados}/{tope} hoy]" if usados is not None else nombre
    return RespuestaFuente(
        nombre=detalle, lecturas=lecturas, peticiones_usadas=usados
    )

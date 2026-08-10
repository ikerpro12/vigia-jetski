"""7Timer!: previsión gratuita, sin clave y sin registro.

Aporta sobre todo **redundancia de infraestructura**: es otro servidor y otra
organización, así que si Open-Meteo se cae entera seguimos teniendo viento.

Aviso sobre su precisión: 7Timer no da nudos, sino un índice de 1 a 8 por
tramos (tipo Beaufort). Se convierte al punto medio de cada tramo, así que el
número es orientativo. Por eso esta fuente **solo aporta viento medio y
dirección, nunca rachas**: las rachas son las que disparan los avisos y no
conviene moverlas con un valor tan grueso.
"""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import urlencode

from ..config import Config
from ..modelo import Lectura, RespuestaFuente
from .base import ErrorFuente, hora_local, ms_a_nudos, pedir_json

ENDPOINT = "https://www.7timer.info/bin/civil.php"

# Índice de 7Timer -> punto medio del tramo, en m/s.
# 1: <0,3 · 2: 0,3-3,4 · 3: 3,4-8 · 4: 8-10,8 · 5: 10,8-17,2
# 6: 17,2-24,5 · 7: 24,5-32,6 · 8: >32,6
TRAMOS_MS = {1: 0.15, 2: 1.85, 3: 5.7, 4: 9.4, 5: 14.0, 6: 20.85, 7: 28.55, 8: 36.0}

RUMBOS = {
    "N": 0, "NNE": 22.5, "NE": 45, "ENE": 67.5, "E": 90, "ESE": 112.5,
    "SE": 135, "SSE": 157.5, "S": 180, "SSW": 202.5, "SW": 225, "WSW": 247.5,
    "W": 270, "WNW": 292.5, "NW": 315, "NNW": 337.5,
}


def viento_7timer(cfg: Config) -> RespuestaFuente:
    nombre = "7Timer (viento)"
    parametros = {
        "lon": round(cfg.longitud, 4),
        "lat": round(cfg.latitud, 4),
        "ac": 0,
        "unit": "metric",
        "output": "json",
        "tzshift": 0,
    }
    try:
        datos = pedir_json(
            f"{ENDPOINT}?{urlencode(parametros)}",
            cabeceras={"User-Agent": cfg.contacto},
            tiempo_espera=cfg.tiempo_espera,
        )
    except ErrorFuente as exc:
        return RespuestaFuente(nombre=nombre, error=str(exc))

    serie = datos.get("dataseries") or []
    marca_inicio = datos.get("init")
    if not serie or not marca_inicio:
        return RespuestaFuente(nombre=nombre, error="respuesta sin serie")

    # `init` viene como AAAAMMDDHH en UTC y cada punto es un desfase en horas.
    try:
        base = hora_local(
            f"{marca_inicio[0:4]}-{marca_inicio[4:6]}-{marca_inicio[6:8]}"
            f"T{marca_inicio[8:10]}:00:00+00:00",
            cfg.zona_horaria,
        )
    except (ValueError, IndexError) as exc:
        return RespuestaFuente(nombre=nombre, error=f"fecha ilegible: {exc}")

    lecturas: list[Lectura] = []
    for punto in serie:
        viento = punto.get("wind10m") or {}
        indice = viento.get("speed")
        if indice not in TRAMOS_MS:
            continue
        horas = punto.get("timepoint")
        if not isinstance(horas, (int, float)):
            continue
        lecturas.append(
            Lectura(
                instante=base + timedelta(hours=float(horas)),
                viento_nudos=ms_a_nudos(TRAMOS_MS[indice]),
                # Sin rachas a propósito: ver la nota de arriba.
                direccion_viento_grados=RUMBOS.get(str(viento.get("direction")).upper()),
            )
        )

    if not lecturas:
        return RespuestaFuente(nombre=nombre, error="serie sin viento utilizable")
    return RespuestaFuente(nombre=nombre, lecturas=lecturas)

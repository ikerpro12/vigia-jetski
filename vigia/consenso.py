"""Combina las lecturas de varias fuentes en una sola previsión por hora.

Regla de combinación, pensada para que ni un modelo optimista ni uno roto
decidan solos:

  * Con 3 o más valores se usa la MEDIANA: un valor disparatado queda fuera.
  * Con 1 o 2 valores se usa el MÁXIMO: nadie puede corregir al otro, así que
    se peca de prudente. Más vale bajar a por la moto de más que de menos.

Además se guarda el rango (mín-máx) para poder avisar cuando las fuentes no
se ponen de acuerdo.
"""

from __future__ import annotations

from datetime import datetime
from statistics import median
from typing import Optional

from .modelo import Consenso, Lectura, RespuestaFuente
from .fuentes.base import truncar_hora


def _combinar(valores: list[float]) -> Optional[float]:
    if not valores:
        return None
    if len(valores) >= 3:
        return float(median(valores))
    return float(max(valores))


def _percentil75(valores: list[float]) -> Optional[float]:
    """Valor prudente: alto, pero sin ser el disparate de turno.

    Con diez y pico modelos votando, el máximo casi siempre es un valor
    atípico y usarlo para escalar avisos dispararía la alarma a todas horas.
    El percentil 75 recoge "lo que dicen los modelos más pesimistas" sin
    dejarse arrastrar por uno solo.
    """
    if not valores:
        return None
    if len(valores) < 3:
        return float(max(valores))
    ordenados = sorted(valores)
    posicion = 0.75 * (len(ordenados) - 1)
    bajo = int(posicion)
    alto = min(bajo + 1, len(ordenados) - 1)
    peso = posicion - bajo
    return float(ordenados[bajo] * (1 - peso) + ordenados[alto] * peso)


def _promediar_angulos(grados: list[float]) -> Optional[float]:
    """Media circular: la media aritmética de 350° y 10° daría 180°, que es falso."""
    if not grados:
        return None
    import math

    seno = sum(math.sin(math.radians(g)) for g in grados)
    coseno = sum(math.cos(math.radians(g)) for g in grados)
    if abs(seno) < 1e-9 and abs(coseno) < 1e-9:
        return None
    return math.degrees(math.atan2(seno, coseno)) % 360.0


def construir_consenso(
    respuestas: list[RespuestaFuente],
    desde: datetime,
    horas: int,
) -> list[Consenso]:
    """Agrupa todas las lecturas por hora y las combina."""
    inicio = truncar_hora(desde)
    por_hora: dict[datetime, list[Lectura]] = {}

    for respuesta in respuestas:
        for lectura in respuesta.lecturas:
            clave = truncar_hora(lectura.instante)
            if clave < inicio:
                continue
            delta = (clave - inicio).total_seconds() / 3600
            if delta > horas:
                continue
            por_hora.setdefault(clave, []).append(lectura)

    resultado: list[Consenso] = []
    for instante in sorted(por_hora):
        lecturas = por_hora[instante]

        alturas = [l.altura_ola_m for l in lecturas if l.altura_ola_m is not None]
        periodos = [l.periodo_ola_s for l in lecturas if l.periodo_ola_s is not None]
        vientos = [l.viento_nudos for l in lecturas if l.viento_nudos is not None]
        rachas = [l.racha_nudos for l in lecturas if l.racha_nudos is not None]
        direcciones = [
            l.direccion_viento_grados
            for l in lecturas
            if l.direccion_viento_grados is not None
        ]

        resultado.append(
            Consenso(
                instante=instante,
                altura_ola_m=_combinar(alturas),
                altura_ola_min_m=min(alturas) if alturas else None,
                altura_ola_max_m=max(alturas) if alturas else None,
                altura_ola_p75_m=_percentil75(alturas),
                periodo_ola_s=_combinar(periodos),
                viento_nudos=_combinar(vientos),
                racha_nudos=_combinar(rachas),
                racha_max_nudos=max(rachas) if rachas else None,
                direccion_viento_grados=_promediar_angulos(direcciones),
                fuentes_ola=len(alturas),
                fuentes_viento=len(rachas) or len(vientos),
            )
        )
    return resultado

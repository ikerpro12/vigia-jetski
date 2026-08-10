"""Convierte números en un veredicto: ¿hay que bajar a por la moto?

Dos ideas importantes más allá de "ola alta = malo":

1. VIENTO DE MAR. Cala Tarida mira al oeste. Con viento del sector SO-NO el
   oleaje entra directo en la cala y además empuja la moto hacia la costa: es
   la situación peligrosa. Con viento de levante la cala queda a resguardo y
   la misma altura de ola es mucho menos preocupante. Por eso el viento de mar
   sube un nivel el aviso, y el de tierra lo baja.

2. PERIODO CORTO. Un mar de viento de periodo bajo (< 4 s) con altura parecida
   golpea más seco y hace trabajar mucho más al amarre que un mar de fondo
   largo. También suma.
"""

from __future__ import annotations

from typing import Optional

from .config import Config, Umbrales
from .modelo import Consenso, Evaluacion, Nivel

ROSA = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO",
]


def rumbo(grados: Optional[float]) -> str:
    """Pasa grados a punto cardinal en español (de dónde viene el viento)."""
    if grados is None:
        return "?"
    indice = int((grados % 360) / 22.5 + 0.5) % 16
    return ROSA[indice]


def es_viento_de_mar(grados: Optional[float], cfg: Config) -> bool:
    """¿Sopla desde el mar hacia la cala?"""
    if grados is None:
        return False
    g = grados % 360
    desde, hasta = cfg.sector_mar_desde, cfg.sector_mar_hasta
    if desde <= hasta:
        return desde <= g <= hasta
    # Sector que cruza el norte (p.ej. 315°-45°).
    return g >= desde or g <= hasta


def _nivel_por_ola(altura: Optional[float], u: Umbrales) -> Nivel:
    if altura is None:
        return Nivel.VERDE
    if altura >= u.ola_rojo:
        return Nivel.ROJO
    if altura >= u.ola_naranja:
        return Nivel.NARANJA
    if altura >= u.ola_amarillo:
        return Nivel.AMARILLO
    return Nivel.VERDE


def _nivel_por_racha(racha: Optional[float], u: Umbrales) -> Nivel:
    if racha is None:
        return Nivel.VERDE
    if racha >= u.racha_rojo:
        return Nivel.ROJO
    if racha >= u.racha_naranja:
        return Nivel.NARANJA
    if racha >= u.racha_amarillo:
        return Nivel.AMARILLO
    return Nivel.VERDE


def _acotar(valor: int) -> Nivel:
    return Nivel(max(Nivel.VERDE, min(Nivel.ROJO, valor)))


def evaluar_hora(punto: Consenso, cfg: Config) -> Evaluacion:
    u = cfg.umbrales
    motivos: list[str] = []

    nivel_ola = _nivel_por_ola(punto.altura_ola_m, u)
    nivel_racha = _nivel_por_racha(punto.racha_nudos, u)
    nivel = max(nivel_ola, nivel_racha)

    if nivel_ola > Nivel.VERDE and punto.altura_ola_m is not None:
        motivos.append(f"olas de {punto.altura_ola_m:.1f} m")
    if nivel_racha > Nivel.VERDE and punto.racha_nudos is not None:
        motivos.append(f"rachas de {punto.racha_nudos:.0f} nudos")

    de_mar = es_viento_de_mar(punto.direccion_viento_grados, cfg)

    # El viento de mar solo agrava si ya hay algo de mar de fondo o de viento:
    # con la cala en calma, que sople del oeste flojito no es un problema.
    if de_mar and nivel > Nivel.VERDE:
        nivel = _acotar(nivel + 1)
        motivos.append(
            f"viento de mar del {rumbo(punto.direccion_viento_grados)} "
            "(entra directo en la cala)"
        )
    elif not de_mar and nivel > Nivel.VERDE and punto.direccion_viento_grados is not None:
        nivel = _acotar(nivel - 1)
        motivos.append(
            f"viento de tierra del {rumbo(punto.direccion_viento_grados)} "
            "(la cala queda a resguardo)"
        )

    # Mar de viento corto y picado: castiga más el amarre.
    if (
        punto.periodo_ola_s is not None
        and punto.periodo_ola_s < 4.0
        and nivel >= Nivel.AMARILLO
    ):
        nivel = _acotar(nivel + 1)
        motivos.append(f"periodo corto de {punto.periodo_ola_s:.1f} s (mar picada)")

    # Desacuerdo entre modelos. Con diez y pico votando, que uno se dispare es
    # lo normal, así que para escalar se mira el percentil 75 (lo que dicen los
    # más pesimistas) y no el máximo, que sería un aviso constante.
    if (
        punto.altura_ola_min_m is not None
        and punto.altura_ola_max_m is not None
        and punto.altura_ola_max_m - punto.altura_ola_min_m >= 0.4
    ):
        motivos.append(
            f"los modelos discrepan ({punto.altura_ola_min_m:.1f}–"
            f"{punto.altura_ola_max_m:.1f} m)"
        )
        prudente = punto.altura_ola_p75_m
        if prudente is not None and _nivel_por_ola(prudente, u) > nivel:
            nivel = _acotar(nivel + 1)
            motivos.append(f"escalado por prudencia (p75 {prudente:.1f} m)")

    return Evaluacion(
        instante=punto.instante, nivel=nivel, motivos=motivos, viento_de_mar=de_mar
    )


def evaluar_serie(serie: list[Consenso], cfg: Config) -> list[Evaluacion]:
    return [evaluar_hora(punto, cfg) for punto in serie]


def primer_aviso(
    evaluaciones: list[Evaluacion], nivel_minimo: Nivel
) -> Optional[Evaluacion]:
    """La primera hora que alcanza o supera el nivel dado. Ahí está el margen."""
    for evaluacion in evaluaciones:
        if evaluacion.nivel >= nivel_minimo:
            return evaluacion
    return None


def pico(evaluaciones: list[Evaluacion]) -> Optional[Evaluacion]:
    """El peor momento de toda la ventana."""
    if not evaluaciones:
        return None
    return max(evaluaciones, key=lambda e: (e.nivel, -e.instante.timestamp()))

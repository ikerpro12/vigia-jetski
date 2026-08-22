"""Convierte números en un veredicto: ¿hay que bajar a por la moto?

Dos ideas importantes más allá de "ola alta = malo":

1. VIENTO DE MAR. Cala Corral se abre al oeste (rumbo 261, calculado con la
   linea de costa de OpenStreetMap). Con viento del sector S-NNO el
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
        # El resguardo tiene un límite. Con rachas fuertes, un viento de
        # tierra tampoco es inofensivo: puede arrancar el amarre y llevarse la
        # moto mar adentro, que es peor que dejarla contra la arena. A partir
        # del umbral naranja de racha ya no se rebaja nada.
        racha_fuerte = (
            punto.racha_nudos is not None and punto.racha_nudos >= u.racha_naranja
        )
        if racha_fuerte:
            motivos.append(
                f"viento de tierra del {rumbo(punto.direccion_viento_grados)}, "
                "pero con rachas fuertes: puede llevarse la moto mar adentro"
            )
        else:
            nivel = _acotar(nivel - 1)
            motivos.append(
                f"viento de tierra del {rumbo(punto.direccion_viento_grados)} "
                "(la cala queda a resguardo)"
            )

    # Mar de viento corto y picado: castiga más el amarre. Pero solo si hay
    # mar de verdad. Con 20 cm de rizado el periodo da igual, y sin este
    # filtro salian rojos absurdos: racha amarilla + viento de mar + periodo
    # corto sumaban dos escalones sobre una mar practicamente plana.
    if (
        punto.periodo_ola_s is not None
        and punto.periodo_ola_s < 4.0
        and nivel >= Nivel.AMARILLO
        and punto.altura_ola_m is not None
        and punto.altura_ola_m >= u.ola_amarillo
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


def corrobora_aviso(serie: list[Consenso], cfg: Config) -> tuple[bool, str]:
    """¿Respalda algo el aviso oficial de AEMET, o va solo?

    AEMET avisa por zonas grandes y por fenómenos que un modelo de oleaje no
    ve (tormentas, turbonadas). Pero un aviso para "aguas de Ibiza y
    Formentera" puede referirse a un chubasco al otro lado de la isla mientras
    en Cala Corral no pasa nada.

    Se busca cualquier indicio en las próximas horas: mar que se levanta,
    rachas que suben o lluvia prevista. Si no hay ninguno, el aviso se enseña
    igual pero no dispara un mensaje.
    """
    u = cfg.umbrales
    for punto in serie:
        if punto.altura_ola_m is not None and punto.altura_ola_m >= u.ola_amarillo:
            return True, f"la mar sube a {punto.altura_ola_m:.1f} m"
        if punto.racha_nudos is not None and punto.racha_nudos >= u.racha_amarillo:
            return True, f"rachas de {punto.racha_nudos:.0f} nudos"
        if punto.lluvia_mm is not None and punto.lluvia_mm >= 1.0:
            return True, f"lluvia de {punto.lluvia_mm:.1f} mm"
        if punto.prob_lluvia_pct is not None and punto.prob_lluvia_pct >= 50:
            return True, f"{punto.prob_lluvia_pct:.0f}% de probabilidad de lluvia"
    return False, "ningún modelo ve nada: mar plana, sin viento y sin lluvia"


def primer_cambio(
    evaluaciones: list[Evaluacion], desde_nivel: Nivel
) -> Optional[Evaluacion]:
    """Primera hora en la que el nivel supera al actual. El "ojo, que viene"."""
    for evaluacion in evaluaciones[1:]:
        if evaluacion.nivel > desde_nivel:
            return evaluacion
    return None


def primera_lluvia(serie: list[Consenso]) -> Optional[Consenso]:
    """Primera hora con lluvia apreciable."""
    for punto in serie:
        if punto.lluvia_mm is not None and punto.lluvia_mm >= 0.5:
            return punto
        if punto.prob_lluvia_pct is not None and punto.prob_lluvia_pct >= 60:
            return punto
    return None


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

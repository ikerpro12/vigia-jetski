"""Traducir números a lenguaje de mar, y decir si se puede salir.

El boletín entero de AEMET era un ladrillo de cinco líneas que nadie lee en
WhatsApp. Es más útil quedarse con lo que un patrón mira de verdad: cómo está
la mar en la escala de siempre, cuánto viento hace en Beaufort, si el agua
está buena y si merece la pena sacar la moto ahora o esperar a la tarde.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from .modelo import Consenso

# Escala Douglas del estado de la mar, por altura significativa (m).
# Son los mismos términos que usa AEMET en sus boletines.
# Los tramos son el límite INFERIOR de cada grado: 0,2 m es marejadilla, no
# mar rizada. Aquí se nota si te equivocas, así que van como manda la escala.
DOUGLAS: tuple[tuple[float, str], ...] = (
    (0.0, "calma chicha"),
    (0.01, "mar rizada"),
    (0.10, "marejadilla"),
    (0.50, "marejada"),
    (1.25, "fuerte marejada"),
    (2.50, "mar gruesa"),
    (4.00, "mar muy gruesa"),
    (6.00, "mar arbolada"),
    (9.00, "mar montañosa"),
)

# Escala Beaufort, por velocidad media del viento en nudos.
BEAUFORT: tuple[tuple[float, int, str], ...] = (
    (1, 0, "calma"),
    (4, 1, "ventolina"),
    (7, 2, "flojito"),
    (11, 3, "flojo"),
    (17, 4, "bonancible"),
    (22, 5, "fresquito"),
    (28, 6, "fresco"),
    (34, 7, "frescachón"),
    (41, 8, "temporal"),
    (48, 9, "temporal fuerte"),
    (56, 10, "temporal duro"),
    (64, 11, "temporal muy duro"),
)


def estado_mar(altura_m: Optional[float]) -> str:
    """Altura de ola -> término de la escala Douglas."""
    if altura_m is None:
        return "?"
    nombre = DOUGLAS[0][1]
    for limite, etiqueta in DOUGLAS:
        if altura_m >= limite:
            nombre = etiqueta
        else:
            break
    return nombre


def fuerza_viento(nudos: Optional[float]) -> tuple[int, str]:
    """Velocidad -> (grado Beaufort, nombre)."""
    if nudos is None:
        return (0, "?")
    for limite, grado, nombre in BEAUFORT:
        if nudos < limite:
            return (grado, nombre)
    return (12, "huracán")


# Veredicto para SALIR con la moto: nada que ver con el aviso de que se hunda
# fondeada. Aquí lo que importa es si se puede planear a gusto o si vas a ir
# dando botes y acabar con la espalda hecha polvo.
def veredicto_salida(
    altura_m: Optional[float],
    racha_nudos: Optional[float],
    periodo_s: Optional[float] = None,
) -> tuple[str, str]:
    """Devuelve (emoji, frase)."""
    if altura_m is None and racha_nudos is None:
        return ("❔", "Sin datos suficientes.")

    ola = altura_m if altura_m is not None else 0.0
    racha = racha_nudos if racha_nudos is not None else 0.0

    # Un mar corto y picado incomoda mucho más que la misma altura tendida.
    picada = periodo_s is not None and periodo_s < 4.0

    if ola < 0.2 and racha < 12:
        return ("🟢", "Balsa. Ideal para ir a tope.")
    if ola < 0.4 and racha < 17:
        frase = "Muy buena. Se plancha sin problema."
        if picada:
            frase = "Buena, aunque algo picada: notarás los golpes a tope de gas."
        return ("🟢", frase)
    if ola < 0.7 and racha < 22:
        return ("🟡", "Aceptable. Se puede, pero vas a saltar bastante.")
    if ola < 1.0 and racha < 28:
        return ("🟠", "Incómoda. Solo si tienes experiencia y sin prisa.")
    return ("🔴", "Mala para salir. Mejor déjalo para otro día.")


def _molestia(punto: Consenso) -> float:
    """Cuánto incomoda una hora para navegar. Cuanto más bajo, mejor."""
    ola = punto.altura_ola_m if punto.altura_ola_m is not None else 0.0
    racha = punto.racha_nudos if punto.racha_nudos is not None else 0.0
    castigo = 0.0
    if punto.periodo_ola_s is not None and punto.periodo_ola_s < 4.0:
        castigo += 0.15
    if punto.lluvia_mm:
        castigo += min(0.4, punto.lluvia_mm * 0.1)
    # La ola pesa más que el viento: es lo que te hace saltar.
    return ola + racha / 45.0 + castigo


def mejor_ventana(
    serie: Sequence[Consenso],
    amanecer: Optional[datetime],
    atardecer: Optional[datetime],
    horas: int = 2,
) -> Optional[tuple[datetime, datetime]]:
    """El tramo más tranquilo con luz dentro de la previsión.

    Solo se proponen horas con sol: salir de noche con la moto no es plan.
    """
    con_luz = [
        p
        for p in serie
        if (amanecer is None or p.instante >= amanecer)
        and (atardecer is None or p.instante <= atardecer)
    ]
    if len(con_luz) < horas:
        return None

    mejor, mejor_puntuacion = None, float("inf")
    for i in range(len(con_luz) - horas + 1):
        tramo = con_luz[i : i + horas]
        # El peor momento del tramo manda: de nada sirve una media buena si
        # en mitad de la salida se pone imposible.
        puntuacion = max(_molestia(p) for p in tramo)
        if puntuacion < mejor_puntuacion:
            mejor, mejor_puntuacion = (tramo[0].instante, tramo[-1].instante), puntuacion
    return mejor


def luz_restante(ahora: datetime, atardecer: Optional[datetime]) -> Optional[str]:
    """Cuánta luz queda, en texto. Para no quedarte sin sol a medio camino."""
    if atardecer is None or ahora >= atardecer:
        return None
    minutos = int((atardecer - ahora).total_seconds() // 60)
    horas, resto = divmod(minutos, 60)
    if horas and resto:
        return f"{horas} h {resto} min"
    if horas:
        return f"{horas} h"
    return f"{resto} min"


def descripcion_agua(grados: Optional[float]) -> str:
    """Temperatura del agua con una pizca de contexto."""
    if grados is None:
        return ""
    if grados >= 26:
        return f"{grados:.0f} °C (como un caldo)"
    if grados >= 22:
        return f"{grados:.0f} °C (buenísima)"
    if grados >= 19:
        return f"{grados:.0f} °C (se está bien)"
    if grados >= 16:
        return f"{grados:.0f} °C (fresquita)"
    return f"{grados:.0f} °C (fría, mejor con neopreno)"


def nudos_a_kmh(nudos: Optional[float]) -> Optional[float]:
    """1 nudo = 1,852 km/h. En el mensaje se enseñan las dos unidades: los
    nudos son lo que usan los partes marítimos, pero el km/h es lo que uno
    tiene en la cabeza."""
    if nudos is None:
        return None
    return nudos * 1.852


def viento_con_unidades(nudos: Optional[float]) -> str:
    """'12 kn (22 km/h)'."""
    if nudos is None:
        return "?"
    return f"{nudos:.0f} kn ({nudos * 1.852:.0f} km/h)"


# --- Sol y UV --------------------------------------------------------------
# Escala oficial de la OMS. Los minutos son orientativos y para piel clara
# sin protección: es el dato que la gente entiende de verdad, mucho más que
# "índice 8". Con crema y a la sombra cambia todo, claro.
ESCALA_UV: tuple[tuple[float, str, str, str], ...] = (
    (3.0, "🟢", "bajo", "Puedes estar al sol sin agobiarte."),
    (6.0, "🟡", "moderado", "Con crema vas bien. Te quemarías en ~40 min sin nada."),
    (8.0, "🟠", "alto", "Crema sí o sí. Te quemas en ~25 min sin protección."),
    (11.0, "🔴", "muy alto", "Pica de verdad: ~15 min y ya te has quemado."),
)
UV_EXTREMO = ("🟣", "extremo", "Brutal. ~10 min al sol y quemadura segura.")


def nivel_uv(indice: Optional[float]) -> tuple[str, str, str]:
    """Índice UV -> (emoji, etiqueta, frase en cristiano)."""
    if indice is None:
        return ("", "?", "")
    for limite, emoji, etiqueta, consejo in ESCALA_UV:
        if indice < limite:
            return (emoji, etiqueta, consejo)
    return UV_EXTREMO


def franja_de_sol(
    serie: Sequence[Consenso], umbral: float = 6.0
) -> Optional[tuple[datetime, datetime, Consenso]]:
    """Cuándo pica el sol de verdad y cuál es el peor momento.

    Devuelve (inicio, fin, hora_del_maximo) del primer tramo del día en el que
    el UV pasa de `umbral` (6 = "alto" en la escala de la OMS).
    """
    fuertes = [p for p in serie if p.uv is not None and p.uv >= umbral]
    if not fuertes:
        return None

    # Solo el primer bloque continuo: mañana ya se verá.
    bloque = [fuertes[0]]
    for anterior, actual in zip(fuertes, fuertes[1:]):
        if (actual.instante - anterior.instante).total_seconds() > 3600 * 1.5:
            break
        bloque.append(actual)

    pico = max(bloque, key=lambda p: p.uv or 0)
    return (bloque[0].instante, bloque[-1].instante, pico)

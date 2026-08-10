"""Redacta el mensaje en castellano que llega al WhatsApp."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .config import Config
from .evaluacion import pico, primer_aviso, rumbo
from .modelo import Consenso, Evaluacion, Nivel, RespuestaFuente

CONSEJO = {
    Nivel.VERDE: "Mar tranquila. La moto puede quedarse donde está.",
    Nivel.AMARILLO: "Vigila. Aún no es urgente, pero echa un ojo al parte.",
    Nivel.NARANJA: "Baja a por la moto o revisa el amarre en cuanto puedas.",
    Nivel.ROJO: "URGENTE: saca la moto del agua. Riesgo real de que se hunda o rompa amarras.",
}


def _margen(ahora: datetime, objetivo: datetime) -> str:
    minutos = int((objetivo - ahora).total_seconds() // 60)
    if minutos <= 0:
        return "ya mismo"
    horas, resto = divmod(minutos, 60)
    if horas and resto:
        return f"en {horas} h {resto} min"
    if horas:
        return f"en {horas} h"
    return f"en {resto} min"


def _consejo(nivel: Nivel, ahora: datetime, disparo: Optional[Evaluacion]) -> str:
    """El consejo depende del nivel, pero también de cuánto margen queda.

    No es lo mismo un rojo que ya está encima que uno previsto para dentro de
    ocho horas: en el segundo caso hay tiempo de organizarse, y decir "urgente"
    solo consigue que dentro de un mes ya nadie lea los avisos.
    """
    if nivel == Nivel.VERDE or disparo is None:
        return CONSEJO[nivel]

    horas = (disparo.instante - ahora).total_seconds() / 3600
    if horas <= 1:
        return CONSEJO[nivel]

    margen = _margen(ahora, disparo.instante)
    if nivel >= Nivel.ROJO:
        return (
            f"Aún hay tiempo, pero organízate ya: la moto debería estar fuera "
            f"del agua antes de {disparo.instante.strftime('%H:%M')} ({margen})."
        )
    if nivel == Nivel.NARANJA:
        return (
            f"Tienes margen ({margen}). Aprovecha para bajar a por la moto o "
            "reforzar el amarre antes de que empeore."
        )
    return CONSEJO[nivel]


def _linea_hora(punto: Consenso) -> str:
    trozos = [punto.instante.strftime("%H:%M")]
    if punto.altura_ola_m is not None:
        trozos.append(f"olas {punto.altura_ola_m:.1f} m")
    if punto.racha_nudos is not None:
        trozos.append(f"rachas {punto.racha_nudos:.0f} kn")
    if punto.direccion_viento_grados is not None:
        trozos.append(rumbo(punto.direccion_viento_grados))
    return " · ".join(trozos)


def componer(
    cfg: Config,
    ahora: datetime,
    serie: list[Consenso],
    evaluaciones: list[Evaluacion],
    respuestas: list[RespuestaFuente],
    para_imagen: bool = False,
) -> tuple[Nivel, str]:
    """Devuelve (nivel máximo de la ventana, texto del mensaje).

    Con `para_imagen` se genera la versión que va como pie de foto: WhatsApp
    corta los pies a 1024 caracteres, y además la tabla de próximas horas y el
    boletín largo ya se ven en el mapa, así que repetirlos sobra.
    """
    peor = pico(evaluaciones)
    nivel = peor.nivel if peor else Nivel.VERDE

    # Un aviso oficial de AEMET para nuestra zona manda sobre los modelos: son
    # cosas (tormentas, turbonadas) que un modelo de oleaje no ve venir. Nunca
    # baja el nivel, solo lo sube a NARANJA como mínimo.
    aviso_oficial = next(
        (r.aviso_oficial for r in respuestas if r.aviso_oficial), None
    )
    if aviso_oficial:
        nivel = max(nivel, Nivel.NARANJA)

    lineas: list[str] = []
    lineas.append(f"{nivel.emoji} *VIGÍA JETSKI · {cfg.lugar}*")
    lineas.append(f"_{ahora.strftime('%d/%m/%Y %H:%M')} · nivel {nivel.etiqueta}_")
    lineas.append("")

    # Situación actual.
    if serie:
        actual = serie[0]
        lineas.append("*Ahora mismo*")
        if actual.altura_ola_m is not None:
            detalle = f"• Olas: {actual.altura_ola_m:.1f} m"
            if (
                actual.altura_ola_min_m is not None
                and actual.altura_ola_max_m is not None
                and actual.altura_ola_max_m - actual.altura_ola_min_m >= 0.15
            ):
                detalle += (
                    f" (fuentes: {actual.altura_ola_min_m:.1f}–"
                    f"{actual.altura_ola_max_m:.1f} m)"
                )
            if actual.periodo_ola_s:
                detalle += f", periodo {actual.periodo_ola_s:.0f} s"
            lineas.append(detalle)
        if actual.viento_nudos is not None:
            viento = f"• Viento: {actual.viento_nudos:.0f} kn"
            if actual.racha_nudos:
                viento += f", rachas {actual.racha_nudos:.0f} kn"
            if actual.direccion_viento_grados is not None:
                viento += f" del {rumbo(actual.direccion_viento_grados)}"
            lineas.append(viento)
        lineas.append("")

    # El aviso oficial va antes que nada: es lo que más peso tiene.
    if aviso_oficial:
        lineas.append("*🛑 AVISO OFICIAL DE AEMET*")
        lineas.append(aviso_oficial)
        lineas.append("")

    # El aviso propiamente dicho: cuánto margen hay.
    umbral = Nivel(cfg.nivel_minimo_aviso)
    disparo = primer_aviso(evaluaciones, umbral)
    if disparo is not None:
        cuando = _margen(ahora, disparo.instante)
        lineas.append(
            f"*⚠️ Aviso {disparo.nivel.etiqueta} {cuando}* "
            f"({disparo.instante.strftime('%H:%M')})"
        )
        if disparo.motivos:
            for motivo in disparo.motivos:
                lineas.append(f"  – {motivo}")
        lineas.append("")

    if peor is not None and peor.nivel > Nivel.VERDE and (
        disparo is None or peor.instante != disparo.instante
    ):
        lineas.append(
            f"*Alcanza nivel {peor.nivel.etiqueta} a las* "
            f"{peor.instante.strftime('%H:%M')} ({_margen(ahora, peor.instante)})"
        )
        lineas.append("")

    lineas.append(f"*Qué hacer:* {_consejo(nivel, ahora, disparo)}")
    lineas.append("")

    # Próximas horas. En la versión con mapa se omite: la gráfica lo enseña.
    if serie and not para_imagen:
        lineas.append("*Próximas horas*")
        for punto in serie[1 : cfg.horas_vista + 1 : 3]:
            lineas.append(f"  {_linea_hora(punto)}")
        lineas.append("")

    # Boletín oficial, si lo hay.
    for respuesta in respuestas:
        if not respuesta.boletin:
            continue
        boletin = respuesta.boletin
        if para_imagen and len(boletin) > 220:
            boletin = boletin[:220].rsplit(" ", 1)[0] + "…"
        lineas.append(f"*{respuesta.nombre}*")
        lineas.append(f"_{boletin}_")
        lineas.append("")

    # Transparencia sobre las fuentes: importa saber cuántas respondieron.
    vivas = [r.nombre for r in respuestas if r.ok or r.boletin]
    caidas = [f"{r.nombre} ({r.error})" for r in respuestas if not (r.ok or r.boletin)]
    if para_imagen:
        lineas.append(f"_{len(vivas)} fuentes OK_")
    else:
        lineas.append(f"_Fuentes OK ({len(vivas)}): {', '.join(vivas) or 'ninguna'}_")
        if caidas:
            lineas.append(f"_Sin respuesta: {'; '.join(caidas)}_")

    texto = "\n".join(lineas).strip()

    # Red de seguridad: si aun así se pasa, se recorta por líneas enteras.
    if para_imagen and len(texto) > 1024:
        recortado: list[str] = []
        for linea in texto.splitlines():
            if sum(len(x) + 1 for x in recortado) + len(linea) > 1000:
                break
            recortado.append(linea)
        texto = "\n".join(recortado).rstrip() + "\n…"

    return nivel, texto


def resumen_consola(nivel: Nivel, texto: str) -> str:
    return f"\n{'=' * 60}\n{texto}\n{'=' * 60}\n"


def sin_datos(cfg: Config, respuestas: list[RespuestaFuente]) -> str:
    """Mensaje para cuando NINGUNA fuente ha respondido: eso también es noticia."""
    fallos = "; ".join(f"{r.nombre}: {r.error}" for r in respuestas)
    return (
        f"⚫ *VIGÍA JETSKI · {cfg.lugar}*\n\n"
        "No he podido consultar *ninguna* fuente de datos. "
        "No sé cómo está la mar, así que no te fíes de la ausencia de avisos.\n\n"
        f"_Detalle: {fallos}_"
    )

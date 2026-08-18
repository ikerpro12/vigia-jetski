"""Redacta el mensaje en castellano que llega al WhatsApp."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .config import Config
from .evaluacion import (
    corrobora_aviso,
    pico,
    primer_aviso,
    primer_cambio,
    primera_lluvia,
    rumbo,
)
from .modelo import Consenso, Evaluacion, Nivel, RespuestaFuente
from .nautica import (
    descripcion_agua,
    estado_mar,
    fuerza_viento,
    luz_restante,
    mejor_ventana,
    veredicto_salida,
)

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


def _bloque_proximos_dias(serie_larga, cfg, ahora) -> list[str]:
    """Resumen por días de lo que viene después de la ventana de aviso."""
    from .evaluacion import evaluar_serie

    dias_nombre = ("lunes", "martes", "miércoles", "jueves",
                   "viernes", "sábado", "domingo")

    evaluaciones = evaluar_serie(list(serie_larga), cfg)
    por_dia: dict = {}
    for punto, evaluacion in zip(serie_larga, evaluaciones):
        if punto.instante.date() == ahora.date():
            continue  # hoy ya está contado más arriba
        por_dia.setdefault(punto.instante.date(), []).append((punto, evaluacion))

    filas = []
    for dia, valores in sorted(por_dia.items()):
        peor = max(e.nivel for _, e in valores)
        if peor < Nivel.AMARILLO:
            continue  # un día tranquilo no merece ocupar sitio
        olas = [p.altura_ola_m for p, _ in valores if p.altura_ola_m is not None]
        rachas = [p.racha_nudos for p, _ in valores if p.racha_nudos is not None]
        filas.append(
            f"  {peor.emoji} {dias_nombre[dia.weekday()].capitalize()} "
            f"{dia:%d/%m}: hasta {max(olas or [0]):.1f} m "
            f"y {max(rachas or [0]):.0f} kn"
        )

    if not filas:
        return []
    return ["*Próximos días*"] + filas + [""]


def componer(
    cfg: Config,
    ahora: datetime,
    serie: list[Consenso],
    evaluaciones: list[Evaluacion],
    respuestas: list[RespuestaFuente],
    para_imagen: bool = False,
    serie_larga: Optional[list[Consenso]] = None,
) -> tuple[Nivel, str]:
    """Devuelve (nivel máximo de la ventana, texto del mensaje).

    Con `para_imagen` se genera la versión que va como pie de foto: WhatsApp
    corta los pies a 1024 caracteres, y además la tabla de próximas horas y el
    boletín largo ya se ven en el mapa, así que repetirlos sobra.
    """
    peor = pico(evaluaciones)
    nivel = peor.nivel if peor else Nivel.VERDE

    # Un aviso oficial de AEMET pesa, pero no a ciegas. Avisa por zonas
    # grandes, y su aviso para "aguas de Ibiza y Formentera" puede ser por un
    # chubasco al otro lado de la isla. Así que:
    #
    #   * Si algún modelo lo respalda (mar, viento o lluvia) -> NARANJA: se
    #     manda el aviso.
    #   * Si no lo respalda nadie -> AMARILLO: no se manda nada, pero se
    #     vigila más a menudo y el aviso aparece en el parte diario.
    #
    # Nunca se ignora del todo: una turbonada no la ve ningún modelo de olas.
    aviso_oficial = next(
        (r.aviso_oficial for r in respuestas if r.aviso_oficial), None
    )
    respaldado, razon_respaldo = (False, "")
    if aviso_oficial:
        respaldado, razon_respaldo = corrobora_aviso(list(serie), cfg)
        nivel = max(nivel, Nivel.NARANJA if respaldado else Nivel.AMARILLO)

    lineas: list[str] = []
    lineas.append(f"{nivel.emoji} *VIGÍA JETSKI · {cfg.lugar}*")
    lineas.append(f"_{ahora.strftime('%d/%m/%Y %H:%M')} · nivel {nivel.etiqueta}_")
    lineas.append("")

    # Situación actual, en lenguaje de mar y no solo en cifras.
    atardecer = next((r.atardecer for r in respuestas if r.atardecer), None)
    amanecer = next((r.amanecer for r in respuestas if r.amanecer), None)

    if serie:
        actual = serie[0]
        lineas.append("*Ahora mismo*")

        if actual.altura_ola_m is not None:
            detalle = f"• Mar: {estado_mar(actual.altura_ola_m)}, {actual.altura_ola_m:.1f} m"
            if actual.periodo_ola_s:
                detalle += f" cada {actual.periodo_ola_s:.0f} s"
            if (
                actual.altura_ola_min_m is not None
                and actual.altura_ola_max_m is not None
                and actual.altura_ola_max_m - actual.altura_ola_min_m >= 0.15
            ):
                detalle += (
                    f" _(modelos: {actual.altura_ola_min_m:.1f}–"
                    f"{actual.altura_ola_max_m:.1f})_"
                )
            lineas.append(detalle)

        if actual.viento_nudos is not None:
            grado, nombre = fuerza_viento(actual.viento_nudos)
            viento = f"• Viento: {nombre} (fuerza {grado}), {actual.viento_nudos:.0f} kn"
            if actual.direccion_viento_grados is not None:
                viento += f" del {rumbo(actual.direccion_viento_grados)}"
            if actual.racha_nudos:
                viento += f", rachas {actual.racha_nudos:.0f}"
            lineas.append(viento)

        extras = []
        if actual.temperatura_mar_c is not None:
            extras.append(f"agua {descripcion_agua(actual.temperatura_mar_c)}")
        queda = luz_restante(ahora, atardecer)
        if queda and atardecer:
            extras.append(f"luz hasta las {atardecer:%H:%M} ({queda})")
        if extras:
            # Solo la inicial: `.capitalize()` pondría "30 °c" en minúscula.
            texto_extras = " · ".join(extras)
            lineas.append(f"• {texto_extras[0].upper()}{texto_extras[1:]}")
        lineas.append("")

        # Veredicto para SALIR: otra pregunta distinta a la de si se hunde.
        emoji, frase = veredicto_salida(
            actual.altura_ola_m, actual.racha_nudos, actual.periodo_ola_s
        )
        lineas.append(f"*{emoji} Para salir con la moto*")
        lineas.append(frase)
        ventana = mejor_ventana(list(serie), amanecer, atardecer)
        if ventana:
            inicio, fin = ventana
            cuando = "hoy" if inicio.date() == ahora.date() else "mañana"
            lineas.append(
                f"_Mejor rato {cuando}: {inicio:%H:%M}–{fin:%H:%M}_"
            )
        lineas.append("")

    # El aviso oficial va antes que nada: es lo que más peso tiene.
    if aviso_oficial:
        lineas.append("*🛑 AVISO OFICIAL DE AEMET*")
        lineas.append(aviso_oficial)
        if respaldado:
            lineas.append(f"_Los modelos lo respaldan: {razon_respaldo}._")
        else:
            lineas.append(
                f"_Pero {razon_respaldo}. Puede ser por otra zona de la isla, "
                "así que se vigila sin dar la alarma._"
            )
        lineas.append("")

    # Qué viene. El objetivo de todo esto es enterarse ANTES, así que si algo
    # empeora más adelante conviene decirlo aunque ahora esté todo tranquilo.
    proximas: list[str] = []
    cambio = primer_cambio(list(evaluaciones), evaluaciones[0].nivel if evaluaciones else Nivel.VERDE)
    if cambio is not None:
        detalle = ", ".join(cambio.motivos[:2]) if cambio.motivos else ""
        proximas.append(
            f"  {cambio.nivel.emoji} {cambio.instante:%H:%M} "
            f"({_margen(ahora, cambio.instante)}): sube a {cambio.nivel.etiqueta}"
            + (f" — {detalle}" if detalle else "")
        )
    lluvia = primera_lluvia(list(serie))
    if lluvia is not None:
        que = []
        if lluvia.lluvia_mm:
            que.append(f"{lluvia.lluvia_mm:.1f} mm")
        if lluvia.prob_lluvia_pct:
            que.append(f"{lluvia.prob_lluvia_pct:.0f}%")
        proximas.append(
            f"  🌧️ {lluvia.instante:%H:%M} ({_margen(ahora, lluvia.instante)}): "
            f"lluvia{' ' + ' · '.join(que) if que else ''}"
        )
    if proximas:
        lineas.append("*Lo que viene*")
        lineas.extend(proximas)
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

    # El boletín completo de AEMET ya no se pega: eran cinco líneas de
    # sinóptica ("baja de 1014 al norte de Argelia...") que nadie lee en el
    # móvil. Lo que importa de AEMET es su aviso, y ese ya va arriba del todo.

    # Pronóstico a varios días. Solo en los partes diarios, y solo si hay algo
    # que contar más allá de la ventana de aviso.
    #
    # Este bloque existe por un fallo real: el temporal del 19-21/08/2026 se
    # veía venir con dos días, pero el vigía solo mira 12 horas y no dijo nada
    # hasta tenerlo encima. Subir la ventana de aviso no vale, porque el nivel
    # es el peor de toda ella y el semáforo se quedaría en rojo tres días
    # seguidos. Así que la previsión larga informa, pero no dispara.
    if serie_larga:
        lineas.extend(_bloque_proximos_dias(serie_larga, cfg, ahora))

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

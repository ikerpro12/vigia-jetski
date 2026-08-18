"""Punto de entrada.

    python -m vigia                una pasada y salir (para cron)
    python -m vigia --bucle        se queda corriendo con intervalo adaptativo
    python -m vigia --forzar       manda el parte aunque esté todo en verde
    python -m vigia --probar       manda un mensaje de prueba al WhatsApp
    python -m vigia --simular      inventa un temporal para ver el aviso
    python -m vigia --sin-enviar   solo imprime, no envía nada
    python -m vigia --pronostico 3 resumen de 3 días con los momentos clave
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import timedelta

from .config import Config
from .consenso import construir_consenso
from .estado import (
    Estado,
    actualizar,
    anotar_comprobacion,
    anotar_stormglass,
    cargar,
    decidir,
    guardar,
    intervalo_sugerido,
    parte_pendiente,
    toca_comprobar,
)
from .evaluacion import evaluar_serie, rumbo
from .fuentes import consultar_todas
from .fuentes.base import ahora as ahora_en, truncar_hora
from .grafico import dibujar_mapa
from .mensaje import componer, resumen_consola, sin_datos
from .modelo import Consenso, Nivel, RespuestaFuente
from .notificaciones import notificar
from .secretos import limpiar


def preparar_salida() -> None:
    """Fuerza UTF-8 en la salida: la consola de Windows usa cp1252 y los
    emojis del mensaje la hacen reventar."""
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def aviso(*partes, error: bool = False) -> None:
    """Imprime tapando cualquier secreto.

    Todo lo que sale por pantalla pasa por aquí: en un repositorio público de
    GitHub, los registros de Actions los lee cualquiera.
    """
    texto = limpiar(" ".join(str(p) for p in partes))
    print(texto, file=sys.stderr if error else sys.stdout)


def construir_argumentos() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vigia",
        description="Vigilancia de oleaje y viento para una moto de agua fondeada.",
    )
    parser.add_argument("--bucle", action="store_true",
                        help="quedarse corriendo, ajustando el intervalo al peligro")
    parser.add_argument("--forzar", action="store_true",
                        help="enviar el parte aunque no haya aviso")
    parser.add_argument("--sin-enviar", action="store_true",
                        help="no enviar nada, solo imprimir")
    parser.add_argument("--probar", action="store_true",
                        help="enviar un mensaje de prueba y salir")
    parser.add_argument("--simular", action="store_true",
                        help="inventar un temporal del oeste para ver el aviso")
    parser.add_argument("--sin-mapa", action="store_true",
                        help="no generar el mapa, solo texto")
    parser.add_argument("--guardar-mapa", metavar="RUTA",
                        help="guardar el mapa en un PNG y salir")
    parser.add_argument("--pronostico", type=int, metavar="DIAS", nargs="?", const=3,
                        help="resumen de varios días con los momentos clave, y salir")
    return parser


def _serie_simulada(cfg: Config, momento) -> list[Consenso]:
    """Temporal de poniente ficticio: entra dentro de 4 horas y va a peor."""
    serie = []
    for i in range(cfg.horas_vista + 1):
        if i < 4:
            altura, racha = 0.3 + i * 0.05, 10 + i
        else:
            altura, racha = 0.6 + (i - 3) * 0.28, 18 + (i - 3) * 3.5
        serie.append(
            Consenso(
                instante=truncar_hora(momento) + timedelta(hours=i),
                altura_ola_m=round(altura, 2),
                altura_ola_min_m=round(altura - 0.1, 2),
                altura_ola_max_m=round(altura + 0.15, 2),
                periodo_ola_s=5.5,
                viento_nudos=round(racha * 0.7, 1),
                racha_nudos=round(racha, 1),
                racha_max_nudos=round(racha, 1),
                direccion_viento_grados=265.0,  # poniente, de lleno en la cala
                fuentes_ola=3,
                fuentes_viento=3,
            )
        )
    return serie


def _merece_stormglass(cfg: Config, estado: Estado, momento) -> tuple[bool, str]:
    """¿Gastamos una de las 9 peticiones diarias de Stormglass en esta pasada?

    Criterio: solo cuando aporta algo. Una segunda opinión de oleaje sirve
    para el parte diario y cuando la cosa ya pinta regular; con la mar plana
    y las fuentes gratis de acuerdo, gastar cuota no tiene sentido.
    """
    if not cfg.stormglass_key:
        return False, "sin clave"

    usados = estado.usos_stormglass_hoy(momento.date())
    if usados >= cfg.stormglass_max_dia:
        return False, f"cuota diaria agotada ({usados}/{cfg.stormglass_max_dia})"

    if parte_pendiente(estado, momento, cfg.horas_parte) is not None:
        return True, "parte diario"

    if Nivel(estado.ultimo_nivel) >= Nivel.AMARILLO:
        return True, f"nivel previo {Nivel(estado.ultimo_nivel).etiqueta}"

    return False, "mar en calma, se reserva la cuota"


def una_pasada(cfg: Config, args, respetar_freno: bool = False) -> tuple[Nivel, int]:
    """Una comprobación completa. Devuelve (nivel, código de salida).

    Con `respetar_freno` (modo cron), la pasada puede salirse sin hacer nada
    si todavía no toca: así el cron se dispara cada 5 min pero el ritmo real
    con la mar en calma es de 15.
    """
    momento = ahora_en(cfg.zona_horaria)
    estado = cargar(cfg.fichero_estado)

    if respetar_freno and not (args.forzar or args.simular):
        seguir, razon = toca_comprobar(estado, momento, cfg)
        if not seguir:
            aviso(f"Sin novedad: {razon}.", error=True)
            return Nivel(estado.ultimo_nivel), 0

    if args.simular:
        aviso("MODO SIMULACIÓN: datos inventados, no es el parte real.", error=True)
        respuestas = [RespuestaFuente(nombre="simulación", error="modo simulación")]
        serie = _serie_simulada(cfg, momento)
    else:
        usar_sg, razon_sg = _merece_stormglass(cfg, estado, momento)
        aviso(f"Stormglass: {'SÍ' if usar_sg else 'no'} ({razon_sg})", error=True)

        respuestas = consultar_todas(cfg, con_cuota=usar_sg)
        for respuesta in respuestas:
            marca = "ok" if (respuesta.ok or respuesta.boletin) else "--"
            detalle = respuesta.error or f"{len(respuesta.lecturas)} lecturas"
            aviso(f"[{marca}] {respuesta.nombre}: {detalle}", error=True)

        if usar_sg:
            reportado = next(
                (r.peticiones_usadas for r in respuestas if r.peticiones_usadas is not None),
                None,
            )
            estado = anotar_stormglass(estado, momento.date(), reportado)

        serie = construir_consenso(respuestas, momento, cfg.horas_vista)

    # Sin datos de ninguna fuente: eso también hay que contarlo.
    if not serie:
        texto = sin_datos(cfg, respuestas)
        aviso(resumen_consola(Nivel.VERDE, texto))
        if not args.sin_enviar and cfg.whatsapp_configurado:
            for resultado in notificar(cfg, texto):
                aviso(f"  [{resultado.canal}] {resultado.detalle}", error=True)
        guardar(cfg.fichero_estado, estado)
        return Nivel.VERDE, 2

    evaluaciones = evaluar_serie(serie, cfg)
    nivel, texto = componer(cfg, momento, serie, evaluaciones, respuestas)
    aviso(resumen_consola(nivel, texto))

    # El mapa se dibuja solo si se va a mandar: son unos segundos de CPU y no
    # tiene sentido gastarlos en las pasadas que acaban en silencio.
    imagen: bytes | None = None
    pie: str | None = None

    decision = decidir(
        estado,
        nivel,
        momento,
        Nivel(cfg.nivel_minimo_aviso),
        cfg.escalada_minutos,
        cfg.escalada_max,
        cfg.horas_parte,
        cfg.calma_minutos,
    )
    if args.forzar or cfg.parte_diario:
        decision.enviar, decision.motivo = True, "envío forzado"

    aviso(
        f"Decisión: {'ENVIAR' if decision.enviar else 'callar'} "
        f"[{decision.tipo}] ({decision.motivo})",
        error=True,
    )

    if decision.enviar and not args.sin_mapa:
        try:
            aviso_oficial = next(
                (r.aviso_oficial for r in respuestas if r.aviso_oficial), None
            )
            imagen = dibujar_mapa(
                cfg, momento, serie, evaluaciones, nivel, aviso_oficial
            )
            _, pie = componer(
                cfg, momento, serie, evaluaciones, respuestas, para_imagen=True
            )
            aviso(f"Mapa generado: {len(imagen) / 1024:.0f} KB", error=True)
        except Exception as exc:  # noqa: BLE001 - un dibujo roto no anula el aviso
            aviso(f"No se pudo dibujar el mapa: {exc!r}", error=True)
            imagen, pie = None, None

    enviado = False
    if decision.enviar and not args.sin_enviar:
        for resultado in notificar(cfg, texto, imagen, pie):
            estado_txt = "OK" if resultado.ok else "FALLO"
            aviso(f"  [{resultado.canal}] {estado_txt}: {resultado.detalle}", error=True)
            enviado = enviado or resultado.ok

    estado = actualizar(
        estado, nivel, momento, decision, enviado, Nivel(cfg.nivel_minimo_aviso)
    )
    estado = anotar_comprobacion(estado, momento)
    guardar(cfg.fichero_estado, estado)

    return nivel, (1 if nivel >= Nivel(cfg.nivel_minimo_aviso) else 0)


def bucle(cfg: Config, args) -> int:
    """Modo residente: mira más a menudo cuanto peor está la mar.

    Es la forma correcta de cumplir "cada 30 min en calma, cada 5 en peligro"
    sin depender de un cron externo, que además saldría carísimo en número de
    ejecuciones.
    """
    aviso(
        f"Vigía en marcha para {cfg.lugar}. "
        f"Intervalos: calma {cfg.intervalo_calma}s · "
        f"amarillo {cfg.intervalo_ojo}s · alerta {cfg.intervalo_alerta}s",
        error=True,
    )
    while True:
        try:
            nivel, _ = una_pasada(cfg, args)
        except KeyboardInterrupt:
            aviso("\nVigía detenido.", error=True)
            return 0
        except Exception as exc:  # noqa: BLE001 - el bucle no puede morirse
            aviso(f"Error inesperado en la pasada: {exc!r}", error=True)
            nivel = Nivel.VERDE

        espera = intervalo_sugerido(nivel, cfg)
        aviso(f"Siguiente comprobación en {espera // 60} min.\n", error=True)
        try:
            time.sleep(espera)
        except KeyboardInterrupt:
            aviso("\nVigía detenido.", error=True)
            return 0


def pronostico(cfg: Config, dias: int) -> int:
    """Resumen de varios dias senalando cuando hay que estar pendiente.

    Va aparte del aviso normal por un motivo importante: el nivel de un aviso
    es el peor de toda la ventana, asi que mirar 72 horas por defecto dejaria
    el semaforo en rojo permanentemente durante un temporal y no serviria de
    nada. Para vigilar se miran 12 horas; para planificar, se piden estas.
    """
    from .evaluacion import es_viento_de_mar
    from .nautica import estado_mar

    cfg.horas_vista = max(24, min(7 * 24, dias * 24))
    momento = ahora_en(cfg.zona_horaria)
    respuestas = consultar_todas(cfg)
    serie = construir_consenso(respuestas, momento, cfg.horas_vista)
    if not serie:
        aviso("Sin datos de ninguna fuente.", error=True)
        return 2
    evaluaciones = evaluar_serie(serie, cfg)

    aviso(f"PRONOSTICO {dias} DIAS - {cfg.lugar}")
    aviso(f"{serie[0].instante:%d/%m %H:%M} -> {serie[-1].instante:%d/%m %H:%M}")
    aviso("")

    oficial = next((r.aviso_oficial for r in respuestas if r.aviso_oficial), None)
    if oficial:
        aviso(f"AVISO AEMET: {oficial}")
        aviso("")

    por_dia: dict = {}
    for punto, evaluacion in zip(serie, evaluaciones):
        por_dia.setdefault(punto.instante.date(), []).append((punto, evaluacion))

    for dia, filas in sorted(por_dia.items()):
        olas = [p.altura_ola_m for p, _ in filas if p.altura_ola_m is not None]
        rachas = [p.racha_nudos for p, _ in filas if p.racha_nudos is not None]
        peor = max(e.nivel for _, e in filas)
        ola_max = max(olas or [0])
        aviso(
            f"{dia:%a %d/%m}  {peor.emoji} {peor.etiqueta:<8} "
            f"ola hasta {ola_max:.2f} m ({estado_mar(ola_max)}) - "
            f"rachas hasta {max(rachas or [0]):.0f} kn"
        )

    aviso("")
    aviso("MOMENTOS PARA ESTAR PENDIENTE")
    anterior = None
    for punto, evaluacion in zip(serie, evaluaciones):
        if anterior is not None and evaluacion.nivel > anterior:
            entra = es_viento_de_mar(punto.direccion_viento_grados, cfg)
            aviso(
                f"  {evaluacion.nivel.emoji} {punto.instante:%a %d/%m %H:%M} "
                f"sube a {evaluacion.nivel.etiqueta}: "
                f"ola {punto.altura_ola_m or 0:.2f} m, "
                f"racha {punto.racha_nudos or 0:.0f} kn del "
                f"{rumbo(punto.direccion_viento_grados)}"
                + (" (entra en la cala)" if entra else "")
            )
        anterior = evaluacion.nivel

    pico = max(serie, key=lambda p: p.altura_ola_m or 0)
    aviso("")
    detalle = ""
    if pico.altura_ola_min_m is not None and pico.altura_ola_max_m is not None:
        detalle = (
            f" (los modelos van de {pico.altura_ola_min_m:.2f} "
            f"a {pico.altura_ola_max_m:.2f})"
        )
    aviso(
        f"PICO: {pico.instante:%a %d/%m %H:%M} "
        f"con {pico.altura_ola_m or 0:.2f} m{detalle}"
    )

    tranquilas = [
        p
        for p in serie
        if (p.altura_ola_m or 9) < cfg.umbrales.ola_amarillo
        and (p.racha_nudos or 99) < cfg.umbrales.racha_amarillo
    ]
    if tranquilas:
        aviso(f"ULTIMO RATO TRANQUILO: hasta {tranquilas[-1].instante:%a %d/%m %H:%M}")
    else:
        aviso("ULTIMO RATO TRANQUILO: ninguno en toda la ventana")
    return 0


def main(argv: list[str] | None = None) -> int:
    preparar_salida()
    args = construir_argumentos().parse_args(argv)
    cfg = Config.desde_entorno()

    if args.probar:
        texto = (
            f"✅ *VIGÍA JETSKI* — mensaje de prueba.\n\n"
            f"Si lees esto, los avisos de {cfg.lugar} llegarán a este chat."
        )
        aviso(texto)
        for resultado in notificar(cfg, texto):
            aviso(f"  [{resultado.canal}] "
                  f"{'OK' if resultado.ok else 'FALLO'}: {resultado.detalle}")
        return 0

    if args.pronostico:
        return pronostico(cfg, args.pronostico)

    if args.guardar_mapa:
        momento = ahora_en(cfg.zona_horaria)
        respuestas = consultar_todas(cfg)
        serie = construir_consenso(respuestas, momento, cfg.horas_vista)
        if not serie:
            aviso("Sin datos: no hay nada que dibujar.", error=True)
            return 2
        evaluaciones = evaluar_serie(serie, cfg)
        nivel, _ = componer(cfg, momento, serie, evaluaciones, respuestas)
        aviso_oficial = next(
            (r.aviso_oficial for r in respuestas if r.aviso_oficial), None
        )
        png = dibujar_mapa(cfg, momento, serie, evaluaciones, nivel, aviso_oficial)
        with open(args.guardar_mapa, "wb") as destino:
            destino.write(png)
        aviso(f"Mapa guardado en {args.guardar_mapa} ({len(png) / 1024:.0f} KB)")
        return 0

    if args.bucle:
        return bucle(cfg, args)

    # Modo cron: el freno decide si esta pasada hace algo o se sale de vacío.
    _, codigo = una_pasada(cfg, args, respetar_freno=True)
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())

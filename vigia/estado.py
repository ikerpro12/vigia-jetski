"""Memoria entre ejecuciones: decide CUÁNDO se manda un mensaje.

Reglas de cadencia:

  * **Peligro nuevo** (se cruza el umbral): se avisa al instante, sin esperar.
  * **Peligro que sigue**: como mucho un mensaje cada `escalada_minutos`
    (5 por defecto) y un tope de `escalada_max` (5) en todo el episodio. Al
    llegar al tope se calla, salvo que la cosa empeore de nivel.
  * **Empeora de nivel dentro del episodio**: se avisa aunque se haya llegado
    al tope, porque pasar de naranja a rojo sí merece interrumpir.
  * **Vuelta a la calma**: un único mensaje de "ya pasó" y se cierra el episodio.
  * **Partes diarios**: a las 8:00, 14:00 y 23:00 llega el parte pase lo que
    pase: en verde y también **con un aviso activo**. No cuentan para el tope
    del episodio ni mueven su reloj. Sin esto, un temporal de tres días eran
    dos avisos la primera noche y después sesenta horas de silencio, que es
    justo cuando más quieres saber cómo va. Si acaba de salir un aviso, el
    parte se da por cubierto y no se repite a los diez minutos.

También lleva la cuenta del gasto diario de Stormglass, que va limitado.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from .modelo import Nivel


@dataclass
class Estado:
    ultimo_nivel: int = 0
    ultimo_aviso_iso: Optional[str] = None

    # Episodio de alerta en curso.
    episodio_inicio_iso: Optional[str] = None
    episodio_mensajes: int = 0
    episodio_nivel_max: int = 0

    # Partes diarios ya enviados hoy, p. ej. {"fecha": "2026-08-10", "horas": [8]}
    partes_fecha: Optional[str] = None
    partes_horas: list[int] = field(default_factory=list)

    # Gasto diario de Stormglass.
    stormglass_fecha: Optional[str] = None
    stormglass_usos: int = 0

    # Cuándo se miró la mar por última vez de verdad (para el freno del cron).
    ultima_comprobacion_iso: Optional[str] = None

    # Desde cuándo el nivel está por debajo del umbral, estando en episodio.
    # Es la memoria de la histéresis: hasta que no pase un rato así, no se
    # da el "ya pasó".
    bajo_umbral_desde_iso: Optional[str] = None

    def _fecha(self, iso: Optional[str]) -> Optional[datetime]:
        if not iso:
            return None
        try:
            return datetime.fromisoformat(iso)
        except ValueError:
            return None

    @property
    def ultimo_aviso(self) -> Optional[datetime]:
        return self._fecha(self.ultimo_aviso_iso)

    @property
    def en_episodio(self) -> bool:
        return self.episodio_inicio_iso is not None

    @property
    def ultima_comprobacion(self) -> Optional[datetime]:
        return self._fecha(self.ultima_comprobacion_iso)

    @property
    def bajo_umbral_desde(self) -> Optional[datetime]:
        return self._fecha(self.bajo_umbral_desde_iso)

    def usos_stormglass_hoy(self, hoy: date) -> int:
        if self.stormglass_fecha != hoy.isoformat():
            return 0
        return self.stormglass_usos

    def partes_de_hoy(self, hoy: date) -> list[int]:
        if self.partes_fecha != hoy.isoformat():
            return []
        return list(self.partes_horas)


def cargar(ruta: Path) -> Estado:
    if not ruta.is_file():
        return Estado()
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Un estado corrupto no debe impedir un aviso.
        return Estado()

    valido = {campo for campo in Estado.__dataclass_fields__}
    return Estado(**{k: v for k, v in datos.items() if k in valido})


def guardar(ruta: Path, estado: Estado) -> None:
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(
            json.dumps(asdict(estado), indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        # En hosting efímero puede no haber disco escribible; no es crítico.
        pass


def parte_pendiente(estado: Estado, ahora: datetime, horas: tuple[int, ...]) -> Optional[int]:
    """¿Toca parte diario ahora y no se ha mandado ya?

    Se admite hasta 59 min de retraso: si el cron se despista (cosa habitual),
    el parte de las 8:00 sigue saliendo a las 8:40.
    """
    enviados = estado.partes_de_hoy(ahora.date())
    for hora in sorted(horas, reverse=True):
        if hora in enviados:
            continue
        # La hora en punto, o hasta una hora tarde si el cron se despistó.
        if 0 <= (ahora.hour - hora) <= 1:
            return hora
    return None


@dataclass
class Decision:
    """Qué hacer en esta pasada y por qué."""

    enviar: bool
    motivo: str
    tipo: str  # "alerta" | "calma" | "parte" | "nada"
    hora_parte: Optional[int] = None
    # Parte que se da por cubierto sin mandarlo: la alerta que acaba de salir
    # ya contaba lo mismo. Se apunta como enviado para que no salte luego.
    omitido: bool = False


def decidir(
    estado: Estado,
    nivel: Nivel,
    ahora: datetime,
    nivel_minimo: Nivel,
    escalada_minutos: int,
    escalada_max: int,
    horas_parte: tuple[int, ...],
    calma_minutos: int = 60,
) -> Decision:
    """Decide si toca mandar mensaje, y de qué tipo."""
    anterior = Nivel(estado.ultimo_nivel)
    ultimo = estado.ultimo_aviso
    minutos_desde = (
        (ahora - ultimo).total_seconds() / 60 if ultimo else float("inf")
    )

    # ---- Situación de peligro -------------------------------------------
    if nivel >= nivel_minimo:
        if not estado.en_episodio:
            return Decision(True, "peligro detectado, aviso inmediato", "alerta")

        # Dentro de un episodio: empeorar siempre interrumpe, aunque se haya
        # llegado al tope. Pasar de naranja a rojo merece molestar.
        if nivel > Nivel(estado.episodio_nivel_max):
            return Decision(True, f"la situación empeora a {nivel.etiqueta}", "alerta")

        if estado.episodio_mensajes >= escalada_max:
            callar = f"tope de {escalada_max} avisos alcanzado en este episodio"
        elif minutos_desde < escalada_minutos:
            callar = (
                f"solo han pasado {minutos_desde:.0f} min de los "
                f"{escalada_minutos} de margen"
            )
        else:
            return Decision(
                True,
                f"sigue el peligro (aviso {estado.episodio_mensajes + 1} "
                f"de {escalada_max})",
                "alerta",
            )

        # Aunque la alerta se calle, el parte diario sale igual. Si no, un
        # temporal de tres días te dejaba dos avisos la primera noche y luego
        # sesenta horas de silencio absoluto, que es justo cuando más quieres
        # saber cómo va la cosa.
        hora = parte_pendiente(estado, ahora, horas_parte)
        if hora is not None:
            # Si acaba de salir una alerta, el parte sería repetir lo mismo a
            # los diez minutos. Se da por cubierto y no se manda.
            if minutos_desde < 60:
                return Decision(
                    False,
                    f"parte de las {hora}:00 cubierto por el aviso de hace "
                    f"{minutos_desde:.0f} min",
                    "parte",
                    hora,
                    omitido=True,
                )
            return Decision(
                True, f"parte diario de las {hora}:00 (con aviso activo)", "parte", hora
            )

        return Decision(False, callar, "nada")

    # ---- Por debajo del umbral, con un episodio abierto ------------------
    # Aquí es donde se corta el baile aviso-calma-aviso-calma. Que el nivel
    # baje un rato NO significa que haya pasado el temporal: puede ser que un
    # modelo haya cambiado de opinión o que el boletín de AEMET se haya
    # actualizado. Se espera a que la cosa aguante tranquila un buen rato.
    if estado.en_episodio:
        desde = estado.bajo_umbral_desde
        if desde is None:
            return Decision(False, "la mar afloja; esperando a ver si se confirma", "nada")
        tranquilo = (ahora - desde).total_seconds() / 60
        if tranquilo >= calma_minutos:
            return Decision(True, f"{tranquilo:.0f} min por debajo del umbral", "calma")
        return Decision(
            False,
            f"solo {tranquilo:.0f} min de calma de los {calma_minutos} "
            "necesarios para dar el aviso por terminado",
            "nada",
        )

    # Episodio que quedó a medias (por ejemplo, tras perder el estado).
    if anterior >= nivel_minimo:
        return Decision(True, "la situación ha vuelto a la normalidad", "calma")

    # ---- Parte diario ----------------------------------------------------
    hora = parte_pendiente(estado, ahora, horas_parte)
    if hora is not None:
        return Decision(True, f"parte diario de las {hora}:00", "parte", hora)

    return Decision(False, "todo en calma, sin novedad", "nada")


def actualizar(
    estado: Estado,
    nivel: Nivel,
    ahora: datetime,
    decision: Decision,
    enviado: bool,
    nivel_minimo: Nivel = Nivel.NARANJA,
) -> Estado:
    """Aplica el resultado de una pasada al estado."""
    tipo = decision.tipo
    estado.ultimo_nivel = int(nivel)

    # Reloj de la histéresis: se pone en marcha al bajar del umbral y se borra
    # en cuanto la mar vuelve a subir, aunque sea un momento.
    if nivel >= nivel_minimo:
        estado.bajo_umbral_desde_iso = None
    elif estado.en_episodio and estado.bajo_umbral_desde_iso is None:
        estado.bajo_umbral_desde_iso = ahora.isoformat()

    if enviado and tipo in ("alerta", "calma"):
        estado.ultimo_aviso_iso = ahora.isoformat()

    if tipo == "alerta" and enviado:
        if not estado.en_episodio:
            estado.episodio_inicio_iso = ahora.isoformat()
            estado.episodio_mensajes = 0
            estado.episodio_nivel_max = 0
        estado.episodio_mensajes += 1
        estado.episodio_nivel_max = max(estado.episodio_nivel_max, int(nivel))

    elif tipo == "calma":
        # Se cierra el episodio: la próxima vez se vuelve a avisar al instante.
        estado.episodio_inicio_iso = None
        estado.episodio_mensajes = 0
        estado.episodio_nivel_max = 0
        estado.bajo_umbral_desde_iso = None

    elif tipo == "parte" and (enviado or decision.omitido):
        hoy = ahora.date().isoformat()
        if estado.partes_fecha != hoy:
            estado.partes_fecha = hoy
            estado.partes_horas = []
        # Se apunta la FRANJA del parte (8, 14, 23), no la hora del reloj: si
        # el parte de las 8:00 sale con retraso a las 9:10, sigue siendo el
        # de las 8 y no debe repetirse.
        franja = decision.hora_parte if decision.hora_parte is not None else ahora.hour
        if franja not in estado.partes_horas:
            estado.partes_horas.append(franja)

    return estado


def anotar_stormglass(estado: Estado, hoy: date, usos: Optional[int] = None) -> Estado:
    """Suma una petición a Stormglass, o fija el valor real que ella reporta."""
    if estado.stormglass_fecha != hoy.isoformat():
        estado.stormglass_fecha = hoy.isoformat()
        estado.stormglass_usos = 0
    if usos is not None:
        # Stormglass devuelve su propio contador: es más fiable que el nuestro.
        estado.stormglass_usos = max(estado.stormglass_usos, usos)
    else:
        estado.stormglass_usos += 1
    return estado


def intervalo_sugerido(nivel: Nivel, cfg) -> int:
    """Cada cuánto conviene volver a mirar, según cómo esté la cosa."""
    if nivel >= Nivel.NARANJA:
        return cfg.intervalo_alerta
    if nivel == Nivel.AMARILLO:
        return cfg.intervalo_ojo
    return cfg.intervalo_calma


def toca_comprobar(estado: Estado, ahora: datetime, cfg) -> tuple[bool, str]:
    """Freno para el cron: ¿esta pasada hace algo o se sale de vacío?

    El cron de GitHub tiene que dispararse cada 5 minutos, porque si no jamás
    podría avisarte cada 5 durante un temporal. Pero con la mar en calma no
    hace falta consultar nada tan a menudo, así que la mayoría de esas pasadas
    salen sin hacer nada y el ritmo real es de 15 minutos.

    Cuando el último nivel conocido ya era preocupante, se comprueba en cada
    pasada: ahí sí queremos los 5 minutos.
    """
    if parte_pendiente(estado, ahora, cfg.horas_parte) is not None:
        return True, "toca parte diario"

    ultima = estado.ultima_comprobacion
    if ultima is None:
        return True, "primera comprobación"

    intervalo = intervalo_sugerido(Nivel(estado.ultimo_nivel), cfg)
    transcurrido = (ahora - ultima).total_seconds()

    # Margen de 60 s: el cron nunca cae en el segundo exacto y sin holgura se
    # perdería una pasada de cada dos.
    if transcurrido >= intervalo - 60:
        return True, f"han pasado {transcurrido / 60:.0f} min"

    return (
        False,
        f"solo {transcurrido / 60:.0f} min de los {intervalo // 60} previstos "
        f"(nivel {Nivel(estado.ultimo_nivel).etiqueta})",
    )


def anotar_comprobacion(estado: Estado, ahora: datetime) -> Estado:
    estado.ultima_comprobacion_iso = ahora.isoformat()
    return estado

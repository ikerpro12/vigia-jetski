"""Configuración: todo por variables de entorno, sin dependencias externas.

Si existe un fichero `.env` junto al proyecto se carga automáticamente, para
que en local no haga falta exportar nada a mano.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

RAIZ = Path(__file__).resolve().parent.parent


def cargar_dotenv(ruta: Path | None = None) -> None:
    """Carga un .env sencillo (CLAVE=valor) sin pisar el entorno real."""
    ruta = ruta or (RAIZ / ".env")
    if not ruta.is_file():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        clave = clave.strip()
        valor = valor.strip().strip('"').strip("'")
        # Las variables ya presentes en el entorno mandan sobre el .env.
        os.environ.setdefault(clave, valor)


def _flotante(clave: str, por_defecto: float) -> float:
    try:
        return float(os.environ[clave])
    except (KeyError, ValueError):
        return por_defecto


def _entero(clave: str, por_defecto: int) -> int:
    try:
        return int(os.environ[clave])
    except (KeyError, ValueError):
        return por_defecto


def _horas(clave: str, por_defecto: tuple[int, ...]) -> tuple[int, ...]:
    """Lee algo como "8,14,23" y lo valida como horas del día."""
    valor = os.environ.get(clave)
    if not valor:
        return por_defecto
    horas = []
    for trozo in valor.split(","):
        try:
            hora = int(trozo.strip())
        except ValueError:
            continue
        if 0 <= hora <= 23:
            horas.append(hora)
    return tuple(sorted(set(horas))) or por_defecto


def _booleano(clave: str, por_defecto: bool) -> bool:
    valor = os.environ.get(clave)
    if valor is None:
        return por_defecto
    return valor.strip().lower() in {"1", "true", "si", "sí", "yes", "on"}


@dataclass
class Umbrales:
    """Alturas de ola (m) y rachas (nudos) que disparan cada nivel.

    Los valores por defecto están pensados para una moto de agua fondeada o en
    boya, sin nadie a bordo. Una ola de 1 m con periodo corto ya la castiga.
    """

    ola_amarillo: float = 0.5
    ola_naranja: float = 0.9
    ola_rojo: float = 1.5

    racha_amarillo: float = 18.0
    racha_naranja: float = 25.0
    racha_rojo: float = 35.0

    @classmethod
    def desde_entorno(cls) -> "Umbrales":
        return cls(
            ola_amarillo=_flotante("OLA_AMARILLO", 0.5),
            ola_naranja=_flotante("OLA_NARANJA", 0.9),
            ola_rojo=_flotante("OLA_ROJO", 1.5),
            racha_amarillo=_flotante("RACHA_AMARILLO", 18.0),
            racha_naranja=_flotante("RACHA_NARANJA", 25.0),
            racha_rojo=_flotante("RACHA_ROJO", 35.0),
        )


@dataclass
class Config:
    # --- Ubicación --------------------------------------------------------
    # Cala Tarida, costa oeste de Ibiza.
    latitud: float = 38.9469
    longitud: float = 1.2264
    lugar: str = "Cala Tarida (Ibiza)"
    zona_horaria: str = "Europe/Madrid"

    # La cala mira al oeste: el viento de este sector entra de lleno.
    # Sector de "viento de mar" (onshore) en grados, de dónde VIENE el viento.
    sector_mar_desde: float = 202.5  # SSO
    sector_mar_hasta: float = 337.5  # NNO

    # --- Vigilancia -------------------------------------------------------
    horas_vista: int = 12          # cuántas horas por delante miramos
    nivel_minimo_aviso: int = 2    # a partir de NARANJA se manda WhatsApp

    # --- Fuentes opcionales (con clave) -----------------------------------
    stormglass_key: Optional[str] = None
    aemet_key: Optional[str] = None
    contacto: str = "vigia-jetski (contacto: cambia-esto@ejemplo.com)"

    # --- Notificaciones ---------------------------------------------------
    green_api_instancia: Optional[str] = None
    green_api_token: Optional[str] = None
    green_api_chat: Optional[str] = None      # p.ej. 34600111222-1581234048@g.us
    green_api_url: str = "https://api.green-api.com"

    callmebot_telefono: Optional[str] = None  # respaldo, solo chats personales
    callmebot_key: Optional[str] = None

    # --- Partes diarios ---------------------------------------------------
    # Horas (locales españolas) a las que llega el parte pase lo que pase.
    horas_parte: tuple[int, ...] = (8, 14, 23)

    # --- Cadencia de avisos -----------------------------------------------
    # Cuando hay peligro: primer aviso instantáneo y luego, como mucho, uno
    # cada `escalada_minutos`, con un tope de `escalada_max` en todo el
    # episodio. Así te enteras rápido sin que el móvil eche humo.
    escalada_minutos: int = 5
    escalada_max: int = 5

    # --- Cada cuánto se mira la mar (segundos) ----------------------------
    # Valen tanto para el modo bucle como para el freno del cron.
    intervalo_calma: int = 900     # 15 min con la mar tranquila
    intervalo_ojo: int = 600       # 10 min en amarillo, la cosa se está armando
    intervalo_alerta: int = 300    # 5 min en naranja o rojo

    # --- Presupuesto de Stormglass ----------------------------------------
    # El plan gratuito da 10 peticiones al día; nos quedamos en 9 por si acaso.
    stormglass_max_dia: int = 9

    # --- Comportamiento ---------------------------------------------------
    parte_diario: bool = False     # forzar envío aunque esté todo en verde
    silenciar_horas: int = 6       # no repetir el mismo aviso antes de N horas
    tiempo_espera: int = 20        # timeout HTTP por fuente, en segundos
    fichero_estado: Path = field(default_factory=lambda: RAIZ / "estado.json")

    umbrales: Umbrales = field(default_factory=Umbrales)

    @classmethod
    def desde_entorno(cls) -> "Config":
        cargar_dotenv()
        estado = os.environ.get("FICHERO_ESTADO")
        return cls(
            latitud=_flotante("LATITUD", 38.9469),
            longitud=_flotante("LONGITUD", 1.2264),
            lugar=os.environ.get("LUGAR", "Cala Tarida (Ibiza)"),
            zona_horaria=os.environ.get("ZONA_HORARIA", "Europe/Madrid"),
            sector_mar_desde=_flotante("SECTOR_MAR_DESDE", 202.5),
            sector_mar_hasta=_flotante("SECTOR_MAR_HASTA", 337.5),
            horas_vista=_entero("HORAS_VISTA", 12),
            nivel_minimo_aviso=_entero("NIVEL_MINIMO_AVISO", 2),
            stormglass_key=os.environ.get("STORMGLASS_KEY") or None,
            aemet_key=os.environ.get("AEMET_KEY") or None,
            contacto=os.environ.get(
                "CONTACTO", "vigia-jetski (contacto: cambia-esto@ejemplo.com)"
            ),
            green_api_instancia=os.environ.get("GREEN_API_INSTANCIA") or None,
            green_api_token=os.environ.get("GREEN_API_TOKEN") or None,
            green_api_chat=os.environ.get("GREEN_API_CHAT") or None,
            green_api_url=os.environ.get(
                "GREEN_API_URL", "https://api.green-api.com"
            ).rstrip("/"),
            callmebot_telefono=os.environ.get("CALLMEBOT_TELEFONO") or None,
            callmebot_key=os.environ.get("CALLMEBOT_KEY") or None,
            horas_parte=_horas("HORAS_PARTE", (8, 14, 23)),
            escalada_minutos=_entero("ESCALADA_MINUTOS", 5),
            escalada_max=_entero("ESCALADA_MAX", 5),
            intervalo_calma=_entero("INTERVALO_CALMA", 900),
            intervalo_ojo=_entero("INTERVALO_OJO", 600),
            intervalo_alerta=_entero("INTERVALO_ALERTA", 300),
            stormglass_max_dia=_entero("STORMGLASS_MAX_DIA", 9),
            parte_diario=_booleano("PARTE_DIARIO", False),
            silenciar_horas=_entero("SILENCIAR_HORAS", 6),
            tiempo_espera=_entero("TIEMPO_ESPERA", 20),
            fichero_estado=Path(estado) if estado else RAIZ / "estado.json",
            umbrales=Umbrales.desde_entorno(),
        )

    @property
    def whatsapp_configurado(self) -> bool:
        return bool(
            (self.green_api_instancia and self.green_api_token and self.green_api_chat)
            or (self.callmebot_telefono and self.callmebot_key)
        )

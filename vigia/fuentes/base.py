"""Utilidades comunes a todas las fuentes: HTTP y parseo de fechas."""

from __future__ import annotations

import gzip
import http.client
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Optional
from zoneinfo import ZoneInfo


class ErrorFuente(Exception):
    """Fallo recuperable de una fuente. Nunca debe tumbar el programa."""


@lru_cache(maxsize=1)
def contexto_ssl() -> ssl.SSLContext:
    """Contexto TLS con un almacén de certificados lo más completo posible.

    En Windows, Python arranca con muy pocas CA cargadas y algunos servidores
    (api.met.no, por ejemplo) fallan la verificación aunque el navegador o curl
    los acepten. Aquí se completa el almacén con el del sistema, y con certifi
    si está instalado. En Linux (Docker, GitHub Actions) no hace falta nada.
    """
    contexto = ssl.create_default_context()

    try:
        import certifi  # opcional: no es una dependencia obligatoria

        contexto.load_verify_locations(certifi.where())
    except Exception:  # noqa: BLE001 - si no está, seguimos con lo que haya
        pass

    if sys.platform == "win32":
        for almacen in ("ROOT", "CA"):
            try:
                certificados = ssl.enum_certificates(almacen)
            except Exception:  # noqa: BLE001
                continue
            for cert, codificacion, confianza in certificados:
                # Solo certificados DER en los que el sistema confía.
                if codificacion != "x509_asn" or confianza is False:
                    continue
                try:
                    contexto.load_verify_locations(cadata=cert)
                except ssl.SSLError:
                    continue

    return contexto


def _detalle_error(exc: urllib.error.HTTPError) -> str:
    """El cuerpo de un error suele venir comprimido; sin descomprimir es ruido."""
    try:
        cuerpo = exc.read()
        if exc.headers.get("Content-Encoding") == "gzip":
            cuerpo = gzip.decompress(cuerpo)
        texto = cuerpo.decode("utf-8", "replace").strip()
    except Exception:  # noqa: BLE001 - el detalle es un extra, no crítico
        return ""
    # Aplanar a una línea: esto acaba en un mensaje de WhatsApp.
    return " ".join(texto.split())[:160]


def pedir_json(
    url: str,
    *,
    cabeceras: Optional[dict[str, str]] = None,
    tiempo_espera: int = 20,
    datos: Optional[bytes] = None,
    intentos: int = 3,
    espera_reintento: float = 2.0,
) -> Any:
    """GET/POST que devuelve JSON, o lanza ErrorFuente con algo legible.

    Reintenta ante fallos pasajeros (429, 5xx, conexiones cortadas), que son
    justo los que AEMET y Open-Meteo devuelven de vez en cuando.
    """
    cabeceras = dict(cabeceras or {})
    cabeceras.setdefault("Accept", "application/json")
    cabeceras.setdefault("Accept-Encoding", "gzip")

    peticion = urllib.request.Request(url, headers=cabeceras, data=datos)
    if datos is not None:
        peticion.add_header("Content-Type", "application/json")

    ultimo_fallo = "desconocido"
    for intento in range(intentos):
        try:
            with urllib.request.urlopen(
                peticion, timeout=tiempo_espera, context=contexto_ssl()
            ) as respuesta:
                crudo = respuesta.read()
                if respuesta.headers.get("Content-Encoding") == "gzip":
                    crudo = gzip.decompress(crudo)
                return json.loads(crudo.decode("utf-8"))

        except urllib.error.HTTPError as exc:
            ultimo_fallo = f"HTTP {exc.code} {exc.reason} {_detalle_error(exc)}".strip()
            # 429 y 5xx suelen ser pasajeros; el resto no mejora reintentando.
            if exc.code != 429 and exc.code < 500:
                raise ErrorFuente(ultimo_fallo) from exc

        except urllib.error.URLError as exc:
            ultimo_fallo = f"red: {exc.reason}"

        except (ConnectionError, http.client.HTTPException) as exc:
            # RemoteDisconnected y similares: el servidor cortó a media faena.
            ultimo_fallo = f"conexión cortada: {type(exc).__name__}"

        except TimeoutError:
            ultimo_fallo = "tiempo de espera agotado"

        except json.JSONDecodeError as exc:
            raise ErrorFuente(f"respuesta no es JSON válido: {exc}") from exc

        if intento < intentos - 1:
            time.sleep(espera_reintento * (intento + 1))

    raise ErrorFuente(f"{ultimo_fallo} (tras {intentos} intentos)")


def hora_local(texto: str, zona: str) -> datetime:
    """Convierte una marca de tiempo ISO-8601 a hora local con tz."""
    limpio = texto.replace("Z", "+00:00")
    momento = datetime.fromisoformat(limpio)
    if momento.tzinfo is None:
        # Open-Meteo devuelve horas ya locales pero sin offset.
        return momento.replace(tzinfo=ZoneInfo(zona))
    return momento.astimezone(ZoneInfo(zona))


def ahora(zona: str) -> datetime:
    return datetime.now(timezone.utc).astimezone(ZoneInfo(zona))


def ms_a_nudos(metros_por_segundo: float) -> float:
    return metros_por_segundo * 1.943844


def truncar_hora(momento: datetime) -> datetime:
    return momento.replace(minute=0, second=0, microsecond=0)


def dias_prevision(horas_vista: int) -> int:
    """Días que hay que pedir a la API para cubrir la ventana de vigilancia.

    Estaba fijo en 2, lo que bastaba para las 12 horas de siempre pero se
    quedaba corto al pedir un pronóstico de varios días. Se suma un día de
    margen porque la ventana empieza a media jornada.
    """
    return max(2, min(10, -(-horas_vista // 24) + 1))

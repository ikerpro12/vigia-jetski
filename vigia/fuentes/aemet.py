"""AEMET OpenData: el boletín marítimo oficial español.

Es la fuente con más autoridad de todas, y la única que capta cosas que los
modelos de oleaje no ven: tormentas, aguaceros y avisos declarados por un
meteorólogo. El 10/08/2026, con los modelos dando 0,3 m de ola y todo en
calma, AEMET tenía un aviso activo de tormenta fuerte en aguas de Ibiza.
Por eso un aviso oficial puede subir el nivel por su cuenta.

AEMET responde en dos pasos: la primera llamada devuelve un JSON con una URL
`datos`, y esa segunda URL trae el boletín de verdad (en ISO-8859-15).

Zonas costeras (parámetro `costa`), comprobadas contra la API:
    40 Galicia · 41 Asturias/Cantabria/País Vasco · 42 Andalucía Occidental
    43 Canarias · 44 ILLES BALEARS · 45 Cataluña · 46 Valencia y Murcia
    47 Andalucía Oriental y Melilla

Clave gratuita en https://opendata.aemet.es/centrodedescargas/altaUsuario
"""

from __future__ import annotations

import gzip
import http.client
import json
import os
import time
import urllib.error
import urllib.request

from ..config import Config
from ..modelo import RespuestaFuente
from .base import ErrorFuente, contexto_ssl, pedir_json

BASE = "https://opendata.aemet.es/opendata/api"

# 44 = Illes Balears. Verificado consultando la API: el 41 que parecía lógico
# es en realidad Asturias, Cantabria y País Vasco.
COSTA_BALEARES = "44"

SIN_AVISOS = "no hay avisos"


def _descargar_texto(url: str, tiempo_espera: int, intentos: int = 3) -> str:
    """La URL `datos` no siempre viene en UTF-8; AEMET usa ISO-8859-15.

    AEMET corta conexiones y devuelve 429 con cierta alegría, así que se
    reintenta antes de darla por perdida.
    """
    peticion = urllib.request.Request(
        url, headers={"Accept": "application/json", "Accept-Encoding": "gzip"}
    )
    crudo = b""
    ultimo = "desconocido"
    for intento in range(intentos):
        try:
            with urllib.request.urlopen(
                peticion, timeout=tiempo_espera, context=contexto_ssl()
            ) as respuesta:
                crudo = respuesta.read()
                if respuesta.headers.get("Content-Encoding") == "gzip":
                    crudo = gzip.decompress(crudo)
            break
        except urllib.error.HTTPError as exc:
            ultimo = f"HTTP {exc.code}"
            if exc.code != 429 and exc.code < 500:
                raise ErrorFuente(f"{ultimo} al descargar el boletín") from exc
        except (urllib.error.URLError, ConnectionError, http.client.HTTPException) as exc:
            ultimo = f"conexión: {type(exc).__name__}"
        if intento < intentos - 1:
            time.sleep(2.0 * (intento + 1))
    else:
        raise ErrorFuente(f"{ultimo} tras {intentos} intentos")

    for codificacion in ("utf-8", "iso-8859-15", "latin-1"):
        try:
            return crudo.decode(codificacion)
        except UnicodeDecodeError:
            continue
    return crudo.decode("utf-8", "replace")


def _texto_de_zona(boletin: dict, zona_interes: str) -> str | None:
    """Saca la predicción de la zona que nos toca (p. ej. 'Aguas costeras de Ibiza')."""
    prediccion = boletin.get("prediccion") or {}
    zonas = prediccion.get("zona") or []
    if isinstance(zonas, dict):
        zonas = [zonas]

    for zona in zonas:
        if zona_interes.lower() not in (zona.get("nombre") or "").lower():
            continue
        subzonas = zona.get("subzona") or []
        if isinstance(subzonas, dict):
            subzonas = [subzonas]
        textos = [s.get("texto", "").strip() for s in subzonas if s.get("texto")]
        if textos:
            return " ".join(textos)
        return None
    return None


def boletin_aemet(cfg: Config) -> RespuestaFuente:
    nombre = "AEMET (boletín oficial)"
    if not cfg.aemet_key:
        return RespuestaFuente(nombre=nombre, error="sin clave configurada")

    costa = os.environ.get("AEMET_COSTA", COSTA_BALEARES)
    zona_interes = os.environ.get("ZONA_AEMET", "Ibiza")

    try:
        sobre = pedir_json(
            f"{BASE}/prediccion/maritima/costera/costa/{costa}",
            cabeceras={"api_key": cfg.aemet_key},
            tiempo_espera=cfg.tiempo_espera,
        )
    except ErrorFuente as exc:
        return RespuestaFuente(nombre=nombre, error=str(exc))

    if not isinstance(sobre, dict) or sobre.get("estado") != 200 or not sobre.get("datos"):
        descripcion = sobre.get("descripcion", "") if isinstance(sobre, dict) else ""
        return RespuestaFuente(
            nombre=nombre, error=f"sin datos {descripcion}".strip()
        )

    try:
        crudo = _descargar_texto(sobre["datos"], cfg.tiempo_espera)
        documento = json.loads(crudo)
    except ErrorFuente as exc:
        return RespuestaFuente(nombre=nombre, error=str(exc))
    except json.JSONDecodeError as exc:
        return RespuestaFuente(nombre=nombre, error=f"boletín ilegible: {exc}")

    if isinstance(documento, list):
        if not documento:
            return RespuestaFuente(nombre=nombre, error="boletín vacío")
        documento = documento[0]

    partes: list[str] = []

    # Predicción concreta de nuestra zona: lo más útil del boletín.
    texto_zona = _texto_de_zona(documento, zona_interes)
    if texto_zona:
        partes.append(f"Aguas de {zona_interes}: {texto_zona}")

    # Aviso oficial declarado por AEMET.
    aviso = (documento.get("aviso") or {}).get("texto", "").strip()
    hay_aviso = bool(aviso) and SIN_AVISOS not in aviso.lower()
    if hay_aviso:
        partes.append(f"Aviso AEMET: {aviso}")

    situacion = (documento.get("situacion") or {}).get("texto", "").strip()
    if situacion:
        partes.append(f"Situación: {situacion}")

    if not partes:
        return RespuestaFuente(nombre=nombre, error="boletín sin contenido útil")

    boletin = " ".join(" ".join(partes).split())
    if len(boletin) > 700:
        boletin = boletin[:700].rsplit(" ", 1)[0] + "…"

    # Solo se escala el nivel si el aviso menciona nuestra zona. Un aviso por
    # temporal en Menorca no debe hacer bajar a nadie a Cala Corral.
    aviso_relevante = None
    if hay_aviso and zona_interes.lower() in aviso.lower():
        aviso_relevante = aviso

    return RespuestaFuente(
        nombre=nombre, boletin=boletin, aviso_oficial=aviso_relevante
    )

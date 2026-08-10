"""Tapado de secretos en todo lo que se imprime.

Esto importa de verdad si alojas el proyecto en un repositorio **público** de
GitHub: los registros de Actions los puede leer cualquiera. Y hay al menos un
sitio donde un token se cuela solo: Green API mete el token en la RUTA de la
URL, así que un error suyo devuelve un cuerpo tal que

    {"statusCode":400, "path":"/waInstance<ID>/sendMessage/<TOKEN>", ...}

Si eso se imprime tal cual, el token queda publicado. Aquí se sustituye por
un marcador antes de que llegue a la salida.
"""

from __future__ import annotations

import os
import re
from typing import Iterable

# Variables de entorno cuyo valor no debe aparecer nunca en la salida.
CLAVES_SENSIBLES = (
    "GREEN_API_TOKEN",
    "GREEN_API_INSTANCIA",
    "GREEN_API_CHAT",
    "AEMET_KEY",
    "STORMGLASS_KEY",
    "CALLMEBOT_KEY",
    "CALLMEBOT_TELEFONO",
)

MARCADOR = "«oculto»"

# Patrones de seguridad, por si un token llega por una vía que no habíamos
# previsto (por ejemplo, el de una instancia que no es la configurada).
PATRONES = (
    # Ruta de Green API: /waInstance<id>/<metodo>/<token>
    re.compile(r"(waInstance)\d+(/\w+/)[A-Za-z0-9]{20,}"),
    # JWT de AEMET.
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
)


def _valores_secretos() -> list[str]:
    valores = []
    for clave in CLAVES_SENSIBLES:
        valor = os.environ.get(clave, "").strip()
        # Los valores muy cortos darían falsos positivos por todas partes.
        if len(valor) >= 6:
            valores.append(valor)
    # Primero los largos: si un secreto contiene a otro, se tapa el grande.
    return sorted(valores, key=len, reverse=True)


def limpiar(texto: str, extra: Iterable[str] = ()) -> str:
    """Devuelve el texto con cualquier secreto conocido sustituido."""
    if not texto:
        return texto

    for valor in list(_valores_secretos()) + [v for v in extra if v]:
        if valor and valor in texto:
            texto = texto.replace(valor, MARCADOR)

    for patron in PATRONES:
        if patron.groups:
            texto = patron.sub(rf"\g<1>{MARCADOR}\g<2>{MARCADOR}", texto)
        else:
            texto = patron.sub(MARCADOR, texto)

    return texto

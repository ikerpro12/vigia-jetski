"""Envío de avisos por WhatsApp.

Sobre grupos de WhatsApp, que es lo que complica esto:

* La API oficial de Meta (Cloud API) solo permite grupos si tienes una Official
  Business Account verificada. Para un particular con una moto de agua, es un
  trámite desproporcionado.
* CallMeBot es gratis y va en dos minutos, pero SOLO envía a chats personales,
  no a grupos.
* GREEN API sí envía a grupos y tiene un plan gratuito (unos 3 chats), que es
  justo lo que hace falta aquí. Funciona vinculando tu WhatsApp por QR, igual
  que WhatsApp Web.

Por eso el canal principal es Green API y CallMeBot queda como respaldo.
Si no hay nada configurado, el aviso sale por consola y ya está.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass

from .config import Config
from .fuentes.base import ErrorFuente, contexto_ssl, pedir_json


@dataclass
class Resultado:
    canal: str
    ok: bool
    detalle: str


def _multipart(campos: dict[str, str], fichero: tuple[str, bytes, str]) -> tuple[bytes, str]:
    """Monta un cuerpo multipart/form-data a mano.

    urllib no lo trae hecho y no vamos a añadir `requests` por esto.
    `fichero` es (nombre_campo, contenido, nombre_archivo).
    """
    frontera = "----VigiaJetski" + uuid.uuid4().hex
    cuerpo = bytearray()

    for clave, valor in campos.items():
        cuerpo += f"--{frontera}\r\n".encode()
        cuerpo += f'Content-Disposition: form-data; name="{clave}"\r\n\r\n'.encode()
        cuerpo += valor.encode("utf-8") + b"\r\n"

    campo, contenido, nombre = fichero
    cuerpo += f"--{frontera}\r\n".encode()
    cuerpo += (
        f'Content-Disposition: form-data; name="{campo}"; filename="{nombre}"\r\n'
    ).encode()
    cuerpo += b"Content-Type: image/png\r\n\r\n"
    cuerpo += contenido + b"\r\n"
    cuerpo += f"--{frontera}--\r\n".encode()

    return bytes(cuerpo), f"multipart/form-data; boundary={frontera}"


def _enviar_imagen_green_api(cfg: Config, imagen: bytes, pie: str) -> Resultado:
    """Manda el mapa como imagen, con el parte de pie de foto."""
    url = (
        f"{cfg.green_api_url}/waInstance{cfg.green_api_instancia}"
        f"/sendFileByUpload/{cfg.green_api_token}"
    )
    # WhatsApp corta los pies de foto a 1024 caracteres.
    cuerpo, tipo = _multipart(
        {
            "chatId": cfg.green_api_chat or "",
            "caption": pie[:1024],
            "fileName": "vigia-cala-tarida.png",
        },
        ("file", imagen, "vigia-cala-tarida.png"),
    )

    peticion = urllib.request.Request(url, data=cuerpo, method="POST")
    peticion.add_header("Content-Type", tipo)
    try:
        with urllib.request.urlopen(
            peticion, timeout=max(cfg.tiempo_espera, 45), context=contexto_ssl()
        ) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detalle = ""
        try:
            detalle = exc.read().decode("utf-8", "replace")[:160]
        except Exception:  # noqa: BLE001
            pass
        return Resultado("Green API (mapa)", False, f"HTTP {exc.code} {detalle}")
    except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
        return Resultado("Green API (mapa)", False, f"red: {exc}")
    except json.JSONDecodeError as exc:
        return Resultado("Green API (mapa)", False, f"respuesta ilegible: {exc}")

    if isinstance(datos, dict) and datos.get("idMessage"):
        return Resultado("Green API (mapa)", True, f"enviado ({datos['idMessage']})")
    return Resultado("Green API (mapa)", False, f"respuesta inesperada: {datos}")


def _enviar_green_api(cfg: Config, texto: str) -> Resultado:
    url = (
        f"{cfg.green_api_url}/waInstance{cfg.green_api_instancia}"
        f"/sendMessage/{cfg.green_api_token}"
    )
    cuerpo = json.dumps(
        {"chatId": cfg.green_api_chat, "message": texto}, ensure_ascii=False
    ).encode("utf-8")

    try:
        respuesta = pedir_json(url, datos=cuerpo, tiempo_espera=cfg.tiempo_espera)
    except ErrorFuente as exc:
        return Resultado("Green API", False, str(exc))

    if isinstance(respuesta, dict) and respuesta.get("idMessage"):
        return Resultado("Green API", True, f"enviado ({respuesta['idMessage']})")
    return Resultado("Green API", False, f"respuesta inesperada: {respuesta}")


def _enviar_callmebot(cfg: Config, texto: str) -> Resultado:
    # CallMeBot tiene un límite de longitud generoso pero no infinito.
    recorte = texto if len(texto) <= 900 else texto[:890] + "…"
    parametros = urllib.parse.urlencode(
        {
            "phone": cfg.callmebot_telefono,
            "text": recorte,
            "apikey": cfg.callmebot_key,
        }
    )
    url = f"https://api.callmebot.com/whatsapp.php?{parametros}"

    # Este endpoint devuelve HTML, no JSON, así que se lee en crudo.
    import urllib.error
    import urllib.request

    try:
        peticion = urllib.request.Request(url, headers={"User-Agent": cfg.contacto})
        with urllib.request.urlopen(
            peticion, timeout=cfg.tiempo_espera, context=contexto_ssl()
        ) as resp:
            cuerpo = resp.read().decode("utf-8", "replace")
        if resp.status == 200:
            return Resultado("CallMeBot", True, "enviado")
        return Resultado("CallMeBot", False, f"HTTP {resp.status}: {cuerpo[:120]}")
    except urllib.error.HTTPError as exc:
        return Resultado("CallMeBot", False, f"HTTP {exc.code}")
    except urllib.error.URLError as exc:
        return Resultado("CallMeBot", False, f"red: {exc.reason}")


def notificar(
    cfg: Config,
    texto: str,
    imagen: bytes | None = None,
    pie: str | None = None,
) -> list[Resultado]:
    """Intenta todos los canales configurados. Devuelve qué pasó en cada uno.

    Si hay imagen, se manda **un solo mensaje**: el mapa con el parte de pie de
    foto. Nada de mandar foto y texto por separado, que serían dos avisos por
    cada uno de verdad. Si la imagen falla, se cae al mensaje de texto.
    """
    resultados: list[Resultado] = []
    hay_green = bool(
        cfg.green_api_instancia and cfg.green_api_token and cfg.green_api_chat
    )

    if hay_green and imagen:
        resultado = _enviar_imagen_green_api(cfg, imagen, pie or texto)
        resultados.append(resultado)
        if resultado.ok:
            return resultados
        # Si el mapa no sale, al menos que llegue el texto.

    if hay_green:
        resultados.append(_enviar_green_api(cfg, texto))

    # Solo se usa el respaldo si el principal no existe o ha fallado.
    ya_enviado = any(r.ok for r in resultados)
    if not ya_enviado and cfg.callmebot_telefono and cfg.callmebot_key:
        resultados.append(_enviar_callmebot(cfg, texto))

    if not resultados:
        resultados.append(
            Resultado("consola", True, "sin WhatsApp configurado, solo salida por pantalla")
        )
    return resultados

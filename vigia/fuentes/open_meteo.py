"""Open-Meteo: olas y viento, sin clave, pidiendo VARIOS MODELOS a la vez.

Aquí está el mayor golpe de redundancia del proyecto. En vez de pedir "la"
previsión de oleaje, se piden cinco modelos numéricos distintos (ECMWF WAM,
Météo-France, NCEP GFS-Wave, DWD GWAM y EWAM) y cada uno entra como un voto
independiente en la mediana.

No es un lujo teórico: el 10/08/2026 a la misma hora y en el mismo punto los
modelos daban 0,24 · 0,58 · 0,00 · 0,80 · 0,34 m. Con una sola fuente te
habría tocado creerte cualquiera de esos números.
"""

from __future__ import annotations

from urllib.parse import urlencode

from ..config import Config
from ..modelo import Lectura, RespuestaFuente
from .base import ErrorFuente, dias_prevision, hora_local, pedir_json

MARINE = "https://marine-api.open-meteo.com/v1/marine"
FORECAST = "https://api.open-meteo.com/v1/forecast"

MODELOS_OLA = ("ecmwf_wam025", "meteofrance_wave", "ncep_gfswave025", "gwam", "ewam")
MODELOS_VIENTO = (
    "ecmwf_ifs025",
    "gfs_seamless",
    "icon_seamless",
    "meteofrance_seamless",
    "ukmo_seamless",
)


def _series_por_modelo(bloque: dict, variable: str, modelos: tuple[str, ...]) -> dict:
    """Open-Meteo nombra las series `variable_modelo` al pedir varios modelos.

    Devuelve {modelo: serie}, saltándose los modelos sin datos útiles.
    """
    encontradas = {}
    for modelo in modelos:
        serie = bloque.get(f"{variable}_{modelo}")
        if not serie:
            continue
        # Un modelo cuya serie entera es 0 o None no está prediciendo: casi
        # siempre significa que su malla coloca este punto en tierra.
        utiles = [v for v in serie if v is not None]
        if not utiles or all(v == 0 for v in utiles):
            continue
        encontradas[modelo] = serie
    return encontradas


def olas_open_meteo(cfg: Config) -> RespuestaFuente:
    nombre = "Open-Meteo olas"
    parametros = {
        "latitude": cfg.latitud,
        "longitude": cfg.longitud,
        "hourly": "wave_height,wave_period,wave_direction",
        "models": ",".join(MODELOS_OLA),
        "timezone": cfg.zona_horaria,
        "forecast_days": dias_prevision(cfg.horas_vista),
    }
    try:
        datos = pedir_json(
            f"{MARINE}?{urlencode(parametros)}", tiempo_espera=cfg.tiempo_espera
        )
    except ErrorFuente as exc:
        return RespuestaFuente(nombre=nombre, error=str(exc))

    bloque = datos.get("hourly") or {}
    tiempos = bloque.get("time") or []
    if not tiempos:
        return RespuestaFuente(nombre=nombre, error="sin datos horarios")

    alturas = _series_por_modelo(bloque, "wave_height", MODELOS_OLA)
    periodos = _series_por_modelo(bloque, "wave_period", MODELOS_OLA)
    direcciones = _series_por_modelo(bloque, "wave_direction", MODELOS_OLA)
    if not alturas:
        return RespuestaFuente(nombre=nombre, error="ningún modelo con datos")

    # Una lectura por modelo y hora: el consenso las junta y saca la mediana.
    lecturas: list[Lectura] = []
    for indice, marca in enumerate(tiempos):
        instante = hora_local(marca, cfg.zona_horaria)
        for modelo, serie in alturas.items():
            if indice >= len(serie) or serie[indice] is None:
                continue
            periodo = periodos.get(modelo, [])
            direccion = direcciones.get(modelo, [])
            lecturas.append(
                Lectura(
                    instante=instante,
                    altura_ola_m=serie[indice],
                    periodo_ola_s=periodo[indice] if indice < len(periodo) else None,
                    direccion_ola_grados=(
                        direccion[indice] if indice < len(direccion) else None
                    ),
                )
            )

    return RespuestaFuente(
        nombre=f"{nombre} ({len(alturas)} modelos)", lecturas=lecturas
    )


def lluvia_open_meteo(cfg: Config) -> RespuestaFuente:
    """Lluvia y probabilidad de lluvia.

    Va en su propia llamada, sin `models`, a propósito. Con varios modelos el
    filtro de series "todo a cero" se cargaría los datos buenos: en oleaje un
    cero constante significa que la malla te pone en tierra, pero en lluvia
    significa, simplemente, que no llueve.

    La lluvia por sí sola no hunde una moto fondeada, así que no sube el nivel.
    Sirve para dos cosas: avisar de a qué hora se estropea la cosa, y **dar o
    quitar la razón a un aviso de AEMET** cuando los modelos de mar están
    planos.
    """
    nombre = "Open-Meteo lluvia y luz"
    parametros = {
        "latitude": cfg.latitud,
        "longitude": cfg.longitud,
        "hourly": "precipitation,precipitation_probability",
        # De paso salen el amanecer y el atardecer, que hacen falta para no
        # proponerte salir a navegar de noche.
        "daily": "sunrise,sunset,uv_index_max",
        "timezone": cfg.zona_horaria,
        "forecast_days": dias_prevision(cfg.horas_vista),
    }
    try:
        datos = pedir_json(
            f"{FORECAST}?{urlencode(parametros)}", tiempo_espera=cfg.tiempo_espera
        )
    except ErrorFuente as exc:
        return RespuestaFuente(nombre=nombre, error=str(exc))

    bloque = datos.get("hourly") or {}
    tiempos = bloque.get("time") or []
    if not tiempos:
        return RespuestaFuente(nombre=nombre, error="sin datos horarios")

    lluvias = bloque.get("precipitation") or [None] * len(tiempos)
    probabilidades = bloque.get("precipitation_probability") or [None] * len(tiempos)

    lecturas = [
        Lectura(
            instante=hora_local(marca, cfg.zona_horaria),
            lluvia_mm=lluvias[i] if i < len(lluvias) else None,
            prob_lluvia_pct=probabilidades[i] if i < len(probabilidades) else None,
        )
        for i, marca in enumerate(tiempos)
    ]

    # Efemérides de hoy. Si falta algo no pasa nada: es información de adorno.
    amanecer = atardecer = None
    uv = None
    diario = datos.get("daily") or {}
    try:
        if diario.get("sunrise"):
            amanecer = hora_local(diario["sunrise"][0], cfg.zona_horaria)
        if diario.get("sunset"):
            atardecer = hora_local(diario["sunset"][0], cfg.zona_horaria)
        if diario.get("uv_index_max"):
            uv = diario["uv_index_max"][0]
    except (ValueError, IndexError, TypeError):
        pass

    return RespuestaFuente(
        nombre=nombre,
        lecturas=lecturas,
        amanecer=amanecer,
        atardecer=atardecer,
        uv_max=uv,
    )


def temperatura_mar_open_meteo(cfg: Config) -> RespuestaFuente:
    """Temperatura del agua. No decide nada, pero es lo primero que pregunta
    todo el mundo antes de bajar a la playa."""
    nombre = "Open-Meteo agua"
    parametros = {
        "latitude": cfg.latitud,
        "longitude": cfg.longitud,
        "hourly": "sea_surface_temperature",
        "timezone": cfg.zona_horaria,
        "forecast_days": dias_prevision(cfg.horas_vista),
    }
    try:
        datos = pedir_json(
            f"{MARINE}?{urlencode(parametros)}", tiempo_espera=cfg.tiempo_espera
        )
    except ErrorFuente as exc:
        return RespuestaFuente(nombre=nombre, error=str(exc))

    bloque = datos.get("hourly") or {}
    tiempos = bloque.get("time") or []
    temperaturas = bloque.get("sea_surface_temperature") or []
    if not tiempos or not temperaturas:
        return RespuestaFuente(nombre=nombre, error="sin temperatura del agua")

    lecturas = [
        Lectura(
            instante=hora_local(marca, cfg.zona_horaria),
            temperatura_mar_c=temperaturas[i] if i < len(temperaturas) else None,
        )
        for i, marca in enumerate(tiempos)
    ]
    return RespuestaFuente(nombre=nombre, lecturas=lecturas)


def viento_open_meteo(cfg: Config) -> RespuestaFuente:
    nombre = "Open-Meteo viento"
    parametros = {
        "latitude": cfg.latitud,
        "longitude": cfg.longitud,
        "hourly": "wind_speed_10m,wind_gusts_10m,wind_direction_10m",
        "models": ",".join(MODELOS_VIENTO),
        "wind_speed_unit": "kn",
        "timezone": cfg.zona_horaria,
        "forecast_days": dias_prevision(cfg.horas_vista),
    }
    try:
        datos = pedir_json(
            f"{FORECAST}?{urlencode(parametros)}", tiempo_espera=cfg.tiempo_espera
        )
    except ErrorFuente as exc:
        return RespuestaFuente(nombre=nombre, error=str(exc))

    bloque = datos.get("hourly") or {}
    tiempos = bloque.get("time") or []
    if not tiempos:
        return RespuestaFuente(nombre=nombre, error="sin datos horarios")

    vientos = _series_por_modelo(bloque, "wind_speed_10m", MODELOS_VIENTO)
    rachas = _series_por_modelo(bloque, "wind_gusts_10m", MODELOS_VIENTO)
    direcciones = _series_por_modelo(bloque, "wind_direction_10m", MODELOS_VIENTO)
    if not vientos and not rachas:
        return RespuestaFuente(nombre=nombre, error="ningún modelo con datos")

    modelos = sorted(set(vientos) | set(rachas))
    lecturas: list[Lectura] = []
    for indice, marca in enumerate(tiempos):
        instante = hora_local(marca, cfg.zona_horaria)
        for modelo in modelos:
            def _valor(fuente: dict) -> float | None:
                serie = fuente.get(modelo)
                if not serie or indice >= len(serie):
                    return None
                return serie[indice]

            viento, racha = _valor(vientos), _valor(rachas)
            if viento is None and racha is None:
                continue
            lecturas.append(
                Lectura(
                    instante=instante,
                    viento_nudos=viento,
                    racha_nudos=racha,
                    direccion_viento_grados=_valor(direcciones),
                )
            )

    return RespuestaFuente(
        nombre=f"{nombre} ({len(modelos)} modelos)", lecturas=lecturas
    )

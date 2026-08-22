"""Dibuja el mapa de situación que se manda por WhatsApp.

Estética de carta náutica nocturna: fondo oscuro, mar en degradado, retícula
de coordenadas y la costa resaltada con un halo. Está pensado para mirarse en
el móvil de noche, que es justo cuando uno se acuerda de que la moto sigue
fondeada.

Todo responde a la misma pregunta: **¿el viento entra en la cala o no?**

  * Isla real de Ibiza con la cala marcada (sale de la configuracion).
  * Cuña sobre el sector expuesto (SO-NO): si el viento cae dentro, entra mar.
  * Líneas de corriente de viento, curvadas y afiladas, en vez de flechitas.
  * Textura de olas cuya intensidad crece con la altura prevista.
  * Curva de previsión con relleno degradado y umbrales marcados.

Sin dependencias: todo se pinta a mano sobre `Lienzo`.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Optional, Sequence

from ..modelo import Consenso, Evaluacion, Nivel
from .costa import CONTORNO_IBIZA
from .lienzo import Color, Lienzo, mezclar
from .tipografia import ancho_texto, centrado, escribir

# --- Paleta de carta náutica nocturna --------------------------------------
NOCHE_ALTA = (10, 22, 36)
NOCHE_BAJA = (7, 15, 26)
MAR_HONDO = (13, 38, 61)
MAR_COSTA = (26, 74, 110)
RETICULA = (30, 58, 84)
TIERRA_ALTA = (38, 46, 54)
TIERRA_BAJA = (26, 33, 40)
COSTA_LUZ = (94, 214, 232)
TEXTO = (232, 241, 246)
TEXTO_TENUE = (128, 156, 176)
PANEL = (14, 28, 44)

COLOR_NIVEL: dict[Nivel, Color] = {
    Nivel.VERDE: (46, 200, 120),
    Nivel.AMARILLO: (245, 190, 60),
    Nivel.NARANJA: (250, 145, 50),
    Nivel.ROJO: (242, 72, 72),
}

SS = 3  # supermuestreo


class Proyeccion:
    """Pasa de (lon, lat) a píxeles, corrigiendo el achatamiento por latitud."""

    def __init__(self, puntos, ancho, alto, margen):
        lons = [p[0] for p in puntos]
        lats = [p[1] for p in puntos]
        self.lon0, self.lon1 = min(lons), max(lons)
        self.lat0, self.lat1 = min(lats), max(lats)
        # Un grado de longitud mide menos que uno de latitud según subes.
        self.k = math.cos(math.radians((self.lat0 + self.lat1) / 2))

        ancho_geo = (self.lon1 - self.lon0) * self.k
        alto_geo = self.lat1 - self.lat0
        self.escala = min(
            (ancho - 2 * margen) / ancho_geo, (alto - 2 * margen) / alto_geo
        )
        self.dx = (ancho - ancho_geo * self.escala) / 2
        self.dy = (alto - alto_geo * self.escala) / 2

    def __call__(self, lon: float, lat: float) -> tuple[float, float]:
        x = self.dx + (lon - self.lon0) * self.k * self.escala
        y = self.dy + (self.lat1 - lat) * self.escala  # y crece hacia abajo
        return x, y


def _dentro(punto, poligono) -> bool:
    """Punto dentro del polígono (regla par-impar)."""
    x, y = punto
    dentro = False
    j = len(poligono) - 1
    for i in range(len(poligono)):
        xi, yi = poligono[i]
        xj, yj = poligono[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            dentro = not dentro
        j = i
    return dentro


def _color_mar(y: int, y0: int, alto: int) -> Color:
    return mezclar(MAR_COSTA, MAR_HONDO, min(1.0, max(0.0, (y - y0) / max(1, alto))))


def _reticula(lienzo, proy, x0, y0, ancho, alto, color):
    """Retícula de latitud y longitud, como en una carta de verdad."""
    paso = 0.10
    lon = math.ceil(proy.lon0 / paso) * paso
    while lon <= proy.lon1:
        x, _ = proy(lon, proy.lat1)
        for y in range(y0, y0 + alto, 14 * SS):  # discontinua
            lienzo.rect(int(x), y, int(x) + SS, y + 7 * SS, color)
        lon += paso
    lat = math.ceil(proy.lat0 / paso) * paso
    while lat <= proy.lat1:
        _, y = proy(proy.lon0, lat)
        y = int(y) + y0
        for x in range(x0, x0 + ancho, 14 * SS):
            lienzo.rect(x, y, x + 7 * SS, y + SS, color)
        lat += paso


def _textura_olas(lienzo, x0, y0, ancho, alto, isla, intensidad, color):
    """Trazos ondulados sobre el mar; cuanta más ola, más marcados.

    Es la pista visual que hace que un mapa con temporal se *note* temporal
    aunque no leas ni un número.
    """
    if intensidad <= 0.02:
        return
    amplitud = 1.2 + 5.0 * intensidad
    separacion = int(30 * SS - 10 * SS * intensidad)
    largo = int(26 * SS + 26 * SS * intensidad)

    fila = 0
    for y in range(y0 + 10 * SS, y0 + alto - 6 * SS, max(8 * SS, separacion)):
        fila += 1
        desfase = (fila % 3) * 22 * SS
        for x in range(x0 + desfase, x0 + ancho, largo + 26 * SS):
            puntos = []
            for paso in range(0, largo, 3 * SS):
                px = x + paso
                py = y + math.sin(paso / (7.0 * SS)) * amplitud * SS
                puntos.append((px, py))
            if not puntos or _dentro(puntos[len(puntos) // 2], isla):
                continue
            lienzo.polilinea(puntos, color, max(1, int(SS * 0.7)))


def _corriente_viento(lienzo, x, y, rumbo, largo, color, brillo, isla):
    """Una línea de corriente: se curva un poco y se afila hacia la punta."""
    hacia = math.radians((rumbo + 180) % 360)
    dx, dy = math.sin(hacia), -math.cos(hacia)
    curva = math.radians(9)  # ligera deriva, para que no parezcan reglas

    puntos = [(x, y)]
    px, py = x, y
    pasos = 7
    for i in range(pasos):
        ang = hacia + curva * (i / pasos - 0.5) * 2
        px += math.sin(ang) * largo / pasos
        py -= math.cos(ang) * largo / pasos
        puntos.append((px, py))

    if _dentro(puntos[len(puntos) // 2], isla):
        return

    # Trazo que engorda hacia la punta.
    for i in range(len(puntos) - 1):
        t = i / max(1, len(puntos) - 2)
        grosor = max(1, int(SS * (0.5 + 1.5 * t)))
        lienzo.linea(
            int(puntos[i][0]), int(puntos[i][1]),
            int(puntos[i + 1][0]), int(puntos[i + 1][1]),
            mezclar(color, brillo, t), grosor,
        )

    # Punta de flecha.
    fx, fy = puntos[-1]
    for signo in (1, -1):
        ang = hacia + signo * math.radians(148)
        lienzo.linea(
            int(fx), int(fy),
            int(fx + math.sin(ang) * largo * 0.26),
            int(fy - math.cos(ang) * largo * 0.26),
            brillo, max(1, int(SS * 1.6)),
        )


def _cuna_expuesta(lienzo, cx, cy, radio, desde, hasta, acento, y0, alto):
    """Sombrea el sector por el que la mar entra en la cala."""
    if hasta < desde:
        hasta += 360
    puntos = [(cx, cy)]
    for i in range(49):
        ang = math.radians(desde + (hasta - desde) * i / 48)
        puntos.append((cx + math.sin(ang) * radio, cy - math.cos(ang) * radio))

    def color(y: int) -> Color:
        return mezclar(_color_mar(y, y0, alto), acento, 0.22)

    lienzo.poligono_por_franja(puntos, color, y_min=y0, y_max=y0 + alto - 1)


def _rosa_nautica(lienzo, cx, cy, radio, color, acento):
    """Rosa de los vientos con puntas de estrella."""
    lienzo.anillo(int(cx), int(cy), int(radio), color, max(1, SS // 2))
    lienzo.anillo(int(cx), int(cy), int(radio * 0.62), color, max(1, SS // 3))
    for i in range(8):
        ang = math.radians(i * 45)
        largo = radio if i % 2 == 0 else radio * 0.55
        lienzo.linea(
            int(cx), int(cy),
            int(cx + math.sin(ang) * largo), int(cy - math.cos(ang) * largo),
            color, max(1, SS // 2),
        )
    # Aguja al norte, resaltada.
    lienzo.linea(int(cx), int(cy), int(cx), int(cy - radio), acento, SS)
    centrado(lienzo, int(cx), int(cy - radio - 11 * SS), "N", acento, SS)


def _pastilla(lienzo, x0, y0, x1, y1, color):
    """Rectángulo con las esquinas comidas: hace de etiqueta redondeada."""
    r = min(6 * SS, (y1 - y0) // 2)
    lienzo.rect(x0 + r, y0, x1 - r, y1, color)
    lienzo.rect(x0, y0 + r, x1, y1 - r, color)
    for cx, cy in ((x0 + r, y0 + r), (x1 - r, y0 + r), (x0 + r, y1 - r), (x1 - r, y1 - r)):
        lienzo.circulo(cx, cy, r, color)


def _partir(texto: str, por_linea: int) -> list[str]:
    lineas, actual = [], ""
    for palabra in texto.split():
        if len(actual) + len(palabra) + 1 > por_linea:
            if actual:
                lineas.append(actual)
            actual = palabra
        else:
            actual = f"{actual} {palabra}".strip()
    if actual:
        lineas.append(actual)
    return lineas


def _curva_prevision(lienzo, x, y, ancho, alto, serie, evaluaciones, umbrales):
    """Curva de altura de ola con relleno degradado y líneas de umbral."""
    puntos = list(zip(serie, evaluaciones))[:13]
    if not puntos:
        return

    techo = max([(p.altura_ola_m or 0) for p, _ in puntos] + [umbrales.ola_naranja * 1.3])
    techo = max(techo * 1.15, 0.7)
    paso = ancho / max(1, len(puntos) - 1)

    def py(altura: float) -> float:
        return y + alto - alto * min(1.0, altura / techo)

    # Umbrales de aviso, al fondo. Se rotulan de arriba abajo y se salta el
    # que caiga pegado al anterior: con la mar plana los tres quedan casi
    # juntos y las cifras se pisarían.
    ultimo_rotulo = -10_000
    for valor, nivel in (
        (umbrales.ola_rojo, Nivel.ROJO),
        (umbrales.ola_naranja, Nivel.NARANJA),
        (umbrales.ola_amarillo, Nivel.AMARILLO),
    ):
        if valor > techo:
            continue
        altura_y = int(py(valor))
        for gx in range(x, x + ancho, 11 * SS):
            lienzo.rect(gx, altura_y, gx + 5 * SS, altura_y + max(1, SS // 2),
                        mezclar(PANEL, COLOR_NIVEL[nivel], 0.5))
        if altura_y - ultimo_rotulo >= 11 * SS:
            escribir(lienzo, x + ancho + 6 * SS, altura_y - 3 * SS,
                     f"{valor:.1f}", mezclar(PANEL, COLOR_NIVEL[nivel], 0.85), SS)
            ultimo_rotulo = altura_y

    trazo = [(x + i * paso, py(p.altura_ola_m or 0)) for i, (p, _) in enumerate(puntos)]

    # Relleno bajo la curva, degradado según el nivel de cada momento.
    peor = max((e.nivel for _, e in puntos), default=Nivel.VERDE)
    acento = COLOR_NIVEL[peor]
    area = trazo + [(x + ancho, y + alto), (x, y + alto)]
    lienzo.poligono_por_franja(
        area,
        lambda yy: mezclar(PANEL, acento, 0.14 + 0.46 * (1 - (yy - y) / max(1, alto))),
        y_min=y,
        y_max=y + alto,
    )

    lienzo.polilinea(trazo, acento, max(2, int(SS * 0.9)))

    # Puntos por hora, con el color de su propio nivel.
    for i, (punto, evaluacion) in enumerate(puntos):
        px, pyy = trazo[i]
        lienzo.circulo(int(px), int(pyy), int(SS * 1.9), PANEL)
        lienzo.circulo(int(px), int(pyy), int(SS * 1.2), COLOR_NIVEL[evaluacion.nivel])
        if i % 3 == 0:
            centrado(lienzo, int(px), y + alto + 7 * SS,
                     punto.instante.strftime("%H"), TEXTO_TENUE, SS)

    # Máximo, etiquetado. Se sujeta dentro del recuadro para que no se salga
    # cuando el pico cae en el primer o el último punto.
    imax = max(range(len(puntos)), key=lambda i: puntos[i][0].altura_ola_m or 0)
    mx, my = trazo[imax]
    texto_max = f"{puntos[imax][0].altura_ola_m or 0:.1f}M"
    medio = ancho_texto(texto_max, SS + 1) // 2
    mx = min(max(mx, x + medio), x + ancho - medio)
    centrado(lienzo, int(mx), max(y, int(my) - 14 * SS), texto_max, TEXTO, SS + 1,
             negrita=True)


def dibujar_mapa(
    cfg,
    ahora: datetime,
    serie: Sequence[Consenso],
    evaluaciones: Sequence[Evaluacion],
    nivel: Nivel,
    aviso_oficial: Optional[str] = None,
) -> bytes:
    """Devuelve el PNG listo para mandar."""
    ancho, alto_base = 720, 940
    lineas_aviso = _partir(aviso_oficial, 56) if aviso_oficial else []
    alto = alto_base + (30 + 15 * len(lineas_aviso) if lineas_aviso else 0)

    L = Lienzo(ancho * SS, alto * SS, NOCHE_BAJA)
    actual = serie[0] if serie else None
    acento = COLOR_NIVEL[nivel]

    # ---- Cabecera --------------------------------------------------------
    cab = 88 * SS
    L.degradado_vertical(0, 0, ancho * SS, cab, NOCHE_ALTA, PANEL)
    L.rect(0, 0, ancho * SS, int(3.5 * SS), acento)

    escribir(L, 24 * SS, 20 * SS, "VIGIA JETSKI", TEXTO, 4 * SS, negrita=True)
    escribir(L, 24 * SS, 56 * SS,
             f"{cfg.lugar} · {ahora:%d/%m %H:%M}", TEXTO_TENUE, 2 * SS)

    etiqueta = nivel.etiqueta
    pw = ancho_texto(etiqueta, 2 * SS) + 22 * SS
    _pastilla(L, ancho * SS - pw - 24 * SS, 26 * SS, ancho * SS - 24 * SS, 52 * SS, acento)
    centrado(L, ancho * SS - 24 * SS - pw // 2, 33 * SS, etiqueta, NOCHE_BAJA,
             2 * SS, negrita=True)

    desplazamiento = cab

    # ---- Aviso oficial de AEMET ------------------------------------------
    # Va lo primero porque muchas veces es la razón entera del aviso: puede
    # haber tormenta declarada con la mar completamente plana.
    if lineas_aviso:
        banda = (30 + 15 * len(lineas_aviso)) * SS
        L.rect(0, desplazamiento, ancho * SS, desplazamiento + banda,
               mezclar(PANEL, COLOR_NIVEL[Nivel.NARANJA], 0.13))
        L.rect(0, desplazamiento, int(4.5 * SS), desplazamiento + banda,
               COLOR_NIVEL[Nivel.NARANJA])
        escribir(L, 24 * SS, desplazamiento + 9 * SS, "AVISO OFICIAL AEMET",
                 COLOR_NIVEL[Nivel.AMARILLO], 2 * SS, negrita=True)
        for i, linea in enumerate(lineas_aviso):
            escribir(L, 24 * SS, desplazamiento + (27 + 15 * i) * SS, linea, TEXTO, SS + 1)
        desplazamiento += banda

    # ---- Mapa ------------------------------------------------------------
    mapa_y0, mapa_alto = desplazamiento, 500 * SS
    L.degradado_vertical(0, mapa_y0, ancho * SS, mapa_y0 + mapa_alto, MAR_COSTA, MAR_HONDO)

    proy = Proyeccion(CONTORNO_IBIZA, ancho * SS, mapa_alto, 40 * SS)
    isla = [
        (px, py + mapa_y0) for px, py in (proy(lon, lat) for lon, lat in CONTORNO_IBIZA)
    ]
    cx, cy = proy(cfg.longitud, cfg.latitud)
    cy += mapa_y0

    _reticula(L, proy, 0, mapa_y0, ancho * SS, mapa_alto, RETICULA)

    rumbo = actual.direccion_viento_grados if actual else None
    de_mar = False
    if rumbo is not None:
        from ..evaluacion import es_viento_de_mar

        de_mar = es_viento_de_mar(rumbo, cfg)

    _cuna_expuesta(
        L, cx, cy, int(330 * SS),
        cfg.sector_mar_desde, cfg.sector_mar_hasta,
        acento if de_mar else COSTA_LUZ, mapa_y0, mapa_alto,
    )

    # Textura de mar, proporcional a la ola prevista.
    ola_max = max([(p.altura_ola_m or 0) for p in serie] or [0])
    _textura_olas(
        L, 0, mapa_y0, ancho * SS, mapa_alto, isla,
        min(1.0, ola_max / max(0.9, cfg.umbrales.ola_rojo)),
        mezclar(MAR_HONDO, COSTA_LUZ, 0.22),
    )

    # Líneas de corriente del viento.
    if rumbo is not None:
        base = acento if de_mar else COSTA_LUZ
        apagado = mezclar(MAR_HONDO, base, 0.30)
        vivo = mezclar(MAR_HONDO, base, 0.92)
        paso = 104 * SS
        for gx in range(int(paso * 0.45), ancho * SS, paso):
            for gy in range(mapa_y0 + int(paso * 0.42), mapa_y0 + mapa_alto, int(paso * 0.86)):
                if _dentro((gx, gy), isla):
                    continue
                if any(abs(gx - px) < 22 * SS and abs(gy - py) < 22 * SS for px, py in isla):
                    continue
                _corriente_viento(L, gx, gy, rumbo, 46 * SS, apagado, vivo, isla)

    # Isla: halo de costa y relleno con degradado.
    L.resplandor(isla, COSTA_LUZ, MAR_HONDO, capas=3, grosor=2 * SS)
    ys = [p[1] for p in isla]
    L.poligono_por_franja(
        isla,
        lambda yy: mezclar(TIERRA_ALTA, TIERRA_BAJA,
                           (yy - min(ys)) / max(1, max(ys) - min(ys))),
        y_min=mapa_y0, y_max=mapa_y0 + mapa_alto - 1,
    )
    L.contorno(isla, COSTA_LUZ, max(1, int(SS * 0.8)))

    _rosa_nautica(L, ancho * SS - 62 * SS, mapa_y0 + 74 * SS, 24 * SS,
                  mezclar(MAR_HONDO, COSTA_LUZ, 0.5), TEXTO)

    # Marcador de la cala, con anillos.
    for radio, alfa in ((17, 0.20), (12, 0.38)):
        L.anillo(int(cx), int(cy), int(radio * SS),
                 mezclar(MAR_HONDO, acento, alfa), max(1, SS // 2))
    L.circulo(int(cx), int(cy), int(7 * SS), TEXTO)
    L.circulo(int(cx), int(cy), int(4.5 * SS), acento)

    # El nombre sale de la configuracion: sin el parentesis del municipio.
    eti = cfg.lugar.split("(")[0].strip().upper()
    ex = int(cx) + 16 * SS
    _pastilla(L, ex - 5 * SS, int(cy) - 9 * SS,
              ex + ancho_texto(eti, SS + 1) + 5 * SS, int(cy) + 8 * SS,
              mezclar(MAR_HONDO, NOCHE_BAJA, 0.55))
    escribir(L, ex, int(cy) - 5 * SS, eti, TEXTO, SS + 1, negrita=True)

    # Rótulo del viento: lo más importante del mapa, sobre panel propio.
    if rumbo is not None:
        from ..evaluacion import rumbo as a_rumbo

        titulo = f"VIENTO DEL {a_rumbo(rumbo)}"
        if actual and actual.racha_nudos:
            titulo += f"  ·  {actual.racha_nudos:.0f} KN"
        aclara = "ENTRA EN LA CALA" if de_mar else "LA CALA ESTA A RESGUARDO"
        panel_ancho = max(ancho_texto(titulo, 2 * SS), ancho_texto(aclara, 2 * SS)) + 24 * SS
        _pastilla(L, 16 * SS, mapa_y0 + 12 * SS, 16 * SS + panel_ancho,
                  mapa_y0 + 58 * SS, mezclar(NOCHE_BAJA, PANEL, 0.6))
        escribir(L, 28 * SS, mapa_y0 + 19 * SS, titulo, TEXTO, 2 * SS, negrita=True)
        escribir(L, 28 * SS, mapa_y0 + 38 * SS, aclara,
                 acento if de_mar else COLOR_NIVEL[Nivel.VERDE], 2 * SS)

    # Leyenda de la cuña, sobre pastilla: si no, las corrientes de viento le
    # pasan por encima y no hay quien la lea.
    from ..evaluacion import rumbo as _rumbo
    leyenda = (
        f"SECTOR EXPUESTO {_rumbo(cfg.sector_mar_desde)}-"
        f"{_rumbo(cfg.sector_mar_hasta)}"
    )
    _pastilla(L, 16 * SS, mapa_y0 + mapa_alto - 26 * SS,
              16 * SS + ancho_texto(leyenda, SS) + 20 * SS,
              mapa_y0 + mapa_alto - 8 * SS,
              mezclar(NOCHE_BAJA, PANEL, 0.5))
    escribir(L, 26 * SS, mapa_y0 + mapa_alto - 21 * SS, leyenda,
             mezclar(PANEL, TEXTO_TENUE, 0.9), SS)

    # ---- Cifras ----------------------------------------------------------
    y = mapa_y0 + mapa_alto
    franja = 92 * SS
    L.degradado_vertical(0, y, ancho * SS, y + franja, PANEL, NOCHE_BAJA)

    if actual:
        casillas = []
        if actual.altura_ola_m is not None:
            casillas.append(("OLA", f"{actual.altura_ola_m:.1f}", "M"))
        if actual.racha_nudos is not None:
            casillas.append(("RACHAS", f"{actual.racha_nudos:.0f}", "KN"))
        if actual.periodo_ola_s is not None:
            casillas.append(("PERIODO", f"{actual.periodo_ola_s:.0f}", "S"))
        if actual.fuentes_ola:
            casillas.append(("MODELOS", str(actual.fuentes_ola), ""))

        hueco = (ancho * SS - 48 * SS) / max(1, len(casillas))
        for i, (titulo, valor, unidad) in enumerate(casillas):
            bx = int(24 * SS + i * hueco)
            if i:
                L.rect(bx - 12 * SS, y + 22 * SS, bx - 12 * SS + max(1, SS // 2),
                       y + 68 * SS, mezclar(PANEL, TEXTO_TENUE, 0.25))
            escribir(L, bx, y + 22 * SS, titulo, TEXTO_TENUE, SS + 1)
            usado = escribir(L, bx, y + 40 * SS, valor, TEXTO, 4 * SS, negrita=True)
            if unidad:
                escribir(L, bx + usado + 3 * SS, y + 54 * SS, unidad, TEXTO_TENUE, SS + 1)

    # ---- Curva de previsión ----------------------------------------------
    y += franja + 30 * SS
    escribir(L, 24 * SS, y - 20 * SS, "ALTURA DE OLA · PROXIMAS HORAS",
             TEXTO_TENUE, SS + 1)
    _curva_prevision(L, 24 * SS, y, ancho * SS - 78 * SS, 118 * SS,
                     list(serie), list(evaluaciones), cfg.umbrales)

    # ---- Pie -------------------------------------------------------------
    escribir(L, 24 * SS, (alto - 24) * SS,
             "MEDIANA DE VARIOS MODELOS · NO ES UN AVISO OFICIAL",
             mezclar(NOCHE_BAJA, TEXTO_TENUE, 0.7), SS)

    return L.reducir(SS).a_png()

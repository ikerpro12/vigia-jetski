"""Lienzo de dibujo y codificador PNG, solo con librería estándar.

El proyecto no tiene dependencias y no se van a añadir por un dibujo: sin
Pillow ni matplotlib, aquí se monta el PNG a mano. Un PNG es más simple de lo
que parece: cabecera, un bloque IHDR, los píxeles comprimidos con zlib (que sí
está en la estándar) y un IEND.

Todo se dibuja con supermuestreo x3 y se reduce al final, que es la forma
barata de que las líneas y las diagonales no salgan con dientes de sierra.
"""

from __future__ import annotations

import struct
import zlib
from typing import Iterable, Sequence

Color = tuple[int, int, int]


class Lienzo:
    def __init__(self, ancho: int, alto: int, fondo: Color = (255, 255, 255)):
        self.ancho = ancho
        self.alto = alto
        self.pix = bytearray(bytes(fondo) * (ancho * alto))

    # -- primitivas ---------------------------------------------------------

    def punto(self, x: int, y: int, color: Color) -> None:
        if 0 <= x < self.ancho and 0 <= y < self.alto:
            i = (y * self.ancho + x) * 3
            self.pix[i : i + 3] = bytes(color)

    def rect(self, x0: int, y0: int, x1: int, y1: int, color: Color) -> None:
        x0, x1 = max(0, min(x0, x1)), min(self.ancho, max(x0, x1))
        y0, y1 = max(0, min(y0, y1)), min(self.alto, max(y0, y1))
        fila = bytes(color) * max(0, x1 - x0)
        for y in range(y0, y1):
            i = (y * self.ancho + x0) * 3
            self.pix[i : i + len(fila)] = fila

    def linea(self, x0: int, y0: int, x1: int, y1: int, color: Color, grosor: int = 1) -> None:
        """Bresenham, engordando el trazo con un cuadradito por píxel."""
        x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        r = grosor // 2
        while True:
            if grosor <= 1:
                self.punto(x0, y0, color)
            else:
                self.rect(x0 - r, y0 - r, x0 - r + grosor, y0 - r + grosor, color)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def poligono(
        self,
        puntos: Sequence[tuple[float, float]],
        color: Color,
        y_min: int | None = None,
        y_max: int | None = None,
    ) -> None:
        """Relleno por barrido de líneas, con la regla par-impar.

        `y_min`/`y_max` recortan el relleno a una banda horizontal. Lo usa el
        mapa para que la cuña del sector expuesto no se derrame fuera de su
        recuadro. En x no hace falta: `rect` ya recorta sola.
        """
        if len(puntos) < 3:
            return
        ys = [p[1] for p in puntos]
        y_ini, y_fin = max(0, int(min(ys))), min(self.alto - 1, int(max(ys)))
        if y_min is not None:
            y_ini = max(y_ini, y_min)
        if y_max is not None:
            y_fin = min(y_fin, y_max)
        for y in range(y_ini, y_fin + 1):
            centro = y + 0.5
            cortes = []
            for i in range(len(puntos)):
                x1, y1 = puntos[i]
                x2, y2 = puntos[(i + 1) % len(puntos)]
                if (y1 <= centro < y2) or (y2 <= centro < y1):
                    cortes.append(x1 + (centro - y1) / (y2 - y1) * (x2 - x1))
            cortes.sort()
            for i in range(0, len(cortes) - 1, 2):
                self.rect(int(cortes[i]), y, int(cortes[i + 1]) + 1, y + 1, color)

    def contorno(
        self, puntos: Sequence[tuple[float, float]], color: Color, grosor: int = 1
    ) -> None:
        for i in range(len(puntos)):
            x1, y1 = puntos[i]
            x2, y2 = puntos[(i + 1) % len(puntos)]
            self.linea(int(x1), int(y1), int(x2), int(y2), color, grosor)

    def circulo(self, cx: int, cy: int, radio: int, color: Color) -> None:
        for y in range(max(0, cy - radio), min(self.alto, cy + radio + 1)):
            dy = y - cy
            ancho = int((radio * radio - dy * dy) ** 0.5) if abs(dy) <= radio else -1
            if ancho >= 0:
                self.rect(cx - ancho, y, cx + ancho + 1, y + 1, color)

    def anillo(self, cx: int, cy: int, radio: int, color: Color, grosor: int = 2) -> None:
        pasos = max(24, radio * 3)
        import math

        previo = None
        for i in range(pasos + 1):
            ang = 2 * math.pi * i / pasos
            p = (cx + radio * math.cos(ang), cy + radio * math.sin(ang))
            if previo:
                self.linea(int(previo[0]), int(previo[1]), int(p[0]), int(p[1]), color, grosor)
            previo = p

    # -- color por franjas --------------------------------------------------

    def degradado_vertical(
        self, x0: int, y0: int, x1: int, y1: int, arriba: Color, abajo: Color
    ) -> None:
        """Degradado pintado fila a fila.

        Se calcula un color por línea y se rellena con `rect`, que copia bytes
        de golpe. Mezclar píxel a píxel en Python sería lentísimo.
        """
        alto = max(1, y1 - y0)
        for y in range(max(0, y0), min(self.alto, y1)):
            t = (y - y0) / alto
            self.rect(x0, y, x1, y + 1, mezclar(arriba, abajo, t))

    def poligono_por_franja(
        self,
        puntos: Sequence[tuple[float, float]],
        color_de_y,
        y_min: int | None = None,
        y_max: int | None = None,
    ) -> None:
        """Como `poligono`, pero el color se decide en cada línea.

        Permite que una forma translúcida se mezcle con el degradado que tiene
        debajo sin tener que hacer alfa de verdad.
        """
        if len(puntos) < 3:
            return
        ys = [p[1] for p in puntos]
        y_ini, y_fin = max(0, int(min(ys))), min(self.alto - 1, int(max(ys)))
        if y_min is not None:
            y_ini = max(y_ini, y_min)
        if y_max is not None:
            y_fin = min(y_fin, y_max)

        for y in range(y_ini, y_fin + 1):
            centro = y + 0.5
            cortes = []
            for i in range(len(puntos)):
                x1, y1 = puntos[i]
                x2, y2 = puntos[(i + 1) % len(puntos)]
                if (y1 <= centro < y2) or (y2 <= centro < y1):
                    cortes.append(x1 + (centro - y1) / (y2 - y1) * (x2 - x1))
            cortes.sort()
            color = color_de_y(y)
            for i in range(0, len(cortes) - 1, 2):
                self.rect(int(cortes[i]), y, int(cortes[i + 1]) + 1, y + 1, color)

    def polilinea(
        self, puntos: Sequence[tuple[float, float]], color: Color, grosor: int = 1
    ) -> None:
        for i in range(len(puntos) - 1):
            x1, y1 = puntos[i]
            x2, y2 = puntos[i + 1]
            self.linea(int(x1), int(y1), int(x2), int(y2), color, grosor)

    def resplandor(
        self,
        puntos: Sequence[tuple[float, float]],
        color: Color,
        fondo: Color,
        capas: int = 4,
        grosor: int = 3,
    ) -> None:
        """Halo alrededor de un trazo: varias pasadas cada vez más finas y
        más cerca del color final. Sale más barato que desenfocar de verdad."""
        for capa in range(capas, 0, -1):
            tono = mezclar(fondo, color, 0.16 + 0.2 * (capas - capa))
            self.contorno(puntos, tono, grosor * capa)

    # -- reducción y salida -------------------------------------------------

    def reducir(self, factor: int) -> "Lienzo":
        """Promedia bloques de factor x factor: el antialiasing del pobre."""
        if factor <= 1:
            return self
        ancho, alto = self.ancho // factor, self.alto // factor
        salida = Lienzo(ancho, alto)
        n = factor * factor
        for y in range(alto):
            for x in range(ancho):
                r = g = b = 0
                for dy in range(factor):
                    base = ((y * factor + dy) * self.ancho + x * factor) * 3
                    for dx in range(factor):
                        i = base + dx * 3
                        r += self.pix[i]
                        g += self.pix[i + 1]
                        b += self.pix[i + 2]
                i = (y * ancho + x) * 3
                salida.pix[i : i + 3] = bytes((r // n, g // n, b // n))
        return salida

    def a_png(self) -> bytes:
        """Empaqueta los píxeles como PNG RGB de 8 bits."""
        crudo = bytearray()
        paso = self.ancho * 3
        for y in range(self.alto):
            crudo.append(0)  # filtro "None" para esta fila
            crudo += self.pix[y * paso : (y + 1) * paso]

        def bloque(tipo: bytes, datos: bytes) -> bytes:
            cuerpo = tipo + datos
            return (
                struct.pack(">I", len(datos))
                + cuerpo
                + struct.pack(">I", zlib.crc32(cuerpo) & 0xFFFFFFFF)
            )

        cabecera = struct.pack(">IIBBBBB", self.ancho, self.alto, 8, 2, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + bloque(b"IHDR", cabecera)
            + bloque(b"IDAT", zlib.compress(bytes(crudo), 9))
            + bloque(b"IEND", b"")
        )


def mezclar(fondo: Color, frente: Color, alfa: float) -> Color:
    """Mezcla dos colores. Sirve para las zonas sombreadas del mapa."""
    return tuple(  # type: ignore[return-value]
        int(fondo[i] * (1 - alfa) + frente[i] * alfa) for i in range(3)
    )

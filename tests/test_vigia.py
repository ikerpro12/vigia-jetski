"""Pruebas de la lógica de decisión. Se ejecutan con:  python -m tests.test_vigia

No hacen ninguna llamada de red: todo son datos inventados.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vigia.config import Config  # noqa: E402
from vigia.consenso import construir_consenso  # noqa: E402
from vigia.estado import (  # noqa: E402
    Estado,
    actualizar,
    anotar_stormglass,
    decidir,
    intervalo_sugerido,
    parte_pendiente,
    toca_comprobar,
)
from vigia.evaluacion import (  # noqa: E402
    corrobora_aviso,
    es_viento_de_mar,
    evaluar_hora,
    evaluar_serie,
    primer_aviso,
    rumbo,
)
from vigia.mensaje import componer  # noqa: E402
from vigia.modelo import Consenso, Lectura, Nivel, RespuestaFuente  # noqa: E402

MADRID = ZoneInfo("Europe/Madrid")
T0 = datetime(2026, 8, 10, 12, 0, tzinfo=MADRID)


def cfg() -> Config:
    return Config()


class PruebaViento(unittest.TestCase):
    def test_sector_de_mar_en_cala_tarida(self):
        c = cfg()
        # La cala mira al oeste: del SO, O y NO entra la mar.
        for grados in (225, 250, 270, 300, 330):
            self.assertTrue(es_viento_de_mar(grados, c), f"{grados}° debería ser de mar")
        # Del este está resguardada.
        for grados in (0, 45, 90, 135, 180):
            self.assertFalse(es_viento_de_mar(grados, c), f"{grados}° debería ser de tierra")

    def test_rumbo_en_castellano(self):
        self.assertEqual(rumbo(0), "N")
        self.assertEqual(rumbo(90), "E")
        self.assertEqual(rumbo(180), "S")
        self.assertEqual(rumbo(270), "O")
        self.assertEqual(rumbo(225), "SO")
        self.assertEqual(rumbo(None), "?")


class PruebaEvaluacion(unittest.TestCase):
    def test_mar_en_calma_es_verde(self):
        punto = Consenso(
            instante=T0, altura_ola_m=0.2, racha_nudos=8, direccion_viento_grados=90,
            periodo_ola_s=5,
        )
        self.assertEqual(evaluar_hora(punto, cfg()).nivel, Nivel.VERDE)

    def test_viento_de_mar_agrava_el_aviso(self):
        """La misma ola, pero con el viento entrando en la cala, sube de nivel."""
        base = dict(instante=T0, altura_ola_m=1.0, racha_nudos=12, periodo_ola_s=6)
        de_tierra = evaluar_hora(Consenso(**base, direccion_viento_grados=90), cfg())
        de_mar = evaluar_hora(Consenso(**base, direccion_viento_grados=270), cfg())

        self.assertGreater(de_mar.nivel, de_tierra.nivel)
        self.assertTrue(de_mar.viento_de_mar)
        self.assertFalse(de_tierra.viento_de_mar)

    def test_temporal_del_oeste_es_rojo(self):
        punto = Consenso(
            instante=T0, altura_ola_m=1.8, racha_nudos=32,
            direccion_viento_grados=260, periodo_ola_s=7,
        )
        self.assertEqual(evaluar_hora(punto, cfg()).nivel, Nivel.ROJO)

    def test_periodo_corto_suma(self):
        largo = evaluar_hora(
            Consenso(instante=T0, altura_ola_m=0.95, periodo_ola_s=8,
                     direccion_viento_grados=90, racha_nudos=10), cfg()
        )
        corto = evaluar_hora(
            Consenso(instante=T0, altura_ola_m=0.95, periodo_ola_s=3.2,
                     direccion_viento_grados=90, racha_nudos=10), cfg()
        )
        self.assertGreater(corto.nivel, largo.nivel)

    def test_solo_racha_fuerte_ya_avisa(self):
        punto = Consenso(
            instante=T0, altura_ola_m=0.2, racha_nudos=40,
            direccion_viento_grados=270, periodo_ola_s=5,
        )
        self.assertEqual(evaluar_hora(punto, cfg()).nivel, Nivel.ROJO)

    def test_discrepancia_entre_fuentes_no_se_ignora(self):
        punto = Consenso(
            instante=T0, altura_ola_m=0.55, altura_ola_min_m=0.3,
            altura_ola_max_m=1.2, direccion_viento_grados=90,
            racha_nudos=10, periodo_ola_s=6,
        )
        resultado = evaluar_hora(punto, cfg())
        self.assertTrue(any("discrepan" in m for m in resultado.motivos))


class PruebaConsenso(unittest.TestCase):
    def _respuesta(self, nombre: str, alturas: list[float]) -> RespuestaFuente:
        return RespuestaFuente(
            nombre=nombre,
            lecturas=[
                Lectura(instante=T0 + timedelta(hours=i), altura_ola_m=a)
                for i, a in enumerate(alturas)
            ],
        )

    def test_con_tres_fuentes_usa_mediana(self):
        """Una fuente disparatada no debe arrastrar el resultado."""
        respuestas = [
            self._respuesta("a", [1.0]),
            self._respuesta("b", [1.1]),
            self._respuesta("c", [9.0]),  # claramente rota
        ]
        serie = construir_consenso(respuestas, T0, 6)
        self.assertAlmostEqual(serie[0].altura_ola_m, 1.1)
        self.assertEqual(serie[0].fuentes_ola, 3)

    def test_con_dos_fuentes_usa_el_maximo(self):
        """Sin mayoría no se puede descartar nada: se peca de prudente."""
        respuestas = [self._respuesta("a", [0.4]), self._respuesta("b", [1.3])]
        serie = construir_consenso(respuestas, T0, 6)
        self.assertAlmostEqual(serie[0].altura_ola_m, 1.3)

    def test_una_fuente_caida_no_rompe_nada(self):
        respuestas = [
            self._respuesta("a", [0.6]),
            RespuestaFuente(nombre="b", error="timeout"),
        ]
        serie = construir_consenso(respuestas, T0, 6)
        self.assertAlmostEqual(serie[0].altura_ola_m, 0.6)

    def test_respeta_la_ventana_de_horas(self):
        respuestas = [self._respuesta("a", [0.5] * 48)]
        serie = construir_consenso(respuestas, T0, 12)
        self.assertLessEqual(len(serie), 13)


class PruebaMargen(unittest.TestCase):
    def test_encuentra_la_primera_hora_peligrosa(self):
        """Lo importante no es que haya temporal, sino cuánto margen queda."""
        c = cfg()
        serie = [
            Consenso(
                instante=T0 + timedelta(hours=i),
                altura_ola_m=0.2 if i < 4 else 1.6,
                direccion_viento_grados=270,
                racha_nudos=10 if i < 4 else 30,
                periodo_ola_s=6,
            )
            for i in range(12)
        ]
        evaluaciones = [evaluar_hora(p, c) for p in serie]
        disparo = primer_aviso(evaluaciones, Nivel.NARANJA)

        self.assertIsNotNone(disparo)
        self.assertEqual(disparo.instante, T0 + timedelta(hours=4))


HORAS_PARTE = (8, 14, 23)


def _decidir(estado, nivel, momento, minimo=Nivel.NARANJA, cada=5, tope=5):
    return decidir(estado, nivel, momento, minimo, cada, tope, HORAS_PARTE)


class PruebaTopeporDefecto(unittest.TestCase):
    """Lo pidió el dueño de la moto: uno o dos avisos, no una ristra."""

    def test_por_defecto_como_mucho_dos_avisos(self):
        c = cfg()
        self.assertEqual(c.escalada_max, 2)
        self.assertEqual(c.escalada_minutos, 15)

    def test_el_segundo_aviso_cierra_el_episodio(self):
        estado = Estado()
        c = cfg()
        momento = T0
        enviados = 0
        # Cuatro horas de temporal, comprobando cada 5 minutos.
        for _ in range(48):
            d = decidir(estado, Nivel.NARANJA, momento, Nivel.NARANJA,
                        c.escalada_minutos, c.escalada_max, c.horas_parte)
            if d.enviar:
                enviados += 1
                estado = actualizar(estado, Nivel.NARANJA, momento, d, True)
            momento += timedelta(minutes=5)
        self.assertEqual(enviados, 2)

    def test_empeorar_a_rojo_sigue_pasando_el_tope(self):
        """Naranja a rojo no es spam: es información nueva."""
        c = cfg()
        estado = Estado()
        momento = T0
        for _ in range(12):
            d = decidir(estado, Nivel.NARANJA, momento, Nivel.NARANJA,
                        c.escalada_minutos, c.escalada_max, c.horas_parte)
            if d.enviar:
                estado = actualizar(estado, Nivel.NARANJA, momento, d, True)
            momento += timedelta(minutes=5)
        self.assertEqual(estado.episodio_mensajes, 2)  # ya en el tope

        d = decidir(estado, Nivel.ROJO, momento, Nivel.NARANJA,
                    c.escalada_minutos, c.escalada_max, c.horas_parte)
        self.assertTrue(d.enviar)
        self.assertIn("empeora", d.motivo)


class PruebaCadencia(unittest.TestCase):
    """El punto delicado: avisar al instante sin acabar inundando el grupo."""

    def _episodio_abierto(self, momento, mensajes=1, nivel=Nivel.NARANJA):
        return Estado(
            ultimo_nivel=int(nivel),
            ultimo_aviso_iso=momento.isoformat(),
            episodio_inicio_iso=momento.isoformat(),
            episodio_mensajes=mensajes,
            episodio_nivel_max=int(nivel),
        )

    def test_el_primer_peligro_avisa_al_instante(self):
        d = _decidir(Estado(), Nivel.NARANJA, T0)
        self.assertTrue(d.enviar)
        self.assertEqual(d.tipo, "alerta")
        self.assertIn("inmediato", d.motivo)

    def test_no_repite_antes_de_cinco_minutos(self):
        estado = self._episodio_abierto(T0)
        d = _decidir(estado, Nivel.NARANJA, T0 + timedelta(minutes=3))
        self.assertFalse(d.enviar)

    def test_repite_pasados_cinco_minutos(self):
        estado = self._episodio_abierto(T0)
        d = _decidir(estado, Nivel.NARANJA, T0 + timedelta(minutes=6))
        self.assertTrue(d.enviar)

    def test_tope_de_cinco_mensajes_por_episodio(self):
        estado = self._episodio_abierto(T0, mensajes=5)
        d = _decidir(estado, Nivel.NARANJA, T0 + timedelta(minutes=30))
        self.assertFalse(d.enviar)
        self.assertIn("tope", d.motivo)

    def test_empeorar_rompe_el_tope(self):
        """Pasar de naranja a rojo sí merece interrumpir, aunque estés al tope."""
        estado = self._episodio_abierto(T0, mensajes=5, nivel=Nivel.NARANJA)
        d = _decidir(estado, Nivel.ROJO, T0 + timedelta(minutes=30))
        self.assertTrue(d.enviar)
        self.assertIn("empeora", d.motivo)

    def test_avisa_de_la_vuelta_a_la_calma_una_sola_vez(self):
        """El 'ya pasó' llega, pero solo tras una hora de calma sostenida."""
        estado = self._episodio_abierto(T0, mensajes=2, nivel=Nivel.ROJO)

        # Primera lectura tranquila: arranca el reloj, todavía no se dice nada.
        primera = T0 + timedelta(hours=8)
        d = _decidir(estado, Nivel.VERDE, primera)
        self.assertFalse(d.enviar)
        estado = actualizar(estado, Nivel.VERDE, primera, d, False, Nivel.NARANJA)

        # Pasada la hora de margen, ahora sí.
        despues = primera + timedelta(minutes=70)
        d = _decidir(estado, Nivel.VERDE, despues)
        self.assertTrue(d.enviar)
        self.assertEqual(d.tipo, "calma")

        # Y no insiste.
        estado = actualizar(estado, Nivel.VERDE, despues, d, True, Nivel.NARANJA)
        siguiente = _decidir(estado, Nivel.VERDE, despues + timedelta(hours=1))
        self.assertFalse(siguiente.enviar)

    def test_episodio_nuevo_vuelve_a_avisar_al_instante(self):
        """Cerrado un temporal, el siguiente vuelve a avisar sin esperas."""
        estado = self._episodio_abierto(T0, mensajes=2)

        momento = T0 + timedelta(hours=2)
        for _ in range(16):  # 80 min de calma: cierra el episodio
            d = _decidir(estado, Nivel.VERDE, momento)
            estado = actualizar(estado, Nivel.VERDE, momento, d, d.enviar, Nivel.NARANJA)
            momento += timedelta(minutes=5)
        self.assertFalse(estado.en_episodio)

        d = _decidir(estado, Nivel.ROJO, momento)
        self.assertTrue(d.enviar)
        self.assertIn("inmediato", d.motivo)


class PruebaAvisoAemetContrastado(unittest.TestCase):
    """Un aviso de AEMET ya no dispara la alarma él solo.

    AEMET avisa por zonas grandes: su aviso para "aguas de Ibiza y Formentera"
    puede ser por un chubasco al otro lado de la isla. Si ningún modelo lo
    respalda, se enseña pero no se molesta a nadie.
    """

    def _serie(self, ola=0.15, racha=5.0, lluvia=0.0, prob=0.0, rumbo_=90.0):
        return [
            Consenso(
                instante=T0 + timedelta(hours=i),
                altura_ola_m=ola,
                periodo_ola_s=6.0,
                racha_nudos=racha,
                direccion_viento_grados=rumbo_,
                lluvia_mm=lluvia,
                prob_lluvia_pct=prob,
                fuentes_ola=4,
            )
            for i in range(6)
        ]

    def _componer(self, serie, con_aviso=True):
        respuestas = [
            RespuestaFuente(
                nombre="AEMET",
                boletin="boletin",
                aviso_oficial="Tormenta en aguas de Ibiza." if con_aviso else None,
            )
        ]
        return componer(cfg(), T0, serie, evaluar_serie(serie, cfg()), respuestas)

    def test_mar_plana_y_sin_lluvia_no_dispara_la_alarma(self):
        nivel, texto = self._componer(self._serie())
        self.assertEqual(nivel, Nivel.AMARILLO)   # vigilar, pero sin mensaje
        self.assertLess(nivel, Nivel.NARANJA)
        self.assertIn("ningún modelo ve nada", texto)

    def test_si_hay_lluvia_prevista_si_dispara(self):
        nivel, texto = self._componer(self._serie(lluvia=2.0))
        self.assertGreaterEqual(nivel, Nivel.NARANJA)
        self.assertIn("respaldan", texto)

    def test_si_sube_la_mar_si_dispara(self):
        nivel, _ = self._componer(self._serie(ola=0.7))
        self.assertGreaterEqual(nivel, Nivel.NARANJA)

    def test_si_hay_rachas_si_dispara(self):
        nivel, _ = self._componer(self._serie(racha=20.0))
        self.assertGreaterEqual(nivel, Nivel.NARANJA)

    def test_alta_probabilidad_de_lluvia_tambien_cuenta(self):
        respalda, _ = corrobora_aviso(self._serie(prob=80.0), cfg())
        self.assertTrue(respalda)

    def test_sin_aviso_de_aemet_la_mar_plana_es_verde(self):
        nivel, _ = self._componer(self._serie(), con_aviso=False)
        self.assertEqual(nivel, Nivel.VERDE)


class PruebaVientoDeTierraFuerte(unittest.TestCase):
    def test_las_rachas_fuertes_no_se_rebajan_por_ser_de_tierra(self):
        """Un viento de tierra fuerte puede llevarse la moto mar adentro."""
        flojo = evaluar_hora(
            Consenso(instante=T0, altura_ola_m=0.6, racha_nudos=20,
                     direccion_viento_grados=90, periodo_ola_s=6), cfg()
        )
        fuerte = evaluar_hora(
            Consenso(instante=T0, altura_ola_m=0.6, racha_nudos=30,
                     direccion_viento_grados=90, periodo_ola_s=6), cfg()
        )
        self.assertGreater(fuerte.nivel, flojo.nivel)
        self.assertTrue(any("mar adentro" in m for m in fuerte.motivos))


class PruebaLoQueViene(unittest.TestCase):
    """El sentido de todo esto es enterarse ANTES, no cuando ya pasa."""

    def test_anuncia_cuando_va_a_empeorar(self):
        serie = [
            Consenso(
                instante=T0 + timedelta(hours=i),
                altura_ola_m=0.2 if i < 3 else 1.2,
                periodo_ola_s=6.0,
                racha_nudos=8 if i < 3 else 28,
                direccion_viento_grados=265.0,
                fuentes_ola=4,
            )
            for i in range(8)
        ]
        _, texto = componer(cfg(), T0, serie, evaluar_serie(serie, cfg()), [])
        self.assertIn("Lo que viene", texto)
        self.assertIn("sube a", texto)

    def test_anuncia_la_lluvia(self):
        serie = [
            Consenso(
                instante=T0 + timedelta(hours=i),
                altura_ola_m=0.2, periodo_ola_s=6.0, racha_nudos=6,
                direccion_viento_grados=90.0,
                lluvia_mm=0.0 if i < 2 else 3.0,
                prob_lluvia_pct=10.0 if i < 2 else 85.0,
                fuentes_ola=4,
            )
            for i in range(6)
        ]
        _, texto = componer(cfg(), T0, serie, evaluar_serie(serie, cfg()), [])
        self.assertIn("lluvia", texto.lower())


class PruebaNautica(unittest.TestCase):
    """Terminología de mar. Si esto se equivoca, canta muchísimo."""

    def test_escala_douglas(self):
        from vigia.nautica import estado_mar

        # Los tramos de la escala son límite inferior: 0,2 m es marejadilla.
        self.assertEqual(estado_mar(0.0), "calma chicha")
        self.assertEqual(estado_mar(0.05), "mar rizada")
        self.assertEqual(estado_mar(0.2), "marejadilla")
        self.assertEqual(estado_mar(0.49), "marejadilla")
        self.assertEqual(estado_mar(0.5), "marejada")
        self.assertEqual(estado_mar(1.3), "fuerte marejada")
        self.assertEqual(estado_mar(3.0), "mar gruesa")
        self.assertEqual(estado_mar(None), "?")

    def test_escala_beaufort(self):
        from vigia.nautica import fuerza_viento

        self.assertEqual(fuerza_viento(0.5)[0], 0)
        self.assertEqual(fuerza_viento(5)[0], 2)
        self.assertEqual(fuerza_viento(14)[0], 4)
        self.assertEqual(fuerza_viento(25)[0], 6)
        self.assertEqual(fuerza_viento(36)[0], 8)
        self.assertEqual(fuerza_viento(80)[0], 12)

    def test_veredicto_para_salir(self):
        from vigia.nautica import veredicto_salida

        self.assertEqual(veredicto_salida(0.1, 8)[0], "🟢")
        self.assertEqual(veredicto_salida(0.6, 18)[0], "🟡")
        self.assertEqual(veredicto_salida(0.9, 24)[0], "🟠")
        self.assertEqual(veredicto_salida(1.5, 30)[0], "🔴")

    def test_el_mar_picado_se_menciona(self):
        from vigia.nautica import veredicto_salida

        _, frase = veredicto_salida(0.3, 12, periodo_s=3.0)
        self.assertIn("picada", frase)

    def test_la_mejor_ventana_evita_la_noche(self):
        """No tiene sentido proponer salir a las tres de la mañana."""
        from vigia.nautica import mejor_ventana

        amanecer = T0.replace(hour=7, minute=0)
        atardecer = T0.replace(hour=21, minute=0)
        serie = []
        for i in range(24):
            momento = T0.replace(hour=0, minute=0) + timedelta(hours=i)
            # La mar más plana es de madrugada, pero no vale.
            serie.append(Consenso(instante=momento,
                                  altura_ola_m=0.05 if i < 5 else 0.3,
                                  racha_nudos=5.0, periodo_ola_s=6.0))
        ventana = mejor_ventana(serie, amanecer, atardecer)
        self.assertIsNotNone(ventana)
        self.assertGreaterEqual(ventana[0].hour, 7)
        self.assertLessEqual(ventana[1].hour, 21)

    def test_luz_restante(self):
        from vigia.nautica import luz_restante

        self.assertIsNone(luz_restante(T0, None))
        self.assertIsNone(luz_restante(T0.replace(hour=22), T0.replace(hour=21)))
        self.assertIn("2 h", luz_restante(T0, T0 + timedelta(hours=2)))


class PruebaMensajeUtil(unittest.TestCase):
    def _serie(self):
        return [
            Consenso(instante=T0 + timedelta(hours=i), altura_ola_m=0.25,
                     periodo_ola_s=6.0, viento_nudos=9.0, racha_nudos=12.0,
                     direccion_viento_grados=90.0, temperatura_mar_c=27.0,
                     fuentes_ola=4)
            for i in range(8)
        ]

    def test_ya_no_se_pega_el_boletin_entero(self):
        """Eran cinco líneas de sinóptica que nadie lee en el móvil."""
        respuestas = [RespuestaFuente(
            nombre="AEMET",
            boletin="Baja de 1014 al norte de Argelia con pocos cambios. " * 6,
        )]
        serie = self._serie()
        _, texto = componer(cfg(), T0, serie, evaluar_serie(serie, cfg()), respuestas)
        self.assertNotIn("Baja de 1014", texto)

    def test_trae_la_informacion_util(self):
        serie = self._serie()
        respuestas = [RespuestaFuente(
            nombre="luz", lecturas=[],
            amanecer=T0.replace(hour=7), atardecer=T0.replace(hour=21),
        )]
        _, texto = componer(cfg(), T0, serie, evaluar_serie(serie, cfg()), respuestas)
        self.assertIn("marejadilla", texto)          # estado de la mar
        self.assertIn("fuerza", texto)               # Beaufort
        self.assertIn("Para salir con la moto", texto)
        self.assertIn("agua 27", texto.lower())      # temperatura del agua
        self.assertIn("luz hasta", texto.lower())    # cuánta luz queda


class PruebaHisteresis(unittest.TestCase):
    """El 11/08/2026 el nivel bailó alrededor del umbral y salieron seis
    mensajes en una hora: naranja, verde, naranja, naranja, verde, naranja.

    El tope de 2 por episodio no servía de nada, porque cada bajada cerraba el
    episodio y cada subida abría uno nuevo. Estas pruebas fijan el arreglo.
    """

    def _simular(self, niveles, cada_min=5, calma=60):
        """Reproduce una secuencia de niveles y cuenta los mensajes."""
        c = cfg()
        estado, momento, enviados = Estado(), T0, []
        for nivel in niveles:
            d = decidir(estado, nivel, momento, Nivel.NARANJA,
                        c.escalada_minutos, c.escalada_max, c.horas_parte, calma)
            if d.enviar:
                enviados.append((momento.strftime("%H:%M"), nivel.etiqueta, d.tipo))
                estado = actualizar(estado, nivel, momento, d, True, Nivel.NARANJA)
            else:
                estado = actualizar(estado, nivel, momento, d, False, Nivel.NARANJA)
            momento += timedelta(minutes=cada_min)
        return enviados

    def test_el_caso_real_del_11_de_agosto(self):
        N, V = Nivel.NARANJA, Nivel.VERDE
        secuencia = [N, N, V, N, N, V, N, N, N, N, N, N]
        enviados = self._simular(secuencia)
        # Antes: 6 mensajes. Ahora: el aviso inicial y su recordatorio.
        self.assertEqual(len(enviados), 2, f"demasiados mensajes: {enviados}")
        self.assertTrue(all(t == "alerta" for _, _, t in enviados))

    def test_un_bajon_corto_no_da_el_todo_despejado(self):
        N, V = Nivel.NARANJA, Nivel.VERDE
        enviados = self._simular([N] + [V] * 6)  # 30 min de calma, no basta
        self.assertEqual([t for _, _, t in enviados], ["alerta"])

    def test_la_calma_sostenida_si_cierra_el_aviso(self):
        N, V = Nivel.NARANJA, Nivel.VERDE
        enviados = self._simular([N] + [V] * 15)  # 75 min de calma
        tipos = [t for _, _, t in enviados]
        self.assertIn("calma", tipos)
        self.assertEqual(tipos.count("calma"), 1, "el 'ya pasó' se manda una vez")

    def test_volver_a_subir_reinicia_el_reloj_de_la_calma(self):
        """Si en mitad de la espera vuelve el peligro, no hay 'ya pasó'."""
        N, V = Nivel.NARANJA, Nivel.VERDE
        enviados = self._simular([N] + [V] * 8 + [N] + [V] * 8)
        self.assertNotIn("calma", [t for _, _, t in enviados])

    def test_amarillo_no_cierra_el_episodio_de_golpe(self):
        N, A = Nivel.NARANJA, Nivel.AMARILLO
        enviados = self._simular([N] + [A] * 6)
        self.assertNotIn("calma", [t for _, _, t in enviados])

    def test_empeorar_sigue_avisando_pese_a_la_histeresis(self):
        N, V, R = Nivel.NARANJA, Nivel.VERDE, Nivel.ROJO
        enviados = self._simular([N, N, V, V, R])
        self.assertEqual(enviados[-1][1], "ROJO")


class PruebaPartesDiarios(unittest.TestCase):
    def test_manda_el_parte_a_las_ocho(self):
        momento = T0.replace(hour=8, minute=5)
        d = _decidir(Estado(), Nivel.VERDE, momento)
        self.assertTrue(d.enviar)
        self.assertEqual(d.tipo, "parte")
        self.assertEqual(d.hora_parte, 8)

    def test_no_repite_el_parte_ya_enviado(self):
        momento = T0.replace(hour=8, minute=5)
        estado = Estado()
        d = _decidir(estado, Nivel.VERDE, momento)
        estado = actualizar(estado, Nivel.VERDE, momento, d, True)

        otra = _decidir(estado, Nivel.VERDE, momento.replace(minute=35))
        self.assertFalse(otra.enviar)

    def test_parte_con_retraso_se_apunta_en_su_franja(self):
        """Si el cron se despista, el parte de las 8 sale tarde pero no dos veces."""
        tarde = T0.replace(hour=9, minute=10)
        estado = Estado()
        d = _decidir(estado, Nivel.VERDE, tarde)
        self.assertTrue(d.enviar)
        self.assertEqual(d.hora_parte, 8)

        estado = actualizar(estado, Nivel.VERDE, tarde, d, True)
        self.assertIn(8, estado.partes_horas)
        self.assertNotIn(9, estado.partes_horas)

    def test_las_tres_franjas_del_dia(self):
        estado = Estado()
        enviados = []
        for hora in (8, 14, 23):
            momento = T0.replace(hour=hora, minute=2)
            d = _decidir(estado, Nivel.VERDE, momento)
            if d.enviar:
                enviados.append(d.hora_parte)
                estado = actualizar(estado, Nivel.VERDE, momento, d, True)
        self.assertEqual(enviados, [8, 14, 23])

    def test_a_media_tarde_no_manda_nada(self):
        d = _decidir(Estado(), Nivel.VERDE, T0.replace(hour=17, minute=30))
        self.assertFalse(d.enviar)

    def test_el_peligro_manda_sobre_el_parte(self):
        d = _decidir(Estado(), Nivel.ROJO, T0.replace(hour=8, minute=5))
        self.assertEqual(d.tipo, "alerta")


class PruebaStormglass(unittest.TestCase):
    def test_cuenta_los_usos_del_dia(self):
        estado = Estado()
        for _ in range(3):
            estado = anotar_stormglass(estado, T0.date())
        self.assertEqual(estado.usos_stormglass_hoy(T0.date()), 3)

    def test_el_contador_se_reinicia_cada_dia(self):
        estado = anotar_stormglass(Estado(), T0.date())
        maniana = (T0 + timedelta(days=1)).date()
        self.assertEqual(estado.usos_stormglass_hoy(maniana), 0)

    def test_hace_caso_al_contador_de_stormglass(self):
        """Si la API dice que vamos por 7, mandan sus números y no los nuestros."""
        estado = anotar_stormglass(Estado(), T0.date(), usos=7)
        self.assertEqual(estado.usos_stormglass_hoy(T0.date()), 7)


class PruebaFrenoDelCron(unittest.TestCase):
    """El cron salta cada 5 min; el freno lo convierte en 15 con la mar plana.

    Lo crítico aquí es que el freno NUNCA retrase un aviso de peligro.
    """

    def _estado(self, hace_minutos, nivel=Nivel.VERDE):
        return Estado(
            ultimo_nivel=int(nivel),
            ultima_comprobacion_iso=(T0 - timedelta(minutes=hace_minutos)).isoformat(),
        )

    def test_en_calma_espera_quince_minutos(self):
        seguir, _ = toca_comprobar(self._estado(5), T0, cfg())
        self.assertFalse(seguir)

        seguir, _ = toca_comprobar(self._estado(15), T0, cfg())
        self.assertTrue(seguir)

    def test_con_peligro_comprueba_cada_cinco(self):
        """Si el último nivel ya era malo, no se salta ni una pasada."""
        seguir, _ = toca_comprobar(self._estado(5, Nivel.NARANJA), T0, cfg())
        self.assertTrue(seguir)

        seguir, _ = toca_comprobar(self._estado(5, Nivel.ROJO), T0, cfg())
        self.assertTrue(seguir)

    def test_en_amarillo_ritmo_intermedio(self):
        seguir, _ = toca_comprobar(self._estado(5, Nivel.AMARILLO), T0, cfg())
        self.assertFalse(seguir)
        seguir, _ = toca_comprobar(self._estado(10, Nivel.AMARILLO), T0, cfg())
        self.assertTrue(seguir)

    def test_el_parte_diario_salta_el_freno(self):
        estado = self._estado(1)
        seguir, motivo = toca_comprobar(estado, T0.replace(hour=8, minute=1), cfg())
        self.assertTrue(seguir)
        self.assertIn("parte", motivo)

    def test_la_primera_vez_siempre_comprueba(self):
        seguir, _ = toca_comprobar(Estado(), T0, cfg())
        self.assertTrue(seguir)

    def test_tolera_el_desfase_del_cron(self):
        """A los 14 min y pico ya vale: si no, se perdería una pasada de cada dos."""
        seguir, _ = toca_comprobar(self._estado(14.5), T0, cfg())
        self.assertTrue(seguir)


class PruebaIntervalo(unittest.TestCase):
    def test_mira_mas_a_menudo_cuanto_peor_esta(self):
        c = cfg()
        self.assertEqual(intervalo_sugerido(Nivel.VERDE, c), c.intervalo_calma)
        self.assertEqual(intervalo_sugerido(Nivel.AMARILLO, c), c.intervalo_ojo)
        self.assertEqual(intervalo_sugerido(Nivel.NARANJA, c), c.intervalo_alerta)
        self.assertEqual(intervalo_sugerido(Nivel.ROJO, c), c.intervalo_alerta)
        self.assertLess(c.intervalo_alerta, c.intervalo_calma)


class PruebaMapa(unittest.TestCase):
    """El mapa se genera a mano, sin librerías: conviene comprobarlo."""

    def _serie(self, n=13, altura=0.4, rumbo=265.0):
        return [
            Consenso(
                instante=T0 + timedelta(hours=i),
                altura_ola_m=altura + i * 0.1,
                altura_ola_min_m=altura,
                altura_ola_max_m=altura + i * 0.2,
                altura_ola_p75_m=altura + i * 0.15,
                periodo_ola_s=5.5,
                viento_nudos=12 + i,
                racha_nudos=16 + i * 1.5,
                direccion_viento_grados=rumbo,
                fuentes_ola=5,
                fuentes_viento=6,
            )
            for i in range(n)
        ]

    def test_genera_un_png_valido(self):
        from vigia.grafico import dibujar_mapa

        serie = self._serie()
        png = dibujar_mapa(cfg(), T0, serie, evaluar_serie(serie, cfg()), Nivel.NARANJA)
        # Firma PNG y bloque final.
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertTrue(png.endswith(b"IEND\xaeB`\x82"))
        self.assertGreater(len(png), 5000)

    def test_las_dimensiones_van_en_la_cabecera(self):
        import struct

        from vigia.grafico import dibujar_mapa

        serie = self._serie()
        png = dibujar_mapa(cfg(), T0, serie, evaluar_serie(serie, cfg()), Nivel.VERDE)
        ancho, alto = struct.unpack(">II", png[16:24])
        self.assertEqual(ancho, 720)
        self.assertGreater(alto, 400)

    def test_el_aviso_oficial_agranda_la_imagen(self):
        import struct

        from vigia.grafico import dibujar_mapa

        serie = self._serie()
        ev = evaluar_serie(serie, cfg())
        sin = dibujar_mapa(cfg(), T0, serie, ev, Nivel.NARANJA)
        con = dibujar_mapa(
            cfg(), T0, serie, ev, Nivel.NARANJA, "Tormenta fuerte en aguas de Ibiza."
        )
        self.assertGreater(
            struct.unpack(">II", con[16:24])[1], struct.unpack(">II", sin[16:24])[1]
        )

    def test_aguanta_una_serie_sin_datos(self):
        """Si las fuentes vienen vacías, el mapa no debe reventar el aviso."""
        from vigia.grafico import dibujar_mapa

        vacia = [Consenso(instante=T0)]
        png = dibujar_mapa(cfg(), T0, vacia, evaluar_serie(vacia, cfg()), Nivel.VERDE)
        self.assertTrue(png.startswith(b"\x89PNG"))


class PruebaPieDeFoto(unittest.TestCase):
    def test_el_pie_cabe_en_el_limite_de_whatsapp(self):
        """WhatsApp corta los pies a 1024 caracteres; con boletín largo aprieta."""
        serie = [
            Consenso(
                instante=T0 + timedelta(hours=i),
                altura_ola_m=1.4,
                periodo_ola_s=4.0,
                racha_nudos=30,
                direccion_viento_grados=265.0,
                fuentes_ola=5,
            )
            for i in range(13)
        ]
        respuestas = [
            RespuestaFuente(nombre="AEMET", boletin="Palabra " * 200,
                            aviso_oficial="Temporal fuerte en aguas de Ibiza."),
            RespuestaFuente(nombre="Open-Meteo olas (5 modelos)", lecturas=[]),
        ]
        _, pie = componer(
            cfg(), T0, serie, evaluar_serie(serie, cfg()), respuestas, para_imagen=True
        )
        self.assertLessEqual(len(pie), 1024)

    def test_la_version_completa_no_se_recorta(self):
        serie = [Consenso(instante=T0, altura_ola_m=0.3, racha_nudos=8,
                          direccion_viento_grados=90.0)]
        _, largo = componer(cfg(), T0, serie, evaluar_serie(serie, cfg()), [])
        _, breve = componer(cfg(), T0, serie, evaluar_serie(serie, cfg()), [],
                            para_imagen=True)
        self.assertGreaterEqual(len(largo), len(breve))


class PruebaSecretos(unittest.TestCase):
    """Con el repositorio público, los registros los lee cualquiera."""

    def test_tapa_el_token_en_la_ruta_de_green_api(self):
        from vigia.secretos import limpiar

        # Valores inventados: en un repositorio público no se pone ni el
        # número de instancia real, aunque el secreto de verdad sea el token.
        fuga = ('{"path":"/waInstance999999999999/sendMessage/'
                'abc123def456ghi789jkl012mno345pqr678"}')
        salida = limpiar(fuga)
        self.assertNotIn("abc123def456ghi789jkl012mno345pqr678", salida)
        self.assertIn("oculto", salida)

    def test_tapa_los_jwt(self):
        from vigia.secretos import limpiar

        jwt = ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhbGd1aWVuQGVqZW1wbG8uY29t"
               "IiwiZXhwIjoxNzk1MDI4MTE3fQ.abcdefghijklmnopqrstuvwxyz123456")
        self.assertNotIn(jwt, limpiar(f"error: {jwt}"))

    def test_tapa_valores_del_entorno(self):
        import os

        from vigia.secretos import limpiar

        os.environ["STORMGLASS_KEY"] = "clave-secretisima-de-prueba"
        try:
            self.assertNotIn(
                "clave-secretisima-de-prueba",
                limpiar("fallo con clave-secretisima-de-prueba"),
            )
        finally:
            del os.environ["STORMGLASS_KEY"]


if __name__ == "__main__":
    unittest.main(verbosity=2)

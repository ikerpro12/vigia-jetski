# 🌊 Vigía Jetski — Cala Tarida

Aviso automático de oleaje y viento para una moto de agua fondeada a la
intemperie. Consulta **varias fuentes meteorológicas a la vez**, las cruza para
que ningún modelo se equivoque solo, y te manda un **WhatsApp con antelación**
cuando la mar va a ponerse fea, para que te dé tiempo a bajar a por ella.

```
🟠 *VIGÍA JETSKI · Cala Tarida (Ibiza)*
_10/08/2026 20:44 · nivel NARANJA_

*Ahora mismo*
• Olas: 0.4 m, periodo 6 s
• Viento: 12 kn, rachas 16 kn del O

*⚠️ Aviso NARANJA en 3 h 14 min* (00:00)
  – olas de 0.9 m
  – rachas de 22 nudos
  – viento de mar del O (entra directo en la cala)

*Qué hacer:* Tienes margen (en 3 h 14 min). Aprovecha para bajar a por la moto
o reforzar el amarre antes de que empeore.
```

---

## Por qué varias fuentes

Un solo modelo se equivoca, se cae o devuelve un dato absurdo. Aquí se
consultan **cinco fuentes en paralelo** y se combinan:

| Fuente | Qué aporta | Modelos | Clave |
|---|---|---|---|
| **Open-Meteo Marine** | Oleaje: ECMWF WAM, Météo-France, GFS-Wave, GWAM, EWAM | hasta 5 | No |
| **Open-Meteo Forecast** | Viento y rachas: ECMWF, GFS, ICON, Météo-France, UKMO | 5 | No |
| **MET Norway (yr.no)** | Viento y rachas, otra organización y otro servidor | 1 | No |
| **7Timer!** | Viento medio, tercera infraestructura independiente | 1 | No |
| **AEMET** | Boletín y **avisos oficiales** de aguas de Ibiza | — | Sí, gratis |
| **Stormglass** | Oleaje de 4 modelos más (NOAA, ECMWF, DWD…) | 4 | Sí, 10/día |

Sumando, en cada hora votan **más de diez modelos numéricos distintos**. Las
cuatro primeras filas **no requieren registro de ningún tipo**: si borras las
claves, el programa sigue funcionando con once modelos.

Pedir varios modelos a Open-Meteo en la misma llamada es lo que más
redundancia aporta por menos esfuerzo. Y no es teórico: el 10/08/2026, a la
misma hora y en el mismo punto, los cinco modelos de oleaje daban
**0,24 · 0,58 · 0,00 · 0,80 · 0,34 m**. Con una sola fuente te habría tocado
creerte cualquiera de esos números.

Los modelos cuya serie entera es 0 se descartan: significa que su malla coloca
Cala Tarida en tierra, no que la mar esté plana. Es justo lo que le pasa a
NCEP GFS-Wave aquí.

*Se han descartado a propósito dos fuentes:* **SOCIB** (el observatorio balear)
exige clave, y **Puertos del Estado**, que tendría datos reales de boya, no
publica ninguna API abierta: habría que rasparle la web, y eso es demasiado
frágil para algo de lo que depende tu moto.

La combinación no es una media ingenua:

- Con **3 o más valores** se usa la **mediana**, así un modelo roto que diga
  9 metros no arrastra el resultado.
- Con **1 o 2 valores** se usa el **máximo**, porque sin mayoría no hay forma
  de saber quién miente y más vale pecar de prudente.
- Si las fuentes **discrepan mucho** (más de 40 cm), se dice en el mensaje y el
  aviso no se rebaja.

---

## Qué tiene en cuenta además de la altura de la ola

Esto es lo que lo hace útil de verdad para Cala Tarida en concreto:

**Viento de mar.** La cala mira al oeste. Con viento del sector SO–NO el
oleaje entra de lleno y además empuja la moto contra la costa: es la situación
peligrosa, y **sube un nivel el aviso**. Con viento de levante la cala queda a
resguardo y la misma ola es mucho menos preocupante, así que **baja un nivel**.

**Periodo corto.** Un mar de viento picado (menos de 4 s entre olas) castiga
el amarre mucho más que un mar de fondo largo de la misma altura. También suma.

**Margen de tiempo.** No mira solo cómo está la mar ahora, sino las próximas
12 horas, y te dice **a qué hora** se cruza el umbral y **cuánto te queda**.
Eso es justamente el tiempo que tienes para bajar.

**Los avisos oficiales mandan sobre los modelos.** Si AEMET tiene un aviso
vigente que menciona Ibiza, el nivel sube a NARANJA como mínimo aunque los
modelos digan que la mar está plana. Esto no es teórico: el 10/08/2026, con
todos los modelos dando 0,3 m de ola y viento flojo, AEMET tenía declarado
*"alguna tormenta que puede ser fuerte hasta media noche"* en aguas de Ibiza.
Una turbonada así no la ve un modelo de oleaje, y es exactamente lo que puede
hundirte la moto. Un aviso que solo mencione Menorca no escala nada.

Niveles: 🟢 VERDE · 🟡 AMARILLO · 🟠 NARANJA · 🔴 ROJO (los mismos colores de AEMET).

---

## Prueba rápida (30 segundos, sin configurar nada)

Necesitas Python 3.11 o superior. Nada más: **no hay dependencias que instalar.**

```bash
python -m vigia --sin-enviar
```

Para ver cómo se vería un aviso de temporal de verdad sin esperar a que lo haya:

```bash
python -m vigia --simular --sin-enviar
```

Y para lanzar las pruebas:

```bash
python -m tests.test_vigia
```

---

## Configurar el WhatsApp al grupo

Aquí está el único punto peliagudo, y conviene que lo sepas antes de empezar:

> **Los grupos de WhatsApp no son fáciles de automatizar.** La API oficial de
> Meta sí permite grupos desde 2026, pero exige una *Official Business Account*
> verificada: papeleo desproporcionado para esto. Y **CallMeBot, que es el
> truco gratuito más conocido, solo envía a chats personales, no a grupos.**
>
> La opción realista para un grupo es **Green API**, que tiene plan gratuito
> para unos 3 chats y funciona vinculando tu WhatsApp por QR, igual que
> WhatsApp Web.

### Green API (grupo) — recomendado

1. Regístrate en [green-api.com](https://green-api.com) y crea una instancia
   (el plan *Developer* es gratis).
2. En el panel te dan **`idInstance`** y **`apiTokenInstance`**. Escanea el QR
   con el WhatsApp del móvil para vincularlo.
3. Saca el ID del grupo. Con la instancia ya vinculada y el grupo creado:

   ```bash
   curl "https://api.green-api.com/waInstance<TU_ID>/getChats/<TU_TOKEN>"
   ```

   Busca el que acabe en **`@g.us`**: algo como `34600111222-1581234048@g.us`.
   Ese es tu `GREEN_API_CHAT`.
4. Copia `.env.example` a `.env`, rellena los tres valores y comprueba:

   ```bash
   python -m vigia --probar
   ```

   Debería llegarte un mensaje de prueba al grupo.

### CallMeBot (chat personal) — respaldo

Se usa automáticamente si Green API no está configurado o falla. Solo llega a
tu chat personal, pero es gratis y se monta en dos minutos: añade
**+34 621 331 709** a contactos, mándale por WhatsApp
`I allow callmebot to send me messages` y te devuelve tu API key.

Tenerlo configurado **además** de Green API es buena idea: si la sesión de
Green API se desvincula, el aviso te sigue llegando a ti aunque no al grupo.

---

## El mapa

Cada aviso llega como **una imagen con el parte de pie de foto** — un solo
mensaje, no dos. El mapa contesta de un vistazo a la única pregunta que
importa de verdad: *¿el viento entra en mi cala o no?*

Va con estética de **carta náutica nocturna**, pensada para mirarse en el móvil
de noche, que es justo cuando uno se acuerda de que la moto sigue fondeada.

- **Ibiza de verdad**, no un dibujo: el contorno sale de OpenStreetMap,
  simplificado a ~130 m y guardado en [`vigia/grafico/costa.py`](vigia/grafico/costa.py).
  No se consulta nada en tiempo de ejecución.
- **Mar en degradado** con retícula de coordenadas y la costa perfilada con un
  halo, como en una carta de verdad.
- **Cuña sombreada** sobre el sector expuesto (SO-NO). Si el viento cae dentro,
  se tiñe del color del aviso y el rótulo dice `ENTRA EN LA CALA`; si no, en
  cian y `LA CALA ESTA A RESGUARDO`.
- **Líneas de corriente de viento**: trazos curvados que se afilan y se
  iluminan hacia la punta, en vez de flechas rígidas. Nunca sobre tierra.
- **Textura de olas** cuya densidad y amplitud crecen con la ola prevista, para
  que un mapa con temporal *se note* temporal aunque no leas ni un número.
- **Banda del aviso oficial de AEMET** justo bajo la cabecera. Es lo primero
  que se lee porque muchas veces es la razón entera del aviso: puede haber
  tormenta declarada con la mar completamente plana.
- **Curva de altura de ola** con relleno degradado, un punto por hora coloreado
  según su nivel y los **umbrales de aviso** marcados con su cifra al margen.

Todo el dibujo está hecho **a mano y sin dependencias**: no hay Pillow ni
matplotlib. [`lienzo.py`](vigia/grafico/lienzo.py) monta el PNG con `zlib` y
`struct` (polígonos por barrido, degradados fila a fila, halos por pasadas
superpuestas y supermuestreo x3 para suavizar) y
[`tipografia.py`](vigia/grafico/tipografia.py) lleva una fuente de mapa de bits
5x7 con negrita simulada. Son unos 4 segundos de CPU y ~50 KB por imagen, y
solo se dibuja cuando realmente se va a enviar.

Un detalle de por qué no hay transparencia real: mezclar píxel a píxel en
Python puro sobre un lienzo de seis millones de puntos sería lentísimo. En su
lugar, las formas translúcidas se pintan **línea a línea** calculando el color
ya mezclado con el degradado que tienen debajo (`poligono_por_franja`), que da
el mismo resultado y usa copias de bytes en bloque.

Para verlo sin mandar nada:

```bash
python -m vigia --guardar-mapa mapa.png
```

Si el envío de la imagen falla por lo que sea, el aviso **se manda igual en
texto**: el mapa nunca puede ser el motivo de que no te enteres.

---

## Cada cuánto mira la mar

| Situación | Ritmo |
|---|---|
| 🟢 Mar en calma | cada **15 min** |
| 🟡 Amarillo, la cosa se está armando | cada **10 min** |
| 🟠🔴 Naranja o rojo | cada **5 min** |

El cron de GitHub **tiene** que dispararse cada 5 minutos: un `*/15` jamás
podría avisarte cada 5 durante un temporal, porque no existe forma de que un
cron se acelere solo. Lo que hace el programa es **salirse de vacío** cuando
todavía no toca (`toca_comprobar` en [`vigia/estado.py`](vigia/estado.py)), así
que con la mar plana el ritmo real es de 15 minutos y solo se acelera cuando
hace falta. Esas pasadas en vacío no consultan ninguna API y duran un suspiro.

Dos salvaguardas para que el freno no te deje tirado: **nunca frena si toca
parte diario**, y **nunca frena si el último nivel conocido ya era peligroso**.

---

## Cuándo te escribe

**Cuando hay peligro** (nivel NARANJA o ROJO):

- El primer aviso sale **al instante**, sin esperar al siguiente ciclo.
- Después, **un único recordatorio** 15 minutos más tarde. Y ya: **tope de 2
  mensajes** por episodio. Un temporal que te suelta quince avisos acaba
  silenciado, y entonces no sirve de nada.
- **Salvo que empeore**: pasar de naranja a rojo rompe el tope y avisa igual,
  porque eso no es spam, es información nueva.
- Cuando pasa el temporal, un último mensaje de "ya está" y a dormir.

Así, un temporal de cuatro horas son **2 mensajes**, no veinte. Hay una prueba
que lo simula (`test_el_segundo_aviso_cierra_el_episodio`).

### Histéresis: por qué no se dice "ya pasó" a la primera

El nivel no baja de golpe: se queda bailando alrededor del umbral, sobre todo
cuando lo que manda es un aviso de AEMET que aparece y desaparece entre
boletines. La primera versión trataba **cada bajada como fin del temporal** y
**cada subida como uno nuevo**, así que el tope de 2 mensajes no servía de
nada. El 11/08/2026 eso produjo seis mensajes en una hora:

```
09:20 NARANJA · 09:31 VERDE · 09:36 NARANJA · 09:51 NARANJA · 09:56 VERDE · 10:11 NARANJA
```

Ahora, una vez abierto un episodio, hace falta **una hora entera por debajo
del umbral** (`CALMA_MINUTOS`) para darlo por cerrado. Si en mitad de esa
espera vuelve a subir, el reloj se reinicia y **no se manda nada**: se sigue
en el mismo episodio. Con esa misma secuencia real ahora salen **2 mensajes**,
y está fijado en `PruebaHisteresis.test_el_caso_real_del_11_de_agosto`.

Bajar a 🟡 amarillo tampoco cierra el episodio de golpe, por lo mismo.

**Con la mar tranquila recibes exactamente 3 mensajes al día**: los partes de
las **8:00, 14:00 y 23:00** (hora española), y nada más. Ni uno de relleno.
Se configuran en `HORAS_PARTE`. Si el cron se despista y el parte de las 8:00
sale a las 8:40, sigue contando como el de las 8 y no se duplica.

Que el nivel suba a 🟡 amarillo **no genera mensaje**: solo hace que se mire la
mar más a menudo, por si sigue empeorando. Se escribe a partir de 🟠 naranja
(`NIVEL_MINIMO_AVISO`).

**Cuota de Stormglass.** El plan gratuito da 10 peticiones al día y el
programa se queda en 9. Como se comprueba la mar cada 5-30 minutos, no se
puede llamar siempre, así que la cuota se reserva para lo que importa: los
tres partes diarios y las pasadas en las que la mar ya pinta mal. Con la mar
plana y las fuentes gratuitas de acuerdo, no se gasta. El contador se lee de
la propia respuesta de Stormglass, así que no se descuadra.

---

## Dónde alojarlo

### Opción recomendada: GitHub Actions en repositorio PÚBLICO (gratis, cada 15 min)

Los repositorios **públicos** tienen **minutos de Actions ilimitados**, así que
el cron sale gratis. Uno privado se comería los 2.000 min/mes gratuitos, y por
eso hay que ponerlo público.

> **Por qué 15 minutos y no 5.** Se probó con `*/5` y GitHub sencillamente no
> lo cumplía: el evento `schedule` es "cuando se pueda", y los cron muy
> frecuentes son los primeros que se aparcan cuando hay carga. A 15 minutos se
> respeta bastante mejor. Como además solo se mandan 2 avisos por episodio,
> mirar más a menudo no aportaba nada.
>
> Si quieres reacción de verdad al minuto, eso solo lo da un proceso encendido
> (`--bucle`), no un cron.

1. Sube el proyecto a un repositorio de GitHub **público**.
2. En *Settings → Secrets and variables → Actions*, añade los secretos (los
   valores están en tu `.env` local):
   `GREEN_API_URL`, `GREEN_API_INSTANCIA`, `GREEN_API_TOKEN`, `GREEN_API_CHAT`,
   `AEMET_KEY`, `STORMGLASS_KEY`, `CONTACTO` y, si los usas,
   `CALLMEBOT_TELEFONO` y `CALLMEBOT_KEY`.
3. Comprueba que `.env` **no** se ha subido (está en `.gitignore`).
4. Listo. En *Actions* puedes lanzarlo a mano con *Run workflow*.

> ✅ **El workflow comprueba los secretos antes de nada.** Si falta alguno, la
> ejecución **falla en rojo** y te dice cuál, en vez de terminar "correcta" sin
> haber mandado nada. Eso último es exactamente lo que despista: con la mar en
> calma y sin `AEMET_KEY`, callarse es el comportamiento correcto, así que no
> hay forma de distinguir "todo bien" de "mal configurado".
>
> Para probar de verdad, usa *Run workflow* **marcando `forzar`**: eso manda el
> parte pase lo que pase, así que si no llega el WhatsApp es que algo falla.

> 🔐 **Lo importante de tenerlo público: los registros los lee cualquiera.**
> Los *secrets* de GitHub siguen siendo secretos y no aparecen en el código,
> pero un mensaje de error sí puede filtrarlos. Green API, por ejemplo, mete
> el token **en la ruta de la URL**, así que un error suyo devuelve
> `{"path":"/waInstance.../sendMessage/<TU_TOKEN>"}`. Por eso **todo lo que
> imprime el programa pasa antes por [`vigia/secretos.py`](vigia/secretos.py)**,
> que sustituye tokens y claves por `«oculto»`. Si añades una fuente nueva con
> clave, mete su variable en `CLAVES_SENSIBLES`.

> ⏱️ **Los cron de GitHub se retrasan.** Con carga alta, `*/5` puede
> convertirse en 10-15 minutos reales. Para vigilancia de verdad al minuto,
> usa el modo bucle de abajo.

> 🔁 **Y se apagan solos.** GitHub desactiva los cron de un repo público tras
> **60 días sin actividad**, y las ejecuciones automáticas no cuentan. Por eso
> va incluido [`mantener-vivo.yml`](.github/workflows/mantener-vivo.yml), que
> hace un commit cada lunes. Aun así, échale un ojo a la pestaña *Actions* de
> vez en cuando.

### Si quieres reacción real al minuto: Fly.io, Railway o Raspberry Pi

Con el modo bucle, el propio programa ajusta cada cuánto mira: **30 min en
calma, 15 en amarillo, 5 en naranja o rojo**. No depende de ningún cron.

```bash
python -m vigia --bucle
```

Vienen hechos el [`Dockerfile`](Dockerfile) y el [`fly.toml`](fly.toml):

```bash
fly launch --no-deploy --copy-config
fly volumes create datos --size 1 --region mad
fly secrets set GREEN_API_URL=https://TUNUM.api.greenapi.com GREEN_API_INSTANCIA=... GREEN_API_TOKEN=... GREEN_API_CHAT=... AEMET_KEY=... STORMGLASS_KEY=...
fly deploy
```

Ojo con dos cosas: **monta el volumen** (si se pierde `estado.json` se repiten
partes y se olvida el tope de mensajes) y **no actives el apagado automático**,
porque esto no es una web que pueda dormirse esperando visitas.

En una Raspberry Pi es aún más simple y no dependes de nadie:

```bash
nohup python3 -m vigia --bucle >> vigia.log 2>&1 &
```

> ⚠️ **`GREEN_API_URL` es fácil de olvidar y rompe los envíos sin decir nada.**
> Cada instancia tiene su propia URL (la tuya es
> `https://TUNUM.api.greenapi.com`, con el número de tu instancia), no la
> genérica `api.green-api.com`.

---

## Ajustar los umbrales

Los valores por defecto están pensados para una moto fondeada sin nadie a
bordo, y son deliberadamente conservadores:

| Nivel | Ola | Rachas |
|---|---|---|
| 🟡 AMARILLO | 0,5 m | 18 kn |
| 🟠 NARANJA | 0,9 m | 25 kn |
| 🔴 ROJO | 1,5 m | 35 kn |

**Aún así, son un punto de partida, no un valor sagrado.** Lo que aguante tu
moto depende del amarre, del calado y de lo abrigado que esté tu punto
concreto de la cala. Déjalo correr unas semanas, compara los avisos con lo que
veas al bajar, y sube o baja los números en el `.env`.

Si te llegan demasiados avisos, sube `OLA_NARANJA` o pon `NIVEL_MINIMO_AVISO=3`
para que solo avise en rojo. Si quieres el parte todos los días aunque esté en
calma, pon `PARTE_DIARIO=true`.

---

## Si ninguna fuente responde

Te lo dice explícitamente. El silencio no significa que la mar esté bien, y
eso hay que saberlo. El programa sale con código 2 en ese caso, por si quieres
monitorizarlo.

---

## Estructura

```
vigia/
  __main__.py        punto de entrada y modos de ejecución
  config.py          configuración por variables de entorno
  modelo.py          estructuras de datos y niveles de aviso
  consenso.py        combina las fuentes (mediana / máximo)
  evaluacion.py      umbrales, viento de mar, cálculo del margen
  mensaje.py         redacción del WhatsApp en castellano
  estado.py          memoria entre ejecuciones (anti-spam)
  notificaciones.py  envío por Green API y CallMeBot
  fuentes/           una fuente por fichero, todas opcionales
tests/               18 pruebas, sin red
```

Añadir una fuente nueva es escribir una función `(Config) -> RespuestaFuente`
y meterla en la lista `FUENTES` de [`vigia/fuentes/__init__.py`](vigia/fuentes/__init__.py).

---

## Aviso importante

Esto es una **ayuda**, no una autoridad náutica. Los modelos meteorológicos
fallan, las APIs se caen y una previsión de oleaje en aguas costeras tiene
mucha incertidumbre: el oleaje real dentro de una cala depende de la batimetría
y de efectos locales que ningún modelo global de estos resuelve bien.

Para decisiones serias, contrasta siempre con el
[boletín marítimo oficial de AEMET](https://www.aemet.es/es/eltiempo/prediccion/maritima)
y con [Puertos del Estado](https://portus.puertos.es/), que tiene datos reales
de boya. Y si hay temporal anunciado, no esperes al WhatsApp: saca la moto.

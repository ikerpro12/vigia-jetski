# Imagen mínima: el programa no tiene dependencias, solo librería estándar.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    TZ=Europe/Madrid \
    FICHERO_ESTADO=/datos/estado.json

WORKDIR /app
COPY vigia/ ./vigia/

# El estado (episodios, partes enviados, cuota de Stormglass) vive en un
# volumen para que sobreviva a los reinicios.
RUN mkdir -p /datos
VOLUME ["/datos"]

# Modo bucle: el propio programa ajusta el intervalo según el peligro
# (30 min en calma, 15 en amarillo, 5 en naranja o rojo). Es la única forma
# realista de cumplir "cada 5 min cuando hay peligro" sin arruinarse en
# ejecuciones de cron.
CMD ["python", "-m", "vigia", "--bucle"]

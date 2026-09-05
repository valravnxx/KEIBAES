#!/usr/bin/env python3
"""
recolectar.py — baja lo nuevo y lo deja en datos/crudo.json

No traduce ni interpreta: solo recoge. Así, si algo falla, sabes si el
problema es de descarga o de proceso.

Uso:
    python scripts/recolectar.py                # normal
    python scripts/recolectar.py --debug        # además guarda el HTML crudo
    python scripts/recolectar.py --solo noticias
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from hashlib import sha1
from urllib.parse import urljoin
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
import fuentes as F

RAIZ = Path(__file__).parent.parent
DATOS = RAIZ / "datos"
DEBUG_DIR = DATOS / "debug"

DEBUG = False


def log(*a):
    print("·", *a, flush=True)


def bajar(url: str, nombre: str = "") -> BeautifulSoup | None:
    """Descarga una página. Devuelve None si falla, no revienta."""
    try:
        r = requests.get(url, headers={"User-Agent": F.UA,
                                       "Accept-Language": "en"},
                         timeout=F.TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        log(f"FALLO {url}: {e}")
        return None
    finally:
        time.sleep(F.ESPERA)

    if DEBUG:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        slug = nombre or sha1(url.encode()).hexdigest()[:10]
        (DEBUG_DIR / f"{slug}.html").write_text(r.text, encoding="utf-8")
        log(f"HTML guardado en datos/debug/{slug}.html")

    return BeautifulSoup(r.text, "html.parser")


def limpiar(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "")).strip()


def id_de(texto: str) -> str:
    return sha1(texto.encode("utf-8")).hexdigest()[:10]


# ----------------------------------------------------------------- noticias

def cuerpo_noticia(url: str) -> str:
    """
    Baja el artículo entero. Como esto es de uso personal y no se republica,
    interesa el texto completo y no un extracto: la app se lee como un diario,
    no como un agregador de titulares.
    """
    sopa = bajar(url)
    if not sopa:
        return ""
    def texto_de(nodo):
        if not nodo:
            return ""
        # Fuera lo que nunca es cuerpo del artículo.
        for basura in nodo.select("script, style, nav, aside, figcaption, .Caption"):
            basura.decompose()
        parrafos = [limpiar(x.get_text()) for x in nodo.find_all("p")]
        return "\n\n".join(x for x in parrafos if len(x) > 60)[:6000]

    mejor = texto_de(sopa.select_one(F.SEL_NOTICIAS.cuerpo_detalle))

    if len(mejor) < 250:
        # Plan B: el bloque con MÁS TEXTO en párrafos largos. Contar párrafos
        # no vale: una galería de fotos tiene muchos pies de foto cortos y
        # ganaba la partida al artículo de verdad.
        for bloque in sopa.find_all(["article", "div", "section"]):
            t = texto_de(bloque)
            if len(t) > len(mejor):
                mejor = t

    # Menos de 250 caracteres no es un artículo: son pies de foto o un teaser.
    # Mejor no guardar nada que guardar dos frases sueltas haciéndolas pasar
    # por la noticia entera.
    return mejor if len(mejor) >= 250 else ""


def recolectar_noticias(limite=40, con_cuerpo=True, max_cuerpos=15) -> list[dict]:
    sopa = bajar(F.NETKEIBA_NOTICIAS, "noticias")
    if not sopa:
        return []

    items = sopa.select(F.SEL_NOTICIAS.item)
    if not items:
        # Plan B: cualquier enlace a una ficha de noticia. Feo pero resistente.
        log("Los selectores no encontraron nada; usando plan B por URL")
        items = [a.parent for a in sopa.select('a[href*="news_detail"]')]

    salida, vistos = [], set()
    for it in items[:limite]:
        a = it.select_one('a[href*="news_detail"]') or it.select_one(F.SEL_NOTICIAS.enlace)
        if not a:
            continue
        href = a.get("href", "")
        if not href or href in vistos:
            continue
        vistos.add(href)

        if href.startswith("/"):
            href = "https://en.netkeiba.com" + href

        titular = limpiar(a.get_text()) or limpiar(it.get_text())[:120]
        if len(titular) < 12:
            continue

        nodo_fecha = it.select_one(F.SEL_NOTICIAS.fecha)
        fecha = limpiar(nodo_fecha.get_text()) if nodo_fecha else ""

        salida.append({
            "id": id_de(titular),
            "titular_en": titular,
            "fecha_texto": fecha,
            "url": href,
            "medio": "netkeiba",
        })

    # Solo se baja el artículo de lo que no se ha visto antes: si ya está en
    # web/datos.json, no se vuelve a pedir. Esto mantiene el número de
    # peticiones bajo aunque el listado devuelva siempre 40 titulares.
    if con_cuerpo:
        conocidos = set()
        prev = RAIZ / "web" / "datos.json"
        if prev.exists():
            try:
                conocidos = {n["id"] for n in
                             json.loads(prev.read_text(encoding="utf-8")).get("noticias", [])}
            except Exception:
                pass

        pendientes = [n for n in salida if n["id"] not in conocidos][:max_cuerpos]
        log(f"bajando el texto de {len(pendientes)} noticias nuevas")
        for n in pendientes:
            n["cuerpo_en"] = cuerpo_noticia(n["url"])

    log(f"noticias: {len(salida)}")
    return salida


# --------------------------------------------------------------- calendario

def recolectar_calendario(anio: int) -> list[dict]:
    """
    El calendario de la JRA es una rejilla semanal: cada fila de la tabla es
    una SEMANA entera con varias carreras dentro. Recorrer filas perdía casi
    todas las carreras y además mezclaba los grados (si en la semana había un
    G1, se etiquetaban todas como G1).

    Se recorren los enlaces, que es lo que de verdad representa una carrera.
    El texto del enlace ya trae nombre y grado: "Kisaragi Sho (G3)".
    Y la URL trae la fecha: .../2026/0208kisaragi.html
    """
    sopa = bajar(F.url_calendario(anio), f"calendario-{anio}")
    if not sopa:
        return []

    base = F.url_calendario(anio)
    carreras, vistos = [], set()

    for a in sopa.select(F.SEL_CALENDARIO.enlace_carrera):
        etiqueta = limpiar(a.get_text(" "))   # con espacio: sin él salía "Keisei HaiAutumn"
        if not etiqueta:
            continue

        url = urljoin(base, a.get("href", ""))

        # Grado: del propio nombre de la carrera, no de la fila.
        m_g = re.search(r"\((J?-?(?:G|Jpn)\s?[123])\)\s*$", etiqueta)
        if not m_g:
            m_g = re.search(r"\((J?-?(?:G|Jpn)\s?[123])\)", etiqueta)
        if not m_g:
            continue
        grado = m_g.group(1).replace(" ", "")

        # Nombre sin el grado pegado al final.
        nombre = limpiar(etiqueta[:m_g.start()] or etiqueta)
        nombre = re.sub(r"[\s,;·-]+$", "", nombre)
        if not nombre:
            continue

        # Fecha: los 4 dígitos del nombre del fichero son MMDD.
        m_f = re.search(r"/(\d{2})(\d{2})[a-z0-9_-]*\.html", url)
        if not m_f:
            continue
        fecha = f"{anio}-{m_f.group(1)}-{m_f.group(2)}"

        # El identificador sale del nombre del fichero de la URL (0927sprinters),
        # que es estable. Si saliera del nombre de la carrera, cualquier
        # arreglo en el texto crearía una carrera "nueva" y quedaría la vieja
        # de zombi para siempre.
        slug = re.sub(r"\.html?$", "", url.rsplit("/", 1)[-1]).lower()
        if not slug:
            continue
        if slug in vistos:
            continue
        vistos.add(slug)

        carreras.append({
            "id": id_de(f"{anio}-{slug}"),
            "slug": slug,
            "nombre": nombre,
            "grado": grado,
            "fecha": fecha,
            "url": url,
            "anio": anio,
        })

    carreras.sort(key=lambda c: c["fecha"])
    grados = {}
    for c in carreras:
        grados[c["grado"]] = grados.get(c["grado"], 0) + 1
    log(f"carreras del calendario {anio}: {len(carreras)} — {grados}")
    return carreras


def detalle_carrera(url: str) -> dict:
    """
    Abre la ficha de una carrera graduada y saca lo que el calendario no da:
    hipódromo, distancia, superficie, premio y el ganador del año pasado.

    Se lee por patrones de texto, no por selectores: si rediseñan la página
    pero el contenido sigue diciendo "1200m, Turf", esto sigue funcionando.
    """
    sopa = bajar(url)
    if not sopa:
        return {}

    txt = limpiar(sopa.get_text(" "))
    d = {}

    m = re.search(F.RE_DISTANCIA, txt, re.I)
    if m:
        d["distancia"] = int(m.group(1))
        d["superficie"] = "cesped" if m.group(2).lower() == "turf" else "arena"

    arriba = txt.upper()
    for pista in F.PISTAS:
        if pista in arriba:
            d["hipodromo"] = pista.capitalize()
            break

    m = re.search(F.RE_SENTIDO, txt, re.I)
    if m:
        d["sentido"] = "derechas" if m.group(1).lower() == "right" else "izquierdas"

    m = re.search(F.RE_EDADES, txt, re.I)
    if m:
        d["edades"] = (m.group(1) + " años en adelante") if m.group(1) else (m.group(2) + " años")

    premios = re.findall(F.RE_PREMIO, txt)
    if premios:
        d["premio"] = "¥" + premios[0]

    # Los ganadores se buscan trozo a trozo, no sobre todo el texto junto:
    # sobre el texto entero la expresión se comía lo que venía detrás y
    # salían cosas como "Lugal Maximum number of Starter".
    ganadores = []
    for trozo in sopa.find_all(string=re.compile(r"Winner\s*:")):
        m = re.search(F.RE_GANADOR, limpiar(str(trozo)))
        if not m:
            continue
        anio, nombre = m.group(1), limpiar(m.group(2))
        if nombre and [anio, nombre] not in ganadores:
            ganadores.append([anio, nombre])
    if ganadores:
        d.setdefault("ficha", {})["ganadores"] = ganadores[:8]

    return d


def completar_fichas(carreras: list[dict], maximo=60) -> int:
    """
    Solo abre las fichas que faltan, y empieza por las carreras más cercanas
    en el tiempo. Así el primer día se rellenan las que importan y el resto
    va cayendo en días sucesivos, sin castigar a la web de la JRA.
    """
    hechas = {}
    prev = RAIZ / "web" / "datos.json"
    if prev.exists():
        try:
            for c in json.loads(prev.read_text(encoding="utf-8")).get("carreras", []):
                if c.get("distancia"):
                    hechas[c.get("id")] = c
        except Exception:
            pass

    hoy = datetime.now(timezone.utc).date().isoformat()
    pendientes = [c for c in carreras if c["id"] not in hechas and c.get("url")]
    pendientes.sort(key=lambda c: abs((datetime.fromisoformat(c["fecha"]).date()
                                       - datetime.fromisoformat(hoy).date()).days))

    log(f"fichas de carrera por abrir: {len(pendientes)} — abriendo {min(maximo, len(pendientes))}")
    n = 0
    for c in pendientes[:maximo]:
        extra = detalle_carrera(c["url"])
        if extra:
            c.update(extra)
            n += 1
        if c.get("grado") == "G1":
            vid = buscar_video(c["nombre"], c.get("anio", hoy[:4]), "G1")
            if vid:
                c["video_id"] = vid
    log(f"fichas completadas: {n}")
    return n


def buscar_video(nombre: str, anio: int, grado: str = "G1") -> str:
    """
    Devuelve el identificador del vídeo oficial, o "" si no se puede saber.

    Requiere YOUTUBE_API_KEY. Si no la hay, no pasa nada: la app enseña un
    botón de búsqueda que lleva al mismo sitio en un toque. La clave solo
    sirve para poder pintar la miniatura dentro de la app.

    Solo se busca para los G1: son los que el canal oficial sube uno a uno.
    """
    import os
    clave = os.environ.get("YOUTUBE_API_KEY", "")
    if not clave or grado != "G1":
        return ""
    try:
        r = requests.get("https://www.googleapis.com/youtube/v3/search",
                         params={"part": "snippet", "type": "video",
                                 "maxResults": 3, "key": clave,
                                 "q": F.consulta_video(nombre, anio, grado)},
                         timeout=F.TIMEOUT)
        r.raise_for_status()
        for item in r.json().get("items", []):
            canal = item["snippet"].get("channelTitle", "")
            titulo = item["snippet"].get("title", "")
            # Solo se acepta si viene del canal de la JRA y el título cuadra.
            if F.CANAL_ESPERADO.lower() in canal.lower() and str(anio) in titulo:
                return item["id"]["videoId"]
    except Exception as e:
        log(f"vídeo de {nombre}: {e}")
    return ""


# ------------------------------------------------- caballos y resultados

def _norm(t: str) -> str:
    """Para comparar nombres de carrera entre la JRA y netkeiba."""
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def tabla_por_cabeceras(sopa) -> list[dict]:
    """
    Lee la tabla más grande de la página usando los NOMBRES de las columnas.
    Fijar índices de columna a mano era pedir que se rompiera al primer
    rediseño; los títulos ("Horse Name", "Jockey") son mucho más estables.
    """
    mejor, mejor_filas = None, 0
    for tabla in sopa.find_all("table"):
        n = len(tabla.find_all("tr"))
        if n > mejor_filas:
            mejor, mejor_filas = tabla, n
    if mejor is None:
        return []

    filas = mejor.find_all("tr")
    mapa, inicio = {}, 0
    for i, fila in enumerate(filas[:4]):
        celdas = [limpiar(c.get_text()).lower() for c in fila.find_all(["th", "td"])]
        if not celdas:
            continue
        # Dos pasadas. Primero coincidencia EXACTA, y solo después parcial:
        # si no, "Horse Number" se llevaba la columna de "Horse Name" porque
        # contiene la palabra "horse".
        encontrado, usadas = {}, set()
        for exacta in (True, False):
            for campo, alias in F.COLUMNAS.items():
                if campo in encontrado:
                    continue
                for j, texto in enumerate(celdas):
                    if j in usadas:
                        continue
                    if any(a == texto for a in alias) if exacta else \
                       any(a in texto for a in alias):
                        encontrado[campo] = j
                        usadas.add(j)
                        break
        if "caballo" in encontrado:
            mapa, inicio = encontrado, i + 1
            break
    if not mapa:
        return []

    salida = []
    for fila in filas[inicio:]:
        celdas = [limpiar(c.get_text()) for c in fila.find_all("td")]
        if len(celdas) < 3:
            continue
        reg = {}
        for campo, j in mapa.items():
            if j < len(celdas) and celdas[j]:
                reg[campo] = celdas[j]
        if reg.get("caballo"):
            salida.append(reg)
    return salida


def race_ids_de_jornada(fecha_iso: str) -> dict:
    """{nombre normalizado: {race_id, hora}} para todas las carreras de un día."""
    sopa = bajar(F.url_jornada(fecha_iso.replace("-", "")))
    if not sopa:
        return {}
    salida = {}
    for a in sopa.select('a[href*="race_id="]'):
        m = re.search(r"race_id=(\d{10,14})", a.get("href", ""))
        if not m:
            continue
        texto = limpiar(a.get_text(" "))
        if len(texto) < 4:
            continue
        nombre = re.sub(r"\b(J?-?G[123]|Jpn[123])\b", "", texto).strip()
        hora = ""
        mh = re.search(r"\b([0-2]?\d:[0-5]\d)\b", texto)
        if mh:
            hora = mh.group(1)
            nombre = nombre.replace(hora, "").strip()
        clave = _norm(nombre)
        if clave and clave not in salida:
            salida[clave] = {"race_id": m.group(1), "hora_jst": hora}
    return salida


def precargar(carreras: list[dict]) -> None:
    """
    Copia sobre el calendario recién leído lo que ya se descargó otros días
    (race_id, clasificación, inscritos, ficha...). Sin esto, cada ejecución
    creería que no tiene nada y volvería a pedirlo todo desde cero.
    """
    prev = RAIZ / "web" / "datos.json"
    if not prev.exists():
        return
    try:
        antiguas = {c.get("id"): c for c in
                    json.loads(prev.read_text(encoding="utf-8")).get("carreras", [])}
    except Exception:
        return
    guardar = ("race_id", "hora_jst", "llegada", "participantes", "video_id",
               "distancia", "superficie", "hipodromo", "sentido", "edades",
               "premio", "ficha", "cronica", "destacado")
    n = 0
    for c in carreras:
        vieja = antiguas.get(c["id"])
        if not vieja:
            continue
        for campo in guardar:
            if vieja.get(campo) and not c.get(campo):
                c[campo] = vieja[campo]
        n += 1
    log(f"reaprovechado lo ya descargado de {n} carreras")


def resolver_race_ids(carreras: list[dict], max_jornadas=14) -> int:
    """
    El calendario de la JRA no da race_id y netkeiba lo necesita. Se resuelve
    por jornada: una sola petición por día sirve para todas las carreras
    graduadas de ese día.
    """
    pendientes = [c for c in carreras if not c.get("race_id") and c.get("fecha")]
    if not pendientes:
        return 0
    hoy = datetime.now(timezone.utc).date()
    fechas = sorted({c["fecha"] for c in pendientes},
                    key=lambda f: abs((datetime.fromisoformat(f).date() - hoy).days))

    n = 0
    for fecha in fechas[:max_jornadas]:
        jornada = race_ids_de_jornada(fecha)
        if not jornada:
            continue
        for c in pendientes:
            if c["fecha"] != fecha:
                continue
            clave = _norm(c["nombre"])
            dato = jornada.get(clave)
            if not dato:
                # A veces netkeiba abrevia; se busca por coincidencia parcial.
                for k, v in jornada.items():
                    if clave and (clave in k or k in clave):
                        dato = v
                        break
            if dato:
                c["race_id"] = dato["race_id"]
                if dato.get("hora_jst"):
                    c["hora_jst"] = dato["hora_jst"]
                n += 1
    log(f"race_id resueltos: {n} (en {min(len(fechas), max_jornadas)} jornadas)")
    return n


def recolectar_resultado(race_id: str) -> list[dict]:
    sopa = bajar(F.url_resultado(race_id), f"resultado-{race_id}")
    if not sopa:
        return []
    llegada = []
    for reg in tabla_por_cabeceras(sopa):
        pos = re.sub(r"\D", "", reg.get("puesto", ""))
        if not pos:
            continue
        llegada.append({
            "pos": int(pos),
            "caballo": reg.get("caballo", ""),
            "jockey": reg.get("jockey", ""),
            "tiempo": reg.get("tiempo", ""),
            "margen": reg.get("margen", ""),
            "odds": reg.get("odds", ""),
        })
    llegada.sort(key=lambda x: x["pos"])
    return llegada[:18]


def recolectar_participantes(race_id: str) -> list[dict]:
    sopa = bajar(F.url_inscripciones(race_id), f"inscritos-{race_id}")
    if not sopa:
        return []
    fuera = []
    for reg in tabla_por_cabeceras(sopa):
        fuera.append({
            "caballo": reg.get("caballo", ""),
            "jockey": reg.get("jockey", ""),
            "entrenador": reg.get("entrenador", ""),
            "peso": reg.get("peso", ""),
            "sexo_edad": reg.get("sexo_edad", ""),
            "odds": reg.get("odds", ""),
        })
    return fuera[:20]


def completar_resultados(carreras: list[dict], maximo=12) -> int:
    """Clasificaciones de lo ya corrido, empezando por lo más reciente."""
    hoy = datetime.now(timezone.utc).date()
    pendientes = [c for c in carreras
                  if c.get("race_id") and not c.get("llegada")
                  and c.get("fecha")
                  and datetime.fromisoformat(c["fecha"]).date() < hoy]
    pendientes.sort(key=lambda c: c["fecha"], reverse=True)
    n = 0
    for c in pendientes[:maximo]:
        llegada = recolectar_resultado(c["race_id"])
        if llegada:
            c["llegada"] = llegada
            n += 1
    log(f"clasificaciones nuevas: {n} (quedaban {len(pendientes)})")
    return n


def completar_participantes(carreras: list[dict], dias=12, maximo=8) -> int:
    """Inscritos de lo que está a punto de correrse. Antes de eso no existen."""
    hoy = datetime.now(timezone.utc).date()
    proximas = []
    for c in carreras:
        if not c.get("race_id") or not c.get("fecha") or c.get("llegada"):
            continue
        d = (datetime.fromisoformat(c["fecha"]).date() - hoy).days
        if 0 <= d <= dias:
            proximas.append((d, c))
    proximas.sort(key=lambda x: x[0])
    n = 0
    for _, c in proximas[:maximo]:
        gente = recolectar_participantes(c["race_id"])
        if gente:
            c["participantes"] = gente
            n += 1
    log(f"cuadros de inscritos: {n}")
    return n


# -------------------------------------------------------------------- main

def main():
    global DEBUG
    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", action="store_true",
                    help="guarda el HTML descargado para ajustar selectores")
    ap.add_argument("--solo", choices=["noticias", "calendario", "resultados"])
    ap.add_argument("--race-id", action="append", default=[],
                    help="resultado concreto a bajar (repetible)")
    args = ap.parse_args()
    DEBUG = args.debug

    DATOS.mkdir(parents=True, exist_ok=True)
    anio = datetime.now(timezone.utc).year

    crudo = {"generado": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    if args.solo in (None, "noticias"):
        crudo["noticias"] = recolectar_noticias()
    if args.solo in (None, "calendario"):
        cal = recolectar_calendario(anio)
        precargar(cal)
        completar_fichas(cal)
        resolver_race_ids(cal)
        completar_participantes(cal)
        completar_resultados(cal)
        crudo["calendario"] = cal
    if args.solo == "resultados" and args.race_id:
        crudo["resultados"] = [{"race_id": x, "llegada": recolectar_resultado(x)}
                               for x in args.race_id]

    destino = DATOS / "crudo.json"
    destino.write_text(json.dumps(crudo, ensure_ascii=False, indent=1),
                       encoding="utf-8")
    log(f"escrito {destino}")

    # Si no se ha recogido NADA, salir con error para que GitHub avise por correo.
    # Es preferible enterarse tú a publicar un boletín vacío.
    total = sum(len(v) for v in crudo.values() if isinstance(v, list))
    if total == 0:
        log("NO SE HA RECOGIDO NADA — probablemente han cambiado los selectores")
        sys.exit(1)


if __name__ == "__main__":
    main()

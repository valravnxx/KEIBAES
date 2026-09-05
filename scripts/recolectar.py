#!/usr/bin/env python3
"""
recolectar.py — baja lo nuevo y lo deja en datos/crudo.json

No traduce ni interpreta: solo recoge. Así, si algo falla, sabes si el
problema es de descarga o de proceso.

Uso:
    python scripts/recolectar.py                # todo
    python scripts/recolectar.py --debug        # además guarda el HTML crudo
    python scripts/recolectar.py --solo noticias
    python scripts/recolectar.py --rapido       # topes altos: para la puesta a punto
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta, date
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

# Cuenta de lo recogido por fuente. Es lo que permite avisar de que las
# noticias llevan días muertas aunque el calendario funcione: mirar solo el
# total escondía averías durante semanas.
SALUD = {}


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


def datos_previos() -> dict:
    p = RAIZ / "web" / "datos.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# ================================================================ noticias

MESES_EN = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def fecha_noticia(texto: str) -> str:
    """
    netkeiba mezcla formatos: "4 hrs", "35 min", "05 Sep 2026 01:53".
    Se normaliza todo a ISO para poder ordenar de verdad; con el texto
    original, "4 hrs" se ordenaba antes que cualquier fecha con número.
    """
    t = limpiar(texto)
    ahora = datetime.now(timezone.utc)

    m = re.search(r"(\d+)\s*(min|hr|hour|day)", t, re.I)
    if m:
        n, unidad = int(m.group(1)), m.group(2).lower()
        delta = (timedelta(minutes=n) if unidad == "min"
                 else timedelta(days=n) if unidad == "day"
                 else timedelta(hours=n))
        return (ahora - delta).strftime("%Y-%m-%d %H:%M")

    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{4})(?:\s+(\d{1,2}):(\d{2}))?", t)
    if m:
        mes = MESES_EN.get(m.group(2).lower())
        if mes:
            return (f"{m.group(3)}-{mes:02d}-{int(m.group(1)):02d} "
                    f"{int(m.group(4) or 0):02d}:{int(m.group(5) or 0):02d}")

    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", t)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d} 00:00"

    return ahora.strftime("%Y-%m-%d %H:%M")


def cuerpo_noticia(url: str) -> str:
    """
    Baja el artículo entero.

    La versión anterior solo miraba dentro de etiquetas <p>. netkeiba no
    siempre las usa —a veces el artículo es un bloque de texto con saltos—,
    así que devolvía vacío y la noticia se descartaba entera. Ahora prueba
    primero con párrafos y, si no hay, parte el texto por saltos de línea.
    """
    sopa = bajar(url)
    if not sopa:
        return ""

    for basura in sopa.select("script, style, nav, aside, header, footer, "
                              "figcaption, .Caption, .Banner, .Ad"):
        basura.decompose()

    def texto_de(nodo) -> str:
        if not nodo:
            return ""
        parrafos = [limpiar(x.get_text(" ")) for x in nodo.find_all("p")]
        parrafos = [x for x in parrafos if len(x) > 60]
        if parrafos:
            return "\n\n".join(parrafos)[:8000]
        # Sin <p>: se parte el texto por saltos y se descarta lo corto,
        # que es lo que separa el artículo de los menús y los pies de foto.
        trozos = [limpiar(x) for x in nodo.get_text("\n").split("\n")]
        return "\n\n".join(x for x in trozos if len(x) > 80)[:8000]

    mejor = texto_de(sopa.select_one(F.SEL_NOTICIAS.cuerpo_detalle))
    if len(mejor) < 250:
        for bloque in sopa.find_all(["article", "div", "section", "td"]):
            t = texto_de(bloque)
            if len(t) > len(mejor):
                mejor = t

    return mejor if len(mejor) >= 250 else ""


def listar_noticias(url: str, etiqueta: str) -> list[dict]:
    sopa = bajar(url, etiqueta)
    if not sopa:
        return []

    salida, vistos = [], set()
    for a in sopa.select('a[href*="news_detail"]'):
        href = a.get("href", "")
        m = re.search(r"id=(\d+)", href)
        if not m or m.group(1) in vistos:
            continue
        vistos.add(m.group(1))

        titular = limpiar(a.get_text(" "))
        if len(titular) < 12:
            continue

        # La fecha suele estar junto al enlace, no dentro.
        contexto = a.parent.get_text(" ") if a.parent else ""
        salida.append({
            "id": "n" + m.group(1),
            "titular_en": titular,
            "fecha_texto": fecha_noticia(contexto),
            "url": urljoin(url, href),
            "medio": "netkeiba",
            "categoria": etiqueta,
        })
    return salida


def recolectar_noticias(max_cuerpos=14, categorias=True) -> list[dict]:
    """
    Portada + las cinco categorías. Antes solo se leía la portada, así que
    los interruptores de Internacional, Cría y Jockeys de los ajustes no
    hacían absolutamente nada.
    """
    todas, vistos = [], set()

    for n in listar_noticias(F.NETKEIBA_NOTICIAS, "jra"):
        if n["id"] not in vistos:
            vistos.add(n["id"])
            todas.append(n)

    if categorias:
        for num, etiqueta in F.NETKEIBA_CATEGORIAS.items():
            for n in listar_noticias(F.url_categoria(num), etiqueta):
                if n["id"] not in vistos:
                    vistos.add(n["id"])
                    todas.append(n)

    conocidas = {n.get("id") for n in datos_previos().get("noticias", [])}
    pendientes = [n for n in todas if n["id"] not in conocidas]
    pendientes.sort(key=lambda n: n["fecha_texto"], reverse=True)
    pendientes = pendientes[:max_cuerpos]

    log(f"noticias en los listados: {len(todas)} · nuevas por leer: {len(pendientes)}")
    con_texto = 0
    for n in pendientes:
        n["cuerpo_en"] = cuerpo_noticia(n["url"])
        if n["cuerpo_en"]:
            con_texto += 1
    log(f"artículos con texto: {con_texto} de {len(pendientes)}")

    SALUD["noticias_listadas"] = len(todas)
    SALUD["noticias_con_texto"] = con_texto
    return todas


# ============================================================== calendario

def recolectar_calendario(anio: int) -> list[dict]:
    """
    El calendario de la JRA es una rejilla semanal: cada fila de la tabla es
    una SEMANA entera con varias carreras dentro. Se recorren los enlaces,
    que es lo que de verdad representa una carrera. El texto del enlace trae
    nombre y grado; la URL trae la fecha.
    """
    sopa = bajar(F.url_calendario(anio), f"calendario-{anio}")
    if not sopa:
        return []

    base = F.url_calendario(anio)
    carreras, vistos = [], set()

    for a in sopa.select(F.SEL_CALENDARIO.enlace_carrera):
        etiqueta = limpiar(a.get_text(" "))
        if not etiqueta:
            continue
        url = urljoin(base, a.get("href", ""))

        m_g = (re.search(r"\((J?-?(?:G|Jpn)\s?[123])\)\s*$", etiqueta)
               or re.search(r"\((J?-?(?:G|Jpn)\s?[123])\)", etiqueta))
        if not m_g:
            continue
        grado = m_g.group(1).replace(" ", "")

        nombre = re.sub(r"[\s,;·-]+$", "", limpiar(etiqueta[:m_g.start()] or etiqueta))
        if not nombre:
            continue

        m_f = re.search(r"/(\d{2})(\d{2})[a-z0-9_-]*\.html", url)
        if not m_f:
            continue
        fecha = f"{anio}-{m_f.group(1)}-{m_f.group(2)}"

        # El identificador sale del nombre del fichero (0927sprinters), que es
        # estable. Si saliera del nombre de la carrera, cualquier arreglo en el
        # texto crearía una carrera "nueva" y la vieja quedaría de zombi.
        slug = re.sub(r"\.html?$", "", url.rsplit("/", 1)[-1]).lower()
        if not slug or slug in vistos:
            continue
        vistos.add(slug)

        carreras.append({"id": id_de(f"{anio}-{slug}"), "slug": slug,
                         "nombre": nombre, "grado": grado, "fecha": fecha,
                         "url": url, "anio": anio})

    carreras.sort(key=lambda c: c["fecha"])
    reparto = {}
    for c in carreras:
        reparto[c["grado"]] = reparto.get(c["grado"], 0) + 1
    log(f"calendario {anio}: {len(carreras)} carreras — {reparto}")
    return carreras


def detalle_carrera(url: str) -> dict:
    """
    Abre la ficha de una carrera y saca lo que el calendario no da. Se lee
    por patrones de texto, no por selectores: si rediseñan la página pero
    sigue diciendo "1200m, Turf", esto sigue funcionando.
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
    hoy = date.today()
    pendientes = [c for c in carreras if not c.get("distancia") and c.get("url")]
    pendientes.sort(key=lambda c: abs((date.fromisoformat(c["fecha"]) - hoy).days))
    log(f"fichas de carrera por abrir: {len(pendientes)} — abriendo {min(maximo, len(pendientes))}")
    n = 0
    for c in pendientes[:maximo]:
        extra = detalle_carrera(c["url"])
        if extra:
            c.update(extra)
            n += 1
        if c.get("grado") == "G1" and not c.get("video_id"):
            vid = buscar_video(c["nombre"], c.get("anio", hoy.year), "G1")
            if vid:
                c["video_id"] = vid
    log(f"fichas completadas: {n}")
    return n


# =================================================================== vídeo

def buscar_video(nombre: str, anio, grado: str = "G1") -> str:
    """
    Identificador del vídeo oficial, o "" si no se puede saber. Requiere
    YOUTUBE_API_KEY; sin ella la app enseña un botón de búsqueda que lleva
    al mismo sitio en un toque.
    """
    clave = os.environ.get("YOUTUBE_API_KEY", "")
    if not clave or grado != "G1":
        return ""
    try:
        r = requests.get("https://www.googleapis.com/youtube/v3/search",
                         params={"part": "snippet", "type": "video", "maxResults": 3,
                                 "key": clave, "q": F.consulta_video(nombre, anio, grado)},
                         timeout=F.TIMEOUT)
        r.raise_for_status()
        for item in r.json().get("items", []):
            canal = item["snippet"].get("channelTitle", "")
            titulo = item["snippet"].get("title", "")
            if F.CANAL_ESPERADO.lower() in canal.lower() and str(anio) in titulo:
                return item["id"]["videoId"]
    except Exception as e:
        log(f"vídeo de {nombre}: {e}")
    return ""


# ================================================ tablas, cuadros y llegadas

def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def tabla_por_cabeceras(sopa) -> list[dict]:
    """
    Lee la tabla más grande usando los NOMBRES de las columnas. Fijar
    índices a mano era pedir que se rompiera al primer rediseño; los
    títulos ("Horse Name", "Jockey") son mucho más estables.

    Devuelve además el identificador del caballo si su nombre es un enlace
    a la ficha de netkeiba: sale gratis y evita tener que buscarlo luego.
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
        # Dos pasadas: primero coincidencia exacta y solo después parcial.
        # Si no, "Horse Number" se llevaba la columna de "Horse Name".
        encontrado, usadas = {}, set()
        for exacta in (True, False):
            for campo, alias in F.COLUMNAS.items():
                if campo in encontrado:
                    continue
                for j, texto in enumerate(celdas):
                    if j in usadas:
                        continue
                    if (any(a == texto for a in alias) if exacta
                            else any(a in texto for a in alias)):
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
        celdas = fila.find_all("td")
        if len(celdas) < 3:
            continue
        textos = [limpiar(c.get_text()) for c in celdas]
        reg = {}
        for campo, j in mapa.items():
            if j < len(textos) and textos[j]:
                reg[campo] = textos[j]
        if not reg.get("caballo"):
            continue
        j = mapa.get("caballo")
        if j is not None and j < len(celdas):
            a = celdas[j].find("a", href=re.compile(r"/db/horse/(\d+)"))
            if a:
                m = re.search(r"/db/horse/(\d+)", a.get("href", ""))
                if m:
                    reg["horse_id"] = m.group(1)
        salida.append(reg)
    return salida


def race_ids_de_jornada(fecha_iso: str) -> dict:
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


def resolver_race_ids(carreras: list[dict], max_jornadas=14) -> int:
    """El calendario de la JRA no da race_id y netkeiba lo necesita. Una
    petición por jornada sirve para todas las graduadas de ese día."""
    pendientes = [c for c in carreras if not c.get("race_id") and c.get("fecha")]
    if not pendientes:
        return 0
    hoy = date.today()
    fechas = sorted({c["fecha"] for c in pendientes},
                    key=lambda f: abs((date.fromisoformat(f) - hoy).days))

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
                for k, v in jornada.items():
                    if clave and (clave in k or k in clave):
                        dato = v
                        break
            if dato:
                c["race_id"] = dato["race_id"]
                if dato.get("hora_jst"):
                    c["hora_jst"] = dato["hora_jst"]
                n += 1
    log(f"race_id resueltos: {n} (mirando {min(len(fechas), max_jornadas)} jornadas)")
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
        llegada.append({"pos": int(pos), "caballo": reg.get("caballo", ""),
                        "jockey": reg.get("jockey", ""), "tiempo": reg.get("tiempo", ""),
                        "margen": reg.get("margen", ""), "odds": reg.get("odds", ""),
                        "horse_id": reg.get("horse_id", "")})
    llegada.sort(key=lambda x: x["pos"])
    return llegada[:18]


def recolectar_participantes(race_id: str) -> list[dict]:
    sopa = bajar(F.url_inscripciones(race_id), f"inscritos-{race_id}")
    if not sopa:
        return []
    return [{"caballo": r.get("caballo", ""), "jockey": r.get("jockey", ""),
             "entrenador": r.get("entrenador", ""), "peso": r.get("peso", ""),
             "sexo_edad": r.get("sexo_edad", ""), "odds": r.get("odds", ""),
             "horse_id": r.get("horse_id", "")}
            for r in tabla_por_cabeceras(sopa)][:20]


def completar_resultados(carreras: list[dict], maximo=12) -> int:
    hoy = date.today()
    pendientes = [c for c in carreras
                  if c.get("race_id") and not c.get("llegada") and c.get("fecha")
                  and date.fromisoformat(c["fecha"]) < hoy]
    pendientes.sort(key=lambda c: c["fecha"], reverse=True)
    n = 0
    for c in pendientes[:maximo]:
        llegada = recolectar_resultado(c["race_id"])
        if llegada:
            c["llegada"] = llegada
            n += 1
    log(f"clasificaciones nuevas: {n} (quedaban {len(pendientes)})")
    SALUD["clasificaciones_pendientes"] = max(0, len(pendientes) - n)
    return n


def completar_participantes(carreras: list[dict], dias=12, maximo=8) -> int:
    hoy = date.today()
    proximas = []
    for c in carreras:
        if not c.get("race_id") or not c.get("fecha") or c.get("llegada"):
            continue
        d = (date.fromisoformat(c["fecha"]) - hoy).days
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


# =============================================================== caballos

def ficha_caballo(horse_id: str) -> dict:
    """
    Pedigrí, entrenador y ganancias. En hípica japonesa el padre de un
    caballo es media conversación, así que esto es lo que convierte una
    ficha en algo que se lee.
    """
    sopa = bajar(F.url_caballo(horse_id))
    if not sopa:
        return {}
    txt = limpiar(sopa.get_text(" "))
    d = {"horse_id": horse_id}

    m = re.search(F.RE_PADRES, txt, re.I)
    if m:
        d["padre"] = limpiar(m.group(1))
        d["madre"] = limpiar(m.group(2))
    else:
        m = re.search(r"Sire\s*[:：]?\s*([A-Za-z][A-Za-z'’\. -]{2,28})", txt)
        if m:
            d["padre"] = limpiar(m.group(1))

    m = re.search(r"Trainer\s*[:：]?\s*([A-Za-z][A-Za-z'’\.\, -]{2,28})", txt)
    if m:
        d["entrenador"] = limpiar(m.group(1))

    m = re.search(r"(?:Total\s+)?(?:Earnings|Prize)\s*[:：]?\s*([\d,]{5,})", txt, re.I)
    if m:
        d["ganancias"] = m.group(1)

    m = re.search(r"\b(Colt|Filly|Horse|Mare|Gelding)\b\s*/?\s*(\d{1,2})?", txt)
    if m:
        sexos = {"colt": "potro", "filly": "potra", "horse": "macho",
                 "mare": "yegua", "gelding": "castrado"}
        d["sexo"] = sexos.get(m.group(1).lower(), "")
        if m.group(2):
            d["edad"] = int(m.group(2))
    return d


def completar_caballos(carreras: list[dict], maximo=25) -> int:
    """Abre la ficha de netkeiba de los caballos que aparecen en carreras
    recientes o próximas y de los que aún no sabemos nada."""
    previos = {c.get("nombre"): c for c in datos_previos().get("caballos", [])}
    ids, orden = {}, []
    for c in carreras:
        for x in (c.get("llegada", []) + c.get("participantes", [])):
            nombre, hid = x.get("caballo"), x.get("horse_id")
            if nombre and hid and nombre not in ids:
                ids[nombre] = hid
                orden.append(nombre)

    pendientes = [n for n in orden if not (previos.get(n) or {}).get("padre")]
    log(f"fichas de caballo por abrir: {len(pendientes)} — abriendo {min(maximo, len(pendientes))}")
    fichas = {}
    for nombre in pendientes[:maximo]:
        d = ficha_caballo(ids[nombre])
        if d and (d.get("padre") or d.get("entrenador")):
            fichas[nombre] = d
    log(f"fichas de caballo nuevas: {len(fichas)}")
    SALUD["caballos_pendientes"] = max(0, len(pendientes) - len(fichas))
    return fichas


# ============================================================ estadísticas

def recolectar_estadisticas(anio: int) -> dict:
    """Jockeys y sementales líderes. La pantalla existía desde el principio
    y nunca se había llenado."""
    salida = {}

    sopa = bajar(F.LEADING_JOCKEYS, "leading-jockeys")
    if sopa:
        jockeys = []
        for reg in tabla_por_cabeceras(sopa):
            nombre = reg.get("caballo") or reg.get("jockey")
            victorias = re.sub(r"\D", "", reg.get("puesto", "") or "")
            if nombre and victorias:
                jockeys.append({"nombre": nombre, "victorias": int(victorias)})
        if not jockeys:
            # Plan B: filas de tabla con nombre + número grande.
            for fila in sopa.select("table tr"):
                celdas = [limpiar(c.get_text()) for c in fila.find_all("td")]
                if len(celdas) < 3:
                    continue
                nombre = next((c for c in celdas if re.match(r"^[A-Za-z][A-Za-z'\. -]{3,}$", c)), "")
                nums = [int(c) for c in celdas if c.isdigit()]
                if nombre and nums:
                    jockeys.append({"nombre": nombre, "victorias": max(nums)})
        jockeys.sort(key=lambda j: j["victorias"], reverse=True)
        if jockeys:
            salida["jockeys"] = jockeys[:15]

    sopa = bajar(F.LEADING_SIRES, "leading-sires")
    if sopa:
        sementales = []
        for fila in sopa.select("table tr"):
            celdas = [limpiar(c.get_text()) for c in fila.find_all("td")]
            if len(celdas) < 3:
                continue
            nombre = next((c for c in celdas if re.match(r"^[A-Za-z][A-Za-z'\. -]{3,}$", c)), "")
            nums = [int(c) for c in celdas if c.isdigit()]
            if nombre and nums:
                sementales.append({"nombre": nombre, "victorias": max(nums)})
        sementales.sort(key=lambda s: s["victorias"], reverse=True)
        if sementales:
            salida["sementales"] = sementales[:15]

    log(f"estadísticas: {len(salida.get('jockeys', []))} jockeys, "
        f"{len(salida.get('sementales', []))} sementales")
    SALUD["estadisticas"] = len(salida)
    return salida


# ================================================================ precarga

def precargar(carreras: list[dict]) -> None:
    """Copia sobre el calendario recién leído lo que ya se descargó otros
    días. Sin esto, cada ejecución creería que no tiene nada."""
    antiguas = {c.get("id"): c for c in datos_previos().get("carreras", [])}
    guardar = ("race_id", "hora_jst", "llegada", "participantes", "video_id",
               "distancia", "superficie", "hipodromo", "sentido", "edades",
               "premio", "ficha", "cronica", "destacado", "titular_cronica")
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


# ==================================================================== main

def main():
    global DEBUG
    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--solo", choices=["noticias", "calendario", "estadisticas"])
    ap.add_argument("--rapido", action="store_true",
                    help="topes altos para la puesta a punto de los primeros días")
    args = ap.parse_args()
    DEBUG = args.debug

    DATOS.mkdir(parents=True, exist_ok=True)
    hoy = date.today()
    crudo = {"generado": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    topes = dict(cuerpos=14, fichas=60, jornadas=14, resultados=12,
                 inscritos=8, caballos=25)
    if args.rapido:
        topes = dict(cuerpos=25, fichas=140, jornadas=40, resultados=40,
                     inscritos=14, caballos=60)

    if args.solo in (None, "noticias"):
        crudo["noticias"] = recolectar_noticias(max_cuerpos=topes["cuerpos"])

    if args.solo in (None, "calendario"):
        # Diciembre mira ya el año siguiente: si no, el 1 de enero la app
        # amanece con el calendario vacío.
        anios = [hoy.year] + ([hoy.year + 1] if hoy.month == 12 else [])
        cal = []
        for anio in anios:
            cal += recolectar_calendario(anio)
        precargar(cal)
        completar_fichas(cal, topes["fichas"])
        resolver_race_ids(cal, topes["jornadas"])
        completar_participantes(cal, maximo=topes["inscritos"])
        completar_resultados(cal, topes["resultados"])
        crudo["calendario"] = cal
        crudo["fichas_caballo"] = completar_caballos(cal, topes["caballos"])
        SALUD["carreras"] = len(cal)

    if args.solo in (None, "estadisticas"):
        crudo["estadisticas"] = recolectar_estadisticas(hoy.year)

    (DATOS / "crudo.json").write_text(json.dumps(crudo, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    log(f"escrito datos/crudo.json — salud: {SALUD}")

    # Aviso POR FUENTE. Mirar solo el total escondía que las noticias
    # llevaran días sin entrar mientras el calendario funcionaba.
    fallos = []
    if args.solo in (None, "noticias") and not SALUD.get("noticias_listadas"):
        fallos.append("no se ha listado NINGUNA noticia")
    if args.solo in (None, "calendario") and not SALUD.get("carreras"):
        fallos.append("el calendario ha venido vacío")
    if fallos:
        for f in fallos:
            log("AVISO: " + f)
        sys.exit(1)


if __name__ == "__main__":
    main()

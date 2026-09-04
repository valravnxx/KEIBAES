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
    nodo = sopa.select_one(F.SEL_NOTICIAS.cuerpo_detalle)
    if not nodo:
        # Plan B: el bloque de párrafos más largo de la página.
        bloques = sopa.find_all(["div", "article", "section"])
        nodo = max(bloques, key=lambda b: len(b.find_all("p")), default=None)
    if not nodo:
        return ""
    parrafos = [limpiar(p.get_text()) for p in nodo.find_all("p")]
    return "\n\n".join(p for p in parrafos if len(p) > 40)[:6000]


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
    sopa = bajar(F.url_calendario(anio), f"calendario-{anio}")
    if not sopa:
        return []

    carreras = []
    for fila in sopa.select(F.SEL_CALENDARIO.fila):
        texto = limpiar(fila.get_text(" "))
        grado = next((g for g in F.GRADOS if re.search(rf"\b{re.escape(g)}\b", texto)), None)
        if not grado:
            continue

        a = fila.select_one(F.SEL_CALENDARIO.enlace_carrera)
        nombre = limpiar(a.get_text()) if a else ""
        if not nombre:
            continue

        url = a.get("href", "") if a else ""
        if url.startswith("/"):
            url = "https://japanracing.jp" + url

        # La URL de la ficha lleva la fecha: .../2026/0927sprinters-stakes.html
        m = re.search(r"/(\d{2})(\d{2})[a-z0-9-]*\.html", url)
        fecha = f"{anio}-{m.group(1)}-{m.group(2)}" if m else ""

        carreras.append({
            "id": id_de(f"{anio}{nombre}"),
            "nombre": nombre,
            "grado": grado,
            "fecha": fecha,
            "url": url,
            "anio": anio,
        })

    # Quitar duplicados manteniendo el orden
    unicas, vistos = [], set()
    for c in carreras:
        if c["nombre"] not in vistos:
            vistos.add(c["nombre"])
            unicas.append(c)

    log(f"carreras del calendario {anio}: {len(unicas)}")
    return unicas


# --------------------------------------------------------------- resultados

def recolectar_resultado(race_id: str) -> dict | None:
    sopa = bajar(F.url_resultado(race_id), f"resultado-{race_id}")
    if not sopa:
        return None

    llegada = []
    for fila in sopa.select(F.SEL_RESULTADO.fila):
        celdas = [limpiar(c.get_text()) for c in fila.select("td")]
        if len(celdas) < 6:
            continue
        if not celdas[F.SEL_RESULTADO.col_puesto].isdigit():
            continue

        def col(i):
            return celdas[i] if i < len(celdas) else ""

        llegada.append({
            "pos": int(celdas[F.SEL_RESULTADO.col_puesto]),
            "caballo": col(F.SEL_RESULTADO.col_caballo),
            "jockey": col(F.SEL_RESULTADO.col_jockey),
            "tiempo": col(F.SEL_RESULTADO.col_tiempo),
            "margen": col(F.SEL_RESULTADO.col_margen),
            "odds": col(F.SEL_RESULTADO.col_odds),
        })

    if not llegada:
        log(f"resultado {race_id}: tabla vacía — revisa los índices de columna")
        return None

    llegada.sort(key=lambda x: x["pos"])
    log(f"resultado {race_id}: {len(llegada)} clasificados, gana {llegada[0]['caballo']}")
    return {"race_id": race_id, "llegada": llegada[:18]}


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
        crudo["calendario"] = recolectar_calendario(anio)
    if args.solo in (None, "resultados") and args.race_id:
        crudo["resultados"] = [r for r in (recolectar_resultado(x)
                                           for x in args.race_id) if r]

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

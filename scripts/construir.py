#!/usr/bin/env python3
"""
construir.py — funde lo traducido con lo que ya había y escribe la web.

Salida:
  web/datos.json      lo que la app carga al abrirse (carreras, caballos,
                      jockeys, estadísticas y las noticias recientes)
  web/archivo.json    las noticias viejas, que la app pide solo si las buscas
  web/mis-carreras.ics  las próximas citas de tus caballos, ya generado

Reglas de fusión:
  · Las noticias se acumulan; las más nuevas primero.
  · Las carreras se actualizan por id sin perder lo ya descargado.
  · Caballos y jockeys se derivan solos de quién corre y quién gana.
"""

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

RAIZ = Path(__file__).parent.parent
DATOS = RAIZ / "datos"
WEB = RAIZ / "web"
SALIDA = WEB / "datos.json"
ARCHIVO = WEB / "archivo.json"
ICS = WEB / "mis-carreras.ics"

NOTICIAS_EN_PORTADA = 60      # lo que viaja en datos.json
NOTICIAS_ARCHIVO = 600        # el resto, en archivo.json
MIN_MENCIONES = 2


def leer(p: Path, por_defecto):
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return por_defecto


def dias_hasta(fecha: str):
    try:
        return (date.fromisoformat(fecha) - date.today()).days
    except (ValueError, TypeError):
        return None


def estado_carrera(c: dict) -> str:
    """lejana → se_acerca → cuadro_cerrado → con_mercado → corrida
       (y 'pasada': ya se corrió pero no tenemos su clasificación)"""
    if c.get("llegada"):
        return "corrida"
    d = dias_hasta(c.get("fecha", ""))
    if d is not None and d < 0:
        return "pasada"
    if c.get("participantes") and any(p.get("odds") for p in c["participantes"]):
        return "con_mercado"
    if c.get("participantes"):
        return "cuadro_cerrado"
    if c.get("suenan"):
        return "se_acerca"
    return "lejana"


def parece_cortado(t: str) -> bool:
    t = (t or "").strip()
    return bool(t) and t[-1] not in '.!?»"\')…'


def normaliza_jockey(n: str) -> str:
    """
    netkeiba escribe "Y.Take" y la JRA "Y. Take": sin unificarlos, el mismo
    jockey salía dos veces en la lista con una monta cada uno.
    """
    n = re.sub(r"\s+", " ", (n or "").strip())
    n = re.sub(r"\b([A-Z])\.\s+", r"\1.", n)      # "Y. Take" -> "Y.Take"
    n = re.sub(r"\b([A-Z])\s+(?=[A-Z][a-z])", r"\1.", n)  # "Y Take" -> "Y.Take"
    return n


def leer_seguidos() -> dict:
    d = leer(DATOS / "seguidos.json", {})
    return {"caballos": d.get("caballos", []), "jockeys": d.get("jockeys", [])}


# ------------------------------------------------------------- caballos

def derivar_caballos(carreras, noticias, fichas, seguidos) -> list[dict]:
    menciones = Counter()
    for n in noticias:
        for c in n.get("caballos", []):
            if c:
                menciones[c] += 1

    fichas_h = {}

    def ficha(nombre):
        return fichas_h.setdefault(nombre, {"nombre": nombre, "historial": [],
                                            "forma": [], "menciones": 0})

    # 1. Quien gana o coloca en una graduada entra siempre.
    for c in carreras:
        for pos in c.get("llegada", [])[:6]:
            nombre = pos.get("caballo")
            if not nombre:
                continue
            f = ficha(nombre)
            f["historial"].append({"carrera": c["id"], "fecha": c.get("fecha"),
                                   "pos": pos["pos"], "grado": c.get("grado"),
                                   "jockey": pos.get("jockey", "")})
            if pos.get("horse_id"):
                f["horse_id"] = pos["horse_id"]

    # 2. Quien está inscrito en algo que aún no se ha corrido.
    for c in carreras:
        for p in c.get("participantes", []):
            nombre = p.get("caballo")
            if not nombre:
                continue
            f = ficha(nombre)
            if p.get("jockey"):
                f.setdefault("jockey", p["jockey"])
            if p.get("sexo_edad"):
                f.setdefault("perfil", p["sexo_edad"])
            if p.get("horse_id"):
                f["horse_id"] = p["horse_id"]

    # 3. Quien se repite en las noticias, aunque no haya corrido.
    for nombre, n in menciones.items():
        if n >= MIN_MENCIONES or nombre in fichas_h:
            ficha(nombre)["menciones"] = n

    # 4. Los tuyos, pase lo que pase.
    for nombre in seguidos["caballos"]:
        ficha(nombre)

    # 5. Pedigrí y datos de la ficha de netkeiba.
    for nombre, extra in (fichas or {}).items():
        if nombre in fichas_h:
            fichas_h[nombre].update({k: v for k, v in extra.items() if v})

    # 6. Próxima cita.
    for c in sorted(carreras, key=lambda x: x.get("fecha") or "9999"):
        if estado_carrera(c) in ("corrida", "pasada"):
            continue
        nombres = ([p.get("caballo") for p in c.get("participantes", [])]
                   + c.get("suenan", []))
        for nombre in nombres:
            if nombre in fichas_h and "proxima" not in fichas_h[nombre]:
                fichas_h[nombre]["proxima"] = c["id"]

    salida = list(fichas_h.values())
    for f in salida:
        f["historial"].sort(key=lambda h: h.get("fecha") or "")
        f["forma"] = [h["pos"] for h in f["historial"]][-6:]
        f["victorias"] = sum(1 for h in f["historial"] if h["pos"] == 1)
        f["podios"] = sum(1 for h in f["historial"] if h["pos"] <= 3)
        f["g1"] = sum(1 for h in f["historial"] if h["pos"] == 1 and h.get("grado") == "G1")
        f["seguido"] = f["nombre"] in seguidos["caballos"]
    salida.sort(key=lambda f: (f["seguido"], f["g1"], f["victorias"],
                               f["podios"], f["menciones"]), reverse=True)
    return salida


# -------------------------------------------------------------- jockeys

def derivar_jockeys(carreras, seguidos) -> list[dict]:
    """
    Los jockeys estaban como texto muerto: aparecían veinte veces y no se
    podía tocar ninguno. Se construyen con lo que ya tenemos, sin pedir
    nada nuevo: quién monta qué y cómo acaba.
    """
    j = {}

    def ficha(nombre):
        return j.setdefault(nombre, {"nombre": nombre, "montas": 0, "victorias": 0,
                                     "podios": 0, "g1": 0, "caballos": [],
                                     "historial": [], "proximas": []})

    for c in carreras:
        for pos in c.get("llegada", []):
            nombre = normaliza_jockey(pos.get("jockey"))
            if not nombre or len(nombre) < 2:
                continue
            f = ficha(nombre)
            f["montas"] += 1
            if pos["pos"] == 1:
                f["victorias"] += 1
                if c.get("grado") == "G1":
                    f["g1"] += 1
            if pos["pos"] <= 3:
                f["podios"] += 1
            if pos.get("caballo") and pos["caballo"] not in f["caballos"]:
                f["caballos"].append(pos["caballo"])
            if pos["pos"] <= 3:
                f["historial"].append({"carrera": c["id"], "fecha": c.get("fecha"),
                                       "pos": pos["pos"], "caballo": pos.get("caballo", ""),
                                       "grado": c.get("grado")})
        for p in c.get("participantes", []):
            nombre = normaliza_jockey(p.get("jockey"))
            if not nombre or len(nombre) < 2:
                continue
            f = ficha(nombre)
            f["proximas"].append({"carrera": c["id"], "caballo": p.get("caballo", ""),
                                  "fecha": c.get("fecha")})
            if p.get("caballo") and p["caballo"] not in f["caballos"]:
                f["caballos"].append(p["caballo"])

    salida = []
    for f in j.values():
        if f["montas"] == 0 and not f["proximas"]:
            continue
        f["historial"].sort(key=lambda h: h.get("fecha") or "", reverse=True)
        f["historial"] = f["historial"][:20]
        f["caballos"] = f["caballos"][:12]
        f["pct"] = round(f["victorias"] / f["montas"] * 100, 1) if f["montas"] else 0
        # "Yutaka Take" en tu lista debe casar con "Y.Take" en las tablas.
        apellido = f["nombre"].split(".")[-1].lower()
        f["seguido"] = any(apellido and apellido in x.lower()
                           for x in seguidos["jockeys"])
        salida.append(f)
    salida.sort(key=lambda f: (f["seguido"], f["g1"], f["victorias"], f["montas"]),
                reverse=True)
    return salida


# ------------------------------------------------------------------ ics

def escribir_ics(carreras, caballos, seguidos):
    """
    El calendario ya generado. Antes había que pulsar un botón y solo metía
    la próxima carrera de cada caballo; ahora sale solo con todo lo que
    viene, y basta con abrir el archivo una vez desde el móvil.
    """
    porid = {c["id"]: c for c in carreras}
    interesa = defaultdict(list)

    for cab in caballos:
        if not cab.get("seguido"):
            continue
        for c in carreras:
            if estado_carrera(c) in ("corrida", "pasada"):
                continue
            en_cuadro = any(p.get("caballo") == cab["nombre"]
                            for p in c.get("participantes", []))
            if en_cuadro or c["id"] == cab.get("proxima"):
                interesa[c["id"]].append(cab["nombre"])

    def z(d):
        return d.strftime("%Y%m%dT%H%M%SZ")

    lineas = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//keiba-es//ES",
              "CALSCALE:GREGORIAN", "X-WR-CALNAME:Mis carreras (KEIBA ES)"]
    ahora = datetime.now(timezone.utc)
    for cid, nombres in interesa.items():
        c = porid.get(cid)
        if not c or not c.get("fecha"):
            continue
        hh, mm = (c.get("hora_jst") or "15:00").split(":")[:2]
        # JST es UTC+9 todo el año.
        ini = datetime(int(c["fecha"][:4]), int(c["fecha"][5:7]), int(c["fecha"][8:10]),
                       tzinfo=timezone.utc) + timedelta(hours=int(hh) - 9, minutes=int(mm))
        lineas += ["BEGIN:VEVENT", f"UID:{cid}@keiba-es", f"DTSTAMP:{z(ahora)}",
                   f"DTSTART:{z(ini)}", f"DTEND:{z(ini + timedelta(minutes=45))}",
                   f"SUMMARY:{c['nombre']} ({c.get('grado','')}) — {', '.join(nombres)}",
                   f"DESCRIPTION:{c.get('hipodromo','')} · {c.get('distancia','')} m",
                   "BEGIN:VALARM", "TRIGGER:-PT45M", "ACTION:DISPLAY",
                   f"DESCRIPTION:{', '.join(nombres)} corre en 45 minutos",
                   "END:VALARM", "END:VEVENT"]
    lineas.append("END:VCALENDAR")

    WEB.mkdir(parents=True, exist_ok=True)
    ICS.write_text("\r\n".join(lineas), encoding="utf-8")
    return len(interesa)


# ----------------------------------------------------------------- main

def main():
    nuevo = leer(DATOS / "traducido.json", {}) or leer(DATOS / "crudo.json", {})
    anterior = leer(SALIDA, {})
    archivo_previo = leer(ARCHIVO, {})
    seguidos = leer_seguidos()

    # --- noticias: portada + archivo, sin duplicar
    noticias = {n["id"]: n for n in
                (archivo_previo.get("noticias", []) + anterior.get("noticias", []))}
    entradas = 0
    for n in nuevo.get("noticias", []):
        if n.get("resumen"):
            if n["id"] not in noticias:
                entradas += 1
            n.pop("cuerpo_en", None)
            noticias[n["id"]] = n
    noticias = sorted(noticias.values(),
                      key=lambda n: n.get("fecha_texto", ""), reverse=True)

    # Limpieza de traducciones cortadas que ya estaban guardadas. Se marcan
    # para que el recolector vuelva a intentarlas; mientras tanto la noticia
    # se queda con su resumen, que sí está entero.
    cortadas = 0
    for n in noticias:
        if parece_cortado(n.get("texto")):
            n["texto"] = ""
            n["reintentar"] = True
            cortadas += 1
        elif n.get("texto") and n.get("reintentar"):
            n.pop("reintentar", None)
    if cortadas:
        print(f"· {cortadas} traducciones cortadas retiradas; se reintentarán")

    # --- carreras
    carreras = {c["id"]: c for c in anterior.get("carreras", [])}
    for c in nuevo.get("calendario", []):
        carreras.setdefault(c["id"], {}).update(c)

    frescas = {c["id"] for c in nuevo.get("calendario", [])}
    if len(frescas) > 30:
        antes = len(carreras)
        carreras = {k: c for k, c in carreras.items()
                    if k in frescas or c.get("llegada") or c.get("cronica")
                    or (c.get("ficha") or {}).get("que_es")}
        if antes != len(carreras):
            print(f"· limpiadas {antes - len(carreras)} carreras obsoletas")

    carreras = list(carreras.values())
    for c in carreras:
        c["dias"] = dias_hasta(c.get("fecha", ""))
        c["estado"] = estado_carrera(c)
    carreras.sort(key=lambda c: c.get("fecha") or "9999")

    caballos = derivar_caballos(carreras, noticias,
                                nuevo.get("fichas_caballo", {}), seguidos)
    jockeys = derivar_jockeys(carreras, seguidos)

    # Tus noticias primero.
    def mia(n):
        txt = (n.get("titular", "") + " " + n.get("texto", ""))
        return (any(x in n.get("caballos", []) for x in seguidos["caballos"])
                or any(x in txt for x in seguidos["jockeys"]))
    noticias.sort(key=lambda n: (mia(n), n.get("fecha_texto", "")), reverse=True)

    # Estadísticas: se conservan si esta vez no se han podido bajar. Antes
    # se perdían en la primera ejecución y la pantalla quedaba vacía.
    estadisticas = nuevo.get("estadisticas") or anterior.get("estadisticas") or {}
    estadisticas.setdefault("records", [
        {"que": "Yutaka Take · G1 ganados", "valor": 86},
        {"que": "Yutaka Take · Takarazuka Kinen", "valor": 6},
        {"que": "Caballos con doble Takarazuka", "valor": 3}])

    portada = noticias[:NOTICIAS_EN_PORTADA]
    resto = noticias[NOTICIAS_EN_PORTADA:NOTICIAS_EN_PORTADA + NOTICIAS_ARCHIVO]

    salida = {
        "version": 2,
        "actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "noticias": portada,
        "hay_archivo": len(resto),
        "carreras": carreras,
        "caballos": caballos,
        "jockeys": jockeys,
        "estadisticas": estadisticas,
        "seguidos": seguidos,
    }

    WEB.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")
    ARCHIVO.write_text(json.dumps({"noticias": resto}, ensure_ascii=False, indent=1),
                       encoding="utf-8")
    eventos = escribir_ics(carreras, caballos, seguidos)

    kb = SALIDA.stat().st_size / 1024
    con_llegada = sum(1 for c in carreras if c.get("llegada"))
    con_cronica = sum(1 for c in carreras if c.get("cronica"))
    print(f"· datos.json  {kb:.0f} KB — {len(portada)} noticias (+{entradas} nuevas), "
          f"{len(carreras)} carreras ({con_llegada} con clasificación, "
          f"{con_cronica} con crónica), {len(caballos)} caballos, {len(jockeys)} jockeys")
    print(f"· archivo.json {len(resto)} noticias · mis-carreras.ics {eventos} eventos")
    if kb > 1200:
        print("· AVISO: datos.json pasa de 1,2 MB. Toca bajar NOTICIAS_EN_PORTADA.")


if __name__ == "__main__":
    main()

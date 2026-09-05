#!/usr/bin/env python3
"""
construir.py — funde lo traducido con lo que ya había y escribe web/datos.json

Reglas de fusión:
  · Las noticias se acumulan (archivo), las más nuevas primero.
  · Las carreras se actualizan por id: una carrera futura pasa a corrida
    cuando aparece su resultado, sin perder la ficha de enciclopedia.
  · Los caballos se derivan solos: entra todo el que gane o coloque en una
    carrera graduada, o cuyo nombre se repita en las noticias.

El resultado es UN fichero. Toda la app lee de él.
"""

import json
from collections import Counter
from datetime import datetime, timezone, date
from pathlib import Path

RAIZ = Path(__file__).parent.parent
DATOS = RAIZ / "datos"
SALIDA = RAIZ / "web" / "datos.json"

MAX_NOTICIAS = 400          # el archivo se corta aquí; más no cabe en memoria
MIN_MENCIONES = 2           # menciones para que un caballo entre solo


def leer(p: Path, por_defecto):
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return por_defecto


def estado_carrera(c: dict) -> str:
    """lejana → se_acerca → cuadro_cerrado → con_mercado → corrida
       (y 'pasada': ya se corrió pero no tenemos su resultado)"""
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


def dias_hasta(fecha: str) -> int | None:
    try:
        d = date.fromisoformat(fecha)
    except (ValueError, TypeError):
        return None
    return (d - date.today()).days


def leer_seguidos() -> dict:
    """Tu lista, versionada en el repo. Es lo que hace que no haga falta
    ninguna cuenta: el fichero viaja contigo a cualquier dispositivo."""
    d = leer(DATOS / "seguidos.json", {})
    return {"caballos": d.get("caballos", []), "jockeys": d.get("jockeys", [])}


def derivar_caballos(carreras, noticias, seguidos_previos) -> list[dict]:
    menciones = Counter()
    for n in noticias:
        for c in n.get("caballos", []):
            if c:
                menciones[c] += 1

    fichas = {}

    # 1. Los que ganan o colocan en una carrera graduada entran siempre.
    for c in carreras:
        for pos in c.get("llegada", [])[:3]:
            nombre = pos.get("caballo")
            if not nombre:
                continue
            f = fichas.setdefault(nombre, {"nombre": nombre, "historial": [],
                                           "forma": [], "menciones": 0})
            f["historial"].append({"carrera": c["id"], "fecha": c.get("fecha"),
                                   "pos": pos["pos"], "grado": c.get("grado")})
            f["forma"].append(pos["pos"])

    # 2. Los que se repiten en las noticias, aunque no hayan corrido aún.
    for nombre, n in menciones.items():
        if n >= MIN_MENCIONES or nombre in fichas:
            f = fichas.setdefault(nombre, {"nombre": nombre, "historial": [],
                                           "forma": [], "menciones": 0})
            f["menciones"] = n

    # 3. Próxima cita: primera carrera futura donde se le espera.
    for c in carreras:
        if estado_carrera(c) == "corrida":
            continue
        for nombre in c.get("suenan", []) + [p.get("caballo") for p in c.get("participantes", [])]:
            if nombre in fichas and "proxima" not in fichas[nombre]:
                fichas[nombre]["proxima"] = c["id"]

    # Conservar lo que el usuario ya seguía aunque haya dejado de sonar
    for nombre in seguidos_previos:
        fichas.setdefault(nombre, {"nombre": nombre, "historial": [],
                                   "forma": [], "menciones": 0})

    salida = list(fichas.values())
    for f in salida:
        f["forma"] = f["forma"][-5:]
        f["victorias"] = sum(1 for h in f["historial"] if h["pos"] == 1)
        f["g1"] = sum(1 for h in f["historial"]
                      if h["pos"] == 1 and h.get("grado") == "G1")

    # Los más relevantes primero: G1 > victorias > menciones
    salida.sort(key=lambda f: (f["g1"], f["victorias"], f["menciones"]), reverse=True)
    return salida


def main():
    nuevo = leer(DATOS / "traducido.json", {})
    anterior = leer(SALIDA, {})

    # --- noticias: acumular sin duplicar
    noticias = {n["id"]: n for n in anterior.get("noticias", [])}
    for n in nuevo.get("noticias", []):
        if n.get("resumen"):           # solo las que se han podido redactar
            noticias[n["id"]] = n
    noticias = sorted(noticias.values(),
                      key=lambda n: n.get("fecha_texto", ""), reverse=True)[:MAX_NOTICIAS]

    # --- carreras: actualizar por id conservando la ficha de enciclopedia
    carreras = {c["id"]: c for c in anterior.get("carreras", [])}
    for c in nuevo.get("calendario", []):
        carreras.setdefault(c["id"], {}).update(c)
    for r in nuevo.get("resultados", []):
        for c in carreras.values():
            if c.get("race_id") == r["race_id"]:
                c.update(r)
                break

    carreras = list(carreras.values())
    for c in carreras:
        c["dias"] = dias_hasta(c.get("fecha", ""))
        c["estado"] = estado_carrera(c)
    carreras.sort(key=lambda c: c.get("fecha") or "9999")

    seguidos = leer_seguidos()
    caballos = derivar_caballos(carreras, noticias, seguidos["caballos"])
    for c in caballos:
        c["seguido"] = c["nombre"] in seguidos["caballos"]

    # Tus caballos primero, luego el resto por relevancia.
    caballos.sort(key=lambda c: (c.get("seguido", False), c["g1"],
                                 c["victorias"], c["menciones"]), reverse=True)

    # Y tus noticias primero también.
    def mia(n):
        txt = (n.get("titular", "") + " " + n.get("texto", ""))
        return (any(x in n.get("caballos", []) for x in seguidos["caballos"])
                or any(j in txt for j in seguidos["jockeys"]))
    noticias.sort(key=lambda n: (mia(n), n.get("fecha_texto", "")), reverse=True)

    salida = {
        "version": 1,
        "actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "noticias": noticias,
        "carreras": carreras,
        "caballos": caballos,
        "seguidos": seguidos,
    }

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(salida, ensure_ascii=False, indent=1),
                      encoding="utf-8")

    kb = SALIDA.stat().st_size / 1024
    print(f"· web/datos.json — {len(noticias)} noticias, {len(carreras)} carreras, "
          f"{len(caballos)} caballos, {kb:.0f} KB")
    if kb > 900:
        print("· AVISO: el fichero pasa de 900 KB. Toca partir el archivo por meses.")


if __name__ == "__main__":
    main()

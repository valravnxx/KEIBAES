#!/usr/bin/env python3
"""
traducir.py — convierte lo recogido en español con contexto.

No es un traductor: es un redactor. Traduce, resume y añade lo que un lector
español no puede saber. Esa tercera parte es la que hace que el resultado
parezca una publicación y no un volcado automático.

Primario  : Gemini (capa gratuita, sin tarjeta)
Reserva   : Groq (se activa sola si Gemini devuelve 429)
Caché     : por hash, en datos/cache_traduccion.json — no se paga dos veces
            por lo mismo, y las re-ejecuciones son instantáneas.

Variables de entorno:
    GEMINI_API_KEY   (obligatoria)
    GROQ_API_KEY     (opcional pero recomendada)
"""

import json
import os
import re
import sys
import time
from hashlib import sha1
from pathlib import Path

import requests

RAIZ = Path(__file__).parent.parent
DATOS = RAIZ / "datos"
CACHE = DATOS / "cache_traduccion.json"

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")

MODELO_GEMINI = "gemini-flash-lite-latest"
MODELO_GROQ = "openai/gpt-oss-120b"


SISTEMA = """Eres redactor de una publicación española sobre hípica japonesa.

Reglas invariables:
- Nombres de caballos, jockeys, entrenadores e hipódromos: SIN traducir.
- Nombres de carrera: en original, con una aclaración breve la primera vez
  que aparecen (ej. "Kikuka Sho, el St. Leger japonés").
- Si el texto da por sabido algo del calendario japonés o del sistema de
  clasificación, explícalo en media frase.
- Tono periodístico. Sin adjetivos de relleno ni entusiasmo impostado.
- NUNCA inventes datos que no estén en el original. Si algo no está, se omite.
- Español de España, sin anglicismos innecesarios."""


PROMPT_NOTICIA = """Traduce esta noticia al español.

Devuelve tres cosas:
- titular: el titular traducido, sin adornos añadidos.
- resumen: dos frases con lo esencial, para la portada.
- texto: la noticia COMPLETA traducida, respetando los párrafos del original
  (sepáralos con \n\n). Si el original da por sabido algo del calendario
  japonés o del sistema de clasificación, añade la aclaración entre guiones
  dentro de la frase. No resumas aquí: es la versión para leer entera.

TITULAR: {titular}

TEXTO ORIGINAL:
{cuerpo}

Devuelve SOLO un objeto JSON, sin ```:
{{"titular": "...", "resumen": "...", "texto": "...", "caballos": ["..."], "categoria": "jra|nar|internacional|cria|jockeys"}}"""


PROMPT_TROZO = """Continúa la traducción al español de esta MISMA noticia.

Es un fragmento intermedio: no lo resumas, no lo introduzcas y no lo cierres.
Tradúcelo entero y devuelve solo el texto, respetando los párrafos.

Estas son las últimas frases ya traducidas, para que enlaces bien:
«{cola}»

FRAGMENTO A TRADUCIR:
{cuerpo}

Devuelve SOLO un objeto JSON, sin ```:
{{"texto": "..."}}"""


PROMPT_CRONICA = """Escribe la crónica de esta carrera en español, en DOS párrafos.

Párrafo 1: qué pasó en la carrera (quién ganó, por cuánto, quién le siguió).
Párrafo 2: por qué importa. Aquí va el contexto que un lector español no tiene
—qué significa esa victoria, qué récord toca, qué lugar ocupa esa carrera en
el calendario japonés—. Este segundo párrafo es lo que diferencia una crónica
de un marcador: si no tienes datos para escribirlo, dilo con un párrafo corto
en vez de rellenar.

CARRERA: {nombre} ({grado}) · {fecha} · {hipodromo} · {distancia} m {superficie}
CONTEXTO DE LA PRUEBA: {contexto}
GANADORES DE AÑOS ANTERIORES: {ganadores}
ORDEN DE LLEGADA (puesto. caballo (jockey) tiempo margen cuota):
{llegada}

Devuelve SOLO un objeto JSON, sin ```:
{{"cronica": "párrafo 1\\n\\npárrafo 2", "destacado": "una frase de 12 palabras como mucho"}}"""


# ------------------------------------------------------------------ caché

def cargar_cache() -> dict:
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return {}


def guardar_cache(c: dict):
    DATOS.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")


def clave(prompt: str) -> str:
    return sha1((SISTEMA + prompt).encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------- proveedores

def pedir_gemini(prompt: str) -> str | None:
    if not GEMINI_KEY:
        return None
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{MODELO_GEMINI}:generateContent")
    cuerpo = {
        "system_instruction": {"parts": [{"text": SISTEMA}]},
        "contents": [{"parts": [{"text": prompt}]}],
        # 8192 en vez de 2400: con 2400, un artículo largo se quedaba sin
        # presupuesto a mitad de la traducción y la noticia terminaba
        # cortada, y encima en inglés.
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 8192},
    }
    try:
        r = requests.post(url, params={"key": GEMINI_KEY}, json=cuerpo, timeout=120)
        if r.status_code == 429:
            print("· Gemini: cuota agotada, paso a Groq")
            return None
        r.raise_for_status()
        cand = r.json()["candidates"][0]
        if cand.get("finishReason") == "MAX_TOKENS":
            # Se ha quedado sin sitio: lo que devuelva estará cortado.
            print("· Gemini: respuesta cortada por longitud")
            return None
        return cand["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"· Gemini falló: {e}")
        return None


def pedir_groq(prompt: str) -> str | None:
    if not GROQ_KEY:
        return None
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            json={"model": MODELO_GROQ,
                  "messages": [{"role": "system", "content": SISTEMA},
                               {"role": "user", "content": prompt}],
                  "temperature": 0.4, "max_tokens": 8000},
            timeout=120)
        r.raise_for_status()
        eleccion = r.json()["choices"][0]
        if eleccion.get("finish_reason") == "length":
            print("· Groq: respuesta cortada por longitud")
            return None
        return eleccion["message"]["content"]
    except Exception as e:
        print(f"· Groq falló: {e}")
        return None
    finally:
        time.sleep(2.5)  # los 8k TPM de Groq no perdonan las ráfagas


TROZO = 1500   # caracteres de original por llamada


def partir(texto: str, tam=TROZO) -> list[str]:
    """
    Parte el artículo por párrafos sin cortar ninguno.

    Traducir un artículo largo de una sentada era lo que lo dejaba a medias:
    por muy alto que pongas el tope, siempre habrá uno más largo. Troceando,
    ninguna llamada se acerca al límite y el texto llega entero.
    """
    parrafos = [p for p in texto.split("\n\n") if p.strip()]

    # Un párrafo más largo que el trozo se parte por frases. Sin esto, un
    # artículo que viniera en un solo bloque no tenía por dónde cortarse y
    # el reintento no podía hacer nada.
    sueltos = []
    for par in parrafos:
        if len(par) <= tam:
            sueltos.append(par)
            continue
        frases = re.split(r"(?<=[\.\?!])\s+", par)
        acum = ""
        for fr in frases:
            if acum and len(acum) + len(fr) > tam:
                sueltos.append(acum)
                acum = fr
            else:
                acum = (acum + " " + fr).strip() if acum else fr
        if acum:
            sueltos.append(acum)

    trozos, actual = [], ""
    for par in sueltos:
        if actual and len(actual) + len(par) > tam:
            trozos.append(actual)
            actual = par
        else:
            actual = (actual + "\n\n" + par) if actual else par
    if actual:
        trozos.append(actual)
    return trozos or [texto]


def parece_cortado(t: str) -> bool:
    """
    Un texto que termina sin puntuación de cierre casi siempre es una
    respuesta truncada. Mejor quedarse con el resumen que publicar media
    frase —y encima a medio traducir, como pasaba.
    """
    t = (t or "").strip()
    if not t:
        return False
    if t[-1] in '.!?»"\')…':
        return False
    return True


def extraer_json(texto: str) -> dict | None:
    if not texto:
        return None
    t = texto.strip()
    if t.startswith("```"):
        t = t.split("```")[1]
        if t.startswith("json"):
            t = t[4:]
    i, j = t.find("{"), t.rfind("}")
    if i == -1 or j == -1:
        return None
    try:
        return json.loads(t[i:j + 1])
    except json.JSONDecodeError:
        return None


def redactar(prompt: str, cache: dict) -> dict | None:
    k = clave(prompt)
    if k in cache:
        return cache[k]

    for proveedor in (pedir_gemini, pedir_groq):
        salida = extraer_json(proveedor(prompt) or "")
        if salida:
            cache[k] = salida
            return salida

    print("· sin respuesta de ningún proveedor")
    return None


def traducir_trozo(cola: str, cuerpo: str, cache: dict, profundidad=0) -> str:
    """
    Traduce un fragmento. Si vuelve cortado o vacío, lo parte en dos y lo
    intenta otra vez: así un tropiezo en una parte no se lleva por delante
    el artículo entero.
    """
    r = redactar(PROMPT_TROZO.format(cola=cola or "(es el principio)", cuerpo=cuerpo), cache)
    t = ((r or {}).get("texto") or "").strip()
    if t and not parece_cortado(t):
        return t

    # Se sigue partiendo por la mitad hasta que el trozo le quepa al
    # traductor. No hay un tamaño "seguro" fijo: depende del artículo y del
    # modelo del día, así que se adapta en vez de adivinarlo.
    if profundidad >= 4 or len(cuerpo) < 250:
        return ""

    mitad = partir(cuerpo, max(200, len(cuerpo) // 2))
    if len(mitad) < 2:
        return ""
    partes = []
    for trozo in mitad:
        anterior = " ".join((partes[-1] if partes else cola).split()[-25:])
        sub = traducir_trozo(anterior, trozo, cache, profundidad + 1)
        if not sub:
            return ""
        partes.append(sub)
    return "\n\n".join(partes)


def traducir_cuerpo(titular: str, cuerpo: str, cache: dict):
    """
    Devuelve (metadatos, texto, completo).

    Trocear es lo que garantiza que el artículo llegue entero: por muy alto
    que pongas el tope de salida, siempre habrá un artículo más largo. Con
    trozos de 2000 caracteres ninguna llamada se acerca al límite.
    """
    trozos = partir(cuerpo)
    r = redactar(PROMPT_NOTICIA.format(titular=titular, cuerpo=trozos[0]), cache)
    if not r:
        return None, "", False

    primero = (r.get("texto") or "").strip()
    if parece_cortado(primero):
        primero = traducir_trozo("", trozos[0], cache, 1)
    if not primero:
        return r, "", False

    partes = [primero]
    for extra in trozos[1:]:
        cola = " ".join(partes[-1].split()[-25:])
        sub = traducir_trozo(cola, extra, cache)
        if not sub:
            return r, "", False
        partes.append(sub)
        guardar_cache(cache)

    if len(trozos) > 1:
        print(f"·   «{titular[:34]}» traducida en {len(partes)} trozos")
    return r, "\n\n".join(partes), True


# -------------------------------------------------------------------- main

def main():
    if not (GEMINI_KEY or GROQ_KEY):
        print("Falta GEMINI_API_KEY (y GROQ_API_KEY). Nada que hacer.")
        sys.exit(1)

    crudo = json.loads((DATOS / "crudo.json").read_text(encoding="utf-8"))
    cache = cargar_cache()
    nuevas = 0

    for n in crudo.get("noticias", []):
        cuerpo = n.get("cuerpo_en", "")
        if not cuerpo:
            # Sin artículo no hay nada que traducir más allá del titular:
            # se salta en vez de inventar contenido.
            continue
        meta, texto, completo = traducir_cuerpo(n["titular_en"], cuerpo, cache)
        if meta is None:
            guardar_cache(cache)
            continue

        if not completo:
            print(f"·   «{n['titular_en'][:38]}» no se ha podido traducir entera "
                  f"— me quedo con el resumen")
            texto = ""

        n.update({"titular": meta.get("titular", n["titular_en"]),
                  "resumen": meta.get("resumen", ""),
                  "texto": texto,
                  "caballos": meta.get("caballos", []),
                  "categoria": meta.get("categoria", n.get("categoria", "jra"))})
        n.pop("cuerpo_en", None)     # el inglés ya no hace falta
        nuevas += 1
        guardar_cache(cache)

    # --- crónicas de las carreras ya corridas que aún no la tienen.
    # Esto es lo que estaba escrito pero sin conectar: el prompt existía y
    # la lista que le llegaba estaba siempre vacía, así que las carreras
    # nuevas se quedaban en tabla de números.
    pendientes = [c for c in crudo.get("calendario", [])
                  if c.get("llegada") and not c.get("cronica")]
    pendientes.sort(key=lambda c: c.get("fecha", ""), reverse=True)
    tope = int(os.environ.get("MAX_CRONICAS", "10"))
    print(f"· crónicas por escribir: {len(pendientes)} — escribiendo {min(tope, len(pendientes))}")

    for c in pendientes[:tope]:
        llegada = "\n".join(
            f"{x['pos']}. {x['caballo']} ({x.get('jockey','')}) "
            f"{x.get('tiempo','')} {x.get('margen','')} cuota {x.get('odds','')}"
            for x in c["llegada"][:8])
        ficha = c.get("ficha") or {}
        ganadores = ", ".join(f"{g[0]} {g[1]}" for g in ficha.get("ganadores", [])[:5]) or "(no disponible)"
        contexto = " · ".join(x for x in [c.get("edades"), c.get("premio"),
                                          ("cuerda a " + c["sentido"]) if c.get("sentido") else ""] if x)
        r = redactar(PROMPT_CRONICA.format(
            nombre=c.get("nombre", ""), grado=c.get("grado", ""), fecha=c.get("fecha", ""),
            hipodromo=c.get("hipodromo", ""), distancia=c.get("distancia", ""),
            superficie=c.get("superficie", ""), contexto=contexto or "(no disponible)",
            ganadores=ganadores, llegada=llegada), cache)
        if r and r.get("cronica") and not parece_cortado(r["cronica"]):
            c["cronica"] = r["cronica"]
            c["destacado"] = r.get("destacado", "")
            nuevas += 1
        guardar_cache(cache)

    (DATOS / "traducido.json").write_text(
        json.dumps(crudo, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"· {nuevas} textos redactados · caché: {len(cache)} entradas")


if __name__ == "__main__":
    main()

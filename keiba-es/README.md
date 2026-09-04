# KEIBA ES

Las carreras de la JRA en español, para mí. Se construye solo cada mañana y se
lee como una app en el móvil. Sin servidor, sin cuentas y sin coste.

```
datos/seguidos.json    ← MI lista. Es lo único que se edita a mano.
scripts/fuentes.py     ← TODO lo frágil (selectores y URLs)
scripts/recolectar.py  ← baja lo nuevo, con el artículo entero → datos/crudo.json
scripts/traducir.py    ← traduce y redacta                     → datos/traducido.json
scripts/construir.py   ← funde y publica                       → web/datos.json
web/                   ← la PWA. Solo lee datos.json
.github/workflows/     ← lo lanza todo a las 07:10
```

---

## Arrancar

**1. Repo en GitHub, público.** Público no por querer publicarlo, sino porque
en repos públicos los minutos de Actions son ilimitados y GitHub Pages es
gratis. En privado, Pages pide plan de pago y Actions se limita a 2.000
minutos. Nadie va a encontrar la URL, y no se promociona en ningún sitio.

> Alternativa si prefieres que no esté en internet: ejecutar los tres scripts
> en el PC de casa con una tarea programada y servir la carpeta `web/` por
> Tailscale. Funciona igual; la pega es que el PC tiene que estar encendido.

**2. Clave de Gemini.** [Google AI Studio](https://aistudio.google.com) →
*Get API key*, con la cuenta de Google y sin tarjeta. En el repo:
*Settings → Secrets and variables → Actions*, nombre `GEMINI_API_KEY`.

Añade también `GROQ_API_KEY` de [console.groq.com](https://console.groq.com):
es la reserva automática cuando Gemini agota cuota.

**3. Pages.** *Settings → Pages → Deploy from a branch → main → carpeta `/web`*.
Luego abre la URL en el móvil y "Añadir a pantalla de inicio".

**4. Primera ejecución, en local y en modo depuración:**

```bash
pip install -r requirements.txt
python scripts/recolectar.py --debug
```

Guarda el HTML descargado en `datos/debug/`. **Ábrelo y ajusta los selectores
de `scripts/fuentes.py`.** Es la única parte que no se puede escribir a ciegas,
y es media hora una sola vez.

```bash
export GEMINI_API_KEY=...
python scripts/traducir.py
python scripts/construir.py
python -m http.server -d web 8000   # http://localhost:8000
```

**5.** *Actions → Boletín diario → Run workflow* para probarlo en la nube.

---

## Mis caballos

`datos/seguidos.json`:

```json
{ "caballos": ["Meisho Tabaru", "Juryoku Pierrot"], "jockeys": ["Yutaka Take"] }
```

Eso es todo el sistema de cuentas. Al ser un fichero del repo:

- Va contigo a cualquier dispositivo sin sincronizar nada.
- Lo puedes editar desde el móvil, en github.com, sin abrir el PC.
- El pipeline lo lee y **pone sus noticias arriba y sus fichas primero**.

La estrella de la app sigue existiendo, pero es solo para ese dispositivo. La
lista de verdad es el fichero.

---

## Cuando se rompa

Se romperá: es scraping. Cuando netkeiba rediseñe, el workflow **falla a
propósito** y GitHub te manda un correo. Es intencionado: mejor enterarte que
descubrir tres semanas después que el boletín salía vacío.

El arreglo es siempre el mismo: `recolectar.py --debug`, mirar el HTML nuevo,
ajustar `fuentes.py`. Ningún otro fichero sabe nada de selectores.

---

## Los estados de una carrera

`construir.py` los calcula solo y la app pinta cosas distintas en cada uno:

| Estado | Cuándo | Qué se ve |
|---|---|---|
| `lejana` | meses antes | Ficha de enciclopedia: qué es, trazado, ganadores |
| `se_acerca` | aparece en noticias | + quién suena (no es cuadro confirmado) |
| `cuadro_cerrado` | la semana de | + participantes con jockey y peso |
| `con_mercado` | al abrir la venta | + cuotas y orden de favoritos |
| `corrida` | después | + vídeo, crónica y orden de llegada |

Por eso no hay que decidir si enseñar las cuotas: se enseñan cuando existen.

---

## Lo que hace la app

- **Hoy** — próxima carrera con cuenta atrás en hora española, noticias, última gran carrera.
- **Calendario** — la temporada completa; cada fila abre su ficha.
- **Caballos** — los tuyos primero, con forma y próxima cita.
- **Resultados** — vídeo oficial, crónica y orden de llegada con cuotas.
- **Leer** — la noticia **entera** traducida, no un resumen. Es lo que cambia
  al ser de uso personal: no se republica nada, se lee.
- **Sin spoilers** — las carreras se corren sobre las 08:40 hora española.
  El interruptor difumina ganadores y tiempos hasta que los tocas, para poder
  ver el vídeo primero. Está en Ajustes.
- **Calendario .ics** — exporta las carreras de tus caballos al calendario del
  móvil. Mejor que las notificaciones: sin permisos y sin servidor.
- **Sin conexión** — el service worker guarda lo último descargado.

---

## Coste

Cero. Actions ilimitado en repo público, Pages gratis, Gemini y Groq con capa
gratuita sin tarjeta. Con 30-60 noticias al día no te acercas a ningún límite,
y la caché por hash evita pagar dos veces por el mismo texto.

---

## Notas

- Se traduce del **inglés**, no del japonés: netkeiba tiene versión en inglés y
  japanracing.jp también. Es lo que hace esto barato y bueno.
- El vídeo se **enlaza** al canal oficial de la JRA, nunca se aloja.
- Las crónicas se **redactan** desde la tabla de resultados y la nota oficial;
  no son traducción de la crónica de nadie.
- No hay pronósticos. Las cuotas se muestran como dato, que es lo que hace
  legible una carrera.

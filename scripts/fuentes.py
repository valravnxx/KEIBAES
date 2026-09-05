"""
fuentes.py — TODO lo frágil vive aquí.

Cuando netkeiba o la JRA cambien su HTML, este es el ÚNICO fichero que hay que
tocar. El resto del pipeline no sabe nada de selectores CSS.

IMPORTANTE: los selectores de abajo están escritos a partir de la estructura
observada de las páginas, pero NO se han podido verificar contra el HTML en
crudo. La primera vez que ejecutes esto, hazlo con:

    python scripts/recolectar.py --debug

que guarda el HTML descargado en datos/debug/ para que puedas abrirlo y
ajustar los selectores. Es media hora de trabajo una sola vez.
"""

from dataclasses import dataclass, field

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Segundos entre peticiones. No lo bajes: es lo que separa "un lector
# automatizado educado" de "un bot que hay que bloquear".
ESPERA = 2.0

TIMEOUT = 25


# ---------------------------------------------------------------- noticias

NETKEIBA_NOTICIAS = "https://en.netkeiba.com/news/news_top.html"

NETKEIBA_CATEGORIAS = {
    1: "jra",
    2: "nar",
    3: "internacional",
    4: "cria",
    5: "jockeys",
}

def url_categoria(n: int) -> str:
    return f"https://en.netkeiba.com/news/search_list.html?type=category&category={n}"


@dataclass
class SelectoresNoticias:
    # Contenedor de cada noticia en el listado
    item: str = "li.NewsItem, div.NewsItem, ul.NewsList li"
    # Enlace al detalle (dentro del item)
    enlace: str = "a"
    # Titular
    titular: str = "h3, .NewsTitle, a"
    # Fecha/hora
    fecha: str = ".NewsDate, time, .Date"
    # En la página de detalle: cuerpo del artículo
    cuerpo_detalle: str = "div.NewsBody, div.ArticleBody, article"


SEL_NOTICIAS = SelectoresNoticias()


# ------------------------------------------------------------- calendario

def url_calendario(anio: int) -> str:
    return f"https://japanracing.jp/en/racing/schedule/jra/{anio}.html"


@dataclass
class SelectoresCalendario:
    # El calendario es una rejilla semanal: cada <tr> es UNA SEMANA con varias
    # carreras dentro. Por eso no se recorren filas, se recorren enlaces:
    # cada enlace a una ficha de carrera graduada es una carrera.
    enlace_carrera: str = 'a[href*="graded/list/"]'


SEL_CALENDARIO = SelectoresCalendario()

# La ficha de cada carrera graduada trae los datos buenos (hipódromo,
# distancia, superficie, premio, ganador del año pasado). Se leen por
# PATRÓN DE TEXTO y no por selector CSS: aguanta mucho mejor un rediseño.
PISTAS = ("NAKAYAMA", "TOKYO", "KYOTO", "HANSHIN", "CHUKYO",
          "SAPPORO", "HAKODATE", "FUKUSHIMA", "NIIGATA", "KOKURA")

RE_DISTANCIA = r"(\d{3,4})\s*m\s*,\s*(Turf|Dirt)"
RE_SENTIDO   = r"(right|left)\s*handed"
RE_EDADES    = r"(\d)\s*yo\s*&\s*up|(\d)\s*yo\b"
RE_PREMIO    = r"¥\s*([\d,]{7,})"
RE_GANADOR   = r"(\d{4})\s*Winner\s*:\s*([A-Za-z][A-Za-z'’\. -]{2,30})"

# Los grados se detectan por texto, no por clase: es más robusto ante
# rediseños y funciona igual en ambos sitios.
GRADOS = ("G1", "G2", "G3", "J-G1", "J-G2", "J-G3", "Jpn1", "Jpn2", "Jpn3")


# ------------------------------------------------------- carreras netkeiba

def url_resultado(race_id: str) -> str:
    return f"https://en.netkeiba.com/race/race_result.html?race_id={race_id}"

def url_inscripciones(race_id: str) -> str:
    return f"https://en.netkeiba.com/race/shutuba.html?race_id={race_id}"

def url_ficha_carrera(no: int) -> str:
    """Horse Racing Library: historia, trazado y ganadores. Casi no cambia."""
    return f"https://en.netkeiba.com/library/detail.html?no={no}"


@dataclass
class SelectoresResultado:
    fila: str = "table.RaceTable01 tr, table tr"
    # Índices de columna en la tabla de resultados (0-based).
    # Ajustar tras mirar el HTML real.
    col_puesto: int = 0
    col_caballo: int = 3
    col_jockey: int = 6
    col_tiempo: int = 7
    col_margen: int = 8
    col_odds: int = 10


SEL_RESULTADO = SelectoresResultado()


# --------------------------------------------------------------- vídeo

YOUTUBE_CANAL_JRA = "UCf7Vv3aTa1zM0PL1_LKMHIQ"  # JRA Official — verificar

def consulta_video(nombre_carrera: str, anio: int) -> str:
    """
    El canal oficial titula sus vídeos con un patrón fijo:
        2026 TAKARAZUKA KINEN (G1) | JRA Official
    Buscar por "<año> <NOMBRE> (G1)" acierta casi siempre.
    """
    return f"{anio} {nombre_carrera} JRA Official"


# ------------------------------------------------------- estadísticas

LEADING_JOCKEYS = "https://en.netkeiba.com/db/jockey/jockey_leading.html"
LEADING_SIRES = "https://en.netkeiba.com/db/horse/sire_leading.html"

def url_estadisticas_jra(anio: int) -> str:
    return f"https://japanracing.jp/_statistics/{anio}/s10.html"


# ------------------------------------------------------------ hipódromos
# Códigos de hipódromo dentro del race_id de netkeiba.
# race_id = AAAA HH RR DD CC
#           año  hip reunión jornada carrera
HIPODROMOS = {
    "01": "Sapporo", "02": "Hakodate", "03": "Fukushima", "04": "Niigata",
    "05": "Tokyo", "06": "Nakayama", "07": "Chukyo", "08": "Kyoto",
    "09": "Hanshin", "10": "Kokura",
}


def construir_race_id(anio, hipodromo, reunion, jornada, carrera) -> str:
    """202609030411 = 2026, Hanshin(09), 3ª reunión, 4ª jornada, carrera 11."""
    return (f"{anio}{hipodromo:0>2}{reunion:0>2}"
            f"{jornada:0>2}{carrera:0>2}")

/* KEIBA ES — toda la app lee de web/datos.json.
   Nada de frameworks: son 400 líneas y se entienden de una sentada. */

'use strict';

var D = null;                 // datos.json
var PILA = [];                // navegación hacia atrás
var HORA_ES = 'Europe/Madrid';

/* ------------------------------------------------- preferencias locales */

var P = {
  seguidos: [],
  sinSpoilers: false,
  tema: 'nocturno',
  categorias: { jra: true, internacional: true, cria: true, jockeys: true, nar: false }
};

function cargarPrefs() {
  try {
    var g = localStorage.getItem('keiba-es');
    if (g) Object.assign(P, JSON.parse(g));
  } catch (e) { /* modo privado o almacenamiento bloqueado: seguimos igual */ }
  document.body.classList.toggle('nospo', P.sinSpoilers);
  document.body.dataset.tema = P.tema || 'nocturno';
}

function guardarPrefs() {
  try { localStorage.setItem('keiba-es', JSON.stringify(P)); } catch (e) {}
}

/* ------------------------------------------------------------ utilidades */

var MES = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
var DIA = ['dom','lun','mar','mié','jue','vie','sáb'];

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c];
  });
}

function fecha(iso) {
  var d = new Date(iso + 'T12:00:00Z');
  return isNaN(d) ? { d: '', m: '', dow: '' }
    : { d: String(d.getUTCDate()).padStart(2, '0'), m: MES[d.getUTCMonth()],
        dow: DIA[d.getUTCDay()], anio: d.getUTCFullYear() };
}

/** Convierte una hora japonesa a hora española. La JRA da las horas en JST
    (UTC+9, sin horario de verano); España cambia dos veces al año, así que
    esto NO es una resta fija de 7 horas. */
function horaEspanola(fechaISO, horaJST) {
  if (!fechaISO || !horaJST) return '';
  var p = horaJST.split(':');
  var utc = Date.UTC(+fechaISO.slice(0,4), +fechaISO.slice(5,7) - 1, +fechaISO.slice(8,10),
                     +p[0] - 9, +p[1]);
  return new Date(utc).toLocaleTimeString('es-ES',
    { timeZone: HORA_ES, hour: '2-digit', minute: '2-digit' });
}

function carrera(id) { return (D.carreras || []).find(function (c) { return c.id === id; }); }
function caballo(n)  { return (D.caballos || []).find(function (c) { return c.nombre === n; }); }
function sigue(n)    { return P.seguidos.indexOf(n) > -1; }

function iniciales(n) {
  return n.split(/\s+/).slice(0, 2).map(function (w) { return w[0]; }).join('').toUpperCase();
}

/** Color estable derivado del nombre: cada caballo tiene siempre el mismo. */
function color(n) {
  var h = 0;
  for (var i = 0; i < n.length; i++) h = (h * 31 + n.charCodeAt(i)) % 360;
  return 'hsl(' + h + ' 42% 58%)';
}

/* ------------------------------------------------------------ navegación */

function mostrar(id) {
  document.querySelectorAll('.page').forEach(function (x) { x.classList.remove('on'); });
  document.getElementById(id).classList.add('on');
  window.scrollTo(0, 0);
}

function abrir(id, titulo, render) {
  var actual = document.querySelector('.page.on');
  if (actual) PILA.push(actual.id);
  if (render) render();
  else if (id === 'p-perfil') pintaPerfil();
  else if (id === 'p-ajustes') pintaAjustes();
  else if (id === 'p-stats') pintaStats();
  else if (id === 'p-buscar') pintaBuscar();
  else if (id === 'p-guia') pintaGuia();
  document.getElementById('hd-main').hidden = true;
  document.getElementById('hd-back').hidden = false;
  document.getElementById('hd-title').textContent = titulo || '';
  mostrar(id);
}

function volver() {
  var prev = PILA.pop() || 'p-hoy';
  mostrar(prev);
  if (!PILA.length) {
    document.getElementById('hd-main').hidden = false;
    document.getElementById('hd-back').hidden = true;
  }
}

/* ------------------------------------------------------------- fragmentos */

function filaCarrera(c, tap) {
  var f = fecha(c.fecha);
  var pasada = c.estado === 'corrida' || c.estado === 'pasada';
  var sub = [c.hipodromo, c.distancia ? c.distancia + ' m' : '', c.alias || '',
             c.estado === 'pasada' ? 'ya corrida' : ''].filter(Boolean).join(' · ');
  return '<div class="race' + (pasada ? ' past' : '') + (tap ? ' tap' : '') + '"' +
    (tap ? ' onclick="verCarrera(\'' + c.id + '\')"' : '') + '>' +
    '<div class="day"><b>' + f.d + '</b><span>' + (f.dow || f.m) + '</span></div>' +
    '<div class="body"><b>' + esc(c.nombre) + '</b><span>' + esc(sub) + '</span></div>' +
    '<span class="g ' + esc(c.grado) + '">' + esc(c.grado) + '</span></div>';
}

function tarjetaNoticia(n) {
  var leible = !!n.texto;
  return '<article class="card news' + (leible ? ' tap' : '') + '"' +
    (leible ? ' onclick="leer(\'' + n.id + '\')"' : '') + '><div class="top">' +
    '<span class="tag ' + esc(n.categoria || 'jra') + '">' + esc(n.categoria || 'jra') + '</span>' +
    '<span class="badge-ia">Traducido</span>' +
    '<span class="time">' + esc((n.fecha_texto || '').slice(5, 16)) + '</span></div>' +
    '<h3>' + esc(n.titular) + '</h3><p>' + esc(n.resumen) + '</p>' +
    '<div class="src">' + esc(n.medio || 'netkeiba') +
    ' · <a href="' + esc(n.url) + '" target="_blank" rel="noopener" onclick="event.stopPropagation()">original</a>' +
    (leible ? '<span style="margin-left:auto;color:var(--acc);font-weight:700">leer ›</span>' : '') +
    '</div></article>';
}

/* Vista de lectura: la noticia entera traducida. Solo tiene sentido porque
   esto es de uso personal — no se republica nada, se lee. */
function leer(id) {
  var n = (D.noticias || []).find(function (x) { return x.id === id; });
  if (!n) return;
  abrir('p-leer', 'Noticia', function () {
    document.getElementById('p-leer').innerHTML =
      '<div class="top" style="display:flex;gap:8px;align-items:center;margin-bottom:12px">' +
      '<span class="tag ' + esc(n.categoria || 'jra') + '">' + esc(n.categoria || 'jra') + '</span>' +
      '<span class="badge-ia">Traducido</span>' +
      '<span class="time">' + esc((n.fecha_texto || '').slice(0, 16)) + '</span></div>' +
      '<h1 class="art">' + esc(n.titular) + '</h1>' +
      (n.caballos || []).map(function (c) {
        return caballo(c) ? '<button class="chip2" onclick="verCaballo(\'' + esc(c) + '\')">' +
          esc(c) + ' ›</button>' : '';
      }).join('') +
      '<div class="cuerpo">' + (n.texto || '').split('\n\n').map(function (par) {
        return '<p>' + esc(par) + '</p>';
      }).join('') + '</div>' +
      '<div class="src">' + esc(n.medio || 'netkeiba') + ' · ' +
      '<a href="' + esc(n.url) + '" target="_blank" rel="noopener">ver el original en inglés</a></div>';
  });
}

/** Enlace de búsqueda en el canal oficial. Sin clave de API no podemos saber
    el identificador exacto del vídeo, pero esto cae en él a un toque. */
function buscarVideo(c) {
  return 'https://www.youtube.com/results?search_query=' +
    encodeURIComponent(fecha(c.fecha).anio + ' ' + c.nombre + ' (' + c.grado + ') JRA Official');
}

/** Qué enseñar cuando no tenemos miniatura:
    · G1  → el canal oficial sube uno por carrera, así que se busca ahí
    · resto → la JRA publica repetición de TODAS en su ficha oficial */
function videoAlternativo(c) {
  if (c.grado === 'G1') {
    return '<a class="btn pri" href="' + buscarVideo(c) + '" target="_blank" rel="noopener" ' +
      'style="margin-bottom:12px">▶  Ver el vídeo en el canal de la JRA</a>';
  }
  if (c.url || c.fuente) {
    return '<a class="btn" href="' + esc(c.url || c.fuente) + '" target="_blank" rel="noopener" ' +
      'style="margin-bottom:12px">▶  Ver la repetición en japanracing.jp</a>';
  }
  return '';
}

function video(id, etiqueta) {
  if (!id) return '';
  return '<a class="vid" href="https://www.youtube.com/watch?v=' + esc(id) +
    '" target="_blank" rel="noopener">' +
    '<img src="https://i.ytimg.com/vi/' + esc(id) + '/hqdefault.jpg" alt="" loading="lazy">' +
    '<span class="play"><i></i></span><span class="lbl">' + esc(etiqueta || 'JRA OFICIAL') + '</span></a>';
}

function estrella(nombre) {
  return '<button class="star' + (sigue(nombre) ? ' on' : '') + '" onclick="alternar(event,\'' +
    esc(nombre) + '\')" aria-label="Seguir"><svg viewBox="0 0 24 24">' +
    '<path d="M12 3l2.6 5.6 6 .8-4.4 4.2 1.1 6-5.3-3-5.3 3 1.1-6L3.4 9.4l6-.8z"/></svg></button>';
}

function alternar(e, nombre) {
  e.stopPropagation();
  var i = P.seguidos.indexOf(nombre);
  if (i > -1) P.seguidos.splice(i, 1); else P.seguidos.push(nombre);
  guardarPrefs();
  e.currentTarget.classList.toggle('on');
}

/* ------------------------------------------------------------- pantallas */

function pintaHoy() {
  // Próxima = la primera que aún no se ha corrido. Sin este filtro por días,
  // el calendario anual hacía que la portada enseñara una carrera de enero
  // con la cuenta atrás en negativo.
  var prox = (D.carreras || []).filter(function (c) {
    return c.fecha && c.estado !== 'corrida' && c.estado !== 'pasada' &&
           (c.dias == null || c.dias >= 0);
  })[0];
  var ultima = (D.carreras || []).filter(function (c) { return c.estado === 'corrida'; }).slice(-1)[0];
  var h = '';

  if (prox) {
    var f = fecha(prox.fecha);
    var he = horaEspanola(prox.fecha, prox.hora_jst);
    h += '<div class="hero tap" onclick="verCarrera(\'' + prox.id + '\')">' +
      '<span class="grade">' + esc(prox.grado) + '</span>' +
      '<h1>' + esc(prox.nombre) + ' <span style="font-size:17px;color:var(--tx3);font-weight:400">›</span></h1>' +
      '<p class="jp">' + esc([prox.nombre_jp, prox.hipodromo,
        prox.distancia ? prox.distancia + ' m' : ''].filter(Boolean).join(' · ')) + '</p>' +
      '<div class="cd"><div><b id="cd-d">–</b><span>días</span></div>' +
      '<div><b id="cd-h">–</b><span>horas</span></div>' +
      '<div><b id="cd-m">–</b><span>min</span></div></div>' +
      '<div class="meta"><span class="chip">' + f.dow + ' ' + f.d + ' ' + f.m + '</span>' +
      (prox.hora_jst ? '<span class="chip">' + esc(prox.hora_jst) + ' JST · ' + he + ' España</span>' : '') +
      '</div></div>';
  }

  var noticias = (D.noticias || []).filter(function (n) {
    return P.categorias[n.categoria] !== false;
  });
  if (P.seguidos.length) {
    // Las noticias de tus caballos, arriba.
    noticias.sort(function (a, b) {
      var A = (a.caballos || []).some(sigue) ? 1 : 0;
      var B = (b.caballos || []).some(sigue) ? 1 : 0;
      return B - A;
    });
  }
  h += '<h2 class="sec">Noticias del día</h2>' +
       noticias.slice(0, 8).map(tarjetaNoticia).join('');

  if (ultima) {
    h += '<h2 class="sec">Última gran carrera <em onclick="ir(\'p-res\')">ver todas ›</em></h2>' +
      '<div class="spoiler-hint">Modo sin spoilers activo · toca para revelar</div>' +
      '<div class="card tap" onclick="verCarrera(\'' + ultima.id + '\')">' +
      video(ultima.video_id) +
      '<div class="rhead"><span class="g ' + esc(ultima.grado) + '">' + esc(ultima.grado) + '</span>' +
      '<h3>' + esc(ultima.nombre) + '</h3></div>' +
      '<p class="cron spo" style="margin:0">' + esc(ultima.destacado || '') + '</p></div>';
  }

  h += '<h2 class="sec">Para entender lo que ves</h2>' +
    '<div class="card tap" onclick="abrir(\'p-guia\',\'Cómo se lee\')" style="display:flex;align-items:center;gap:12px">' +
    '<div class="silk" style="background:#3f6f8e;color:#fff">?</div>' +
    '<div style="flex:1"><b style="font-size:15px">Cómo se lee una carrera japonesa</b>' +
    '<div style="font-size:12px;color:var(--tx3);margin-top:2px">Grados, cuotas, el voto de los aficionados y la triple corona</div></div>' +
    '<span style="color:var(--tx3);font-size:18px">›</span></div>';

  document.getElementById('p-hoy').innerHTML = h;
  if (prox) cuentaAtras(prox);
}

var timerCuenta = null;
function cuentaAtras(c) {
  var objetivo = Date.UTC(+c.fecha.slice(0,4), +c.fecha.slice(5,7) - 1, +c.fecha.slice(8,10),
                          +(c.hora_jst || '15:00').slice(0,2) - 9, +(c.hora_jst || '15:00').slice(3,5));
  function tick() {
    var d = document.getElementById('cd-d');
    if (!d) { clearInterval(timerCuenta); return; }
    var s = Math.floor((objetivo - Date.now()) / 1000);
    if (s <= 0) {
      // Ya ha salido (o es hoy y no sabemos la hora). Tres ceros no dicen
      // nada; mejor decirlo con palabras.
      var caja = d.closest('.cd');
      if (caja) caja.outerHTML =
        '<div class="chip" style="display:inline-block;margin-bottom:14px;font-weight:700">' +
        'Se corre hoy</div>';
      clearInterval(timerCuenta);
      return;
    }
    d.textContent = Math.floor(s / 86400);
    document.getElementById('cd-h').textContent = String(Math.floor(s % 86400 / 3600)).padStart(2, '0');
    document.getElementById('cd-m').textContent = String(Math.floor(s % 3600 / 60)).padStart(2, '0');
  }
  tick();
  clearInterval(timerCuenta);
  timerCuenta = setInterval(tick, 30000);
}

var CAL = { modo: 'proximas', filtro: 'Todas' };

function pintaCalendario() {
  var modos = [['proximas', 'Próximas'], ['pasadas', 'Ya corridas']];
  var filtros = ['Todas', 'Solo G1', 'G2 y G3', 'Tokyo', 'Nakayama', 'Kyoto', 'Hanshin'];

  var h = '<div class="filters">' + modos.map(function (m) {
      return '<button class="f' + (CAL.modo === m[0] ? ' on' : '') +
        '" onclick="calModo(\'' + m[0] + '\')">' + m[1] + '</button>';
    }).join('') + '</div>' +
    '<div class="filters">' + filtros.map(function (t) {
      return '<button class="f' + (CAL.filtro === t ? ' on' : '') +
        '" onclick="calFiltro(\'' + t + '\')">' + t + '</button>';
    }).join('') + '</div>' +
    '<div id="cal-lista">' + listaCalendario() + '</div>';
  document.getElementById('p-cal').innerHTML = h;
}

function calModo(m) { CAL.modo = m; pintaCalendario(); }
function calFiltro(f) { CAL.filtro = f; pintaCalendario(); }

function listaCalendario() {
  var cs = (D.carreras || []).filter(function (c) { return c.fecha; });

  // Lo que ya se ha corrido no estorba a lo que viene: son dos pestañas.
  var corrida = function (c) {
    return c.estado === 'corrida' || c.estado === 'pasada' ||
           (c.dias != null && c.dias < 0);
  };
  cs = cs.filter(function (c) {
    return CAL.modo === 'pasadas' ? corrida(c) : !corrida(c);
  });

  var f = CAL.filtro;
  if (f === 'Solo G1') cs = cs.filter(function (c) { return c.grado === 'G1'; });
  else if (f === 'G2 y G3') cs = cs.filter(function (c) { return c.grado === 'G2' || c.grado === 'G3'; });
  else if (f !== 'Todas') cs = cs.filter(function (c) { return c.hipodromo === f; });

  // Próximas: de la más cercana en adelante. Pasadas: de la más reciente atrás.
  cs.sort(function (a, b) {
    return CAL.modo === 'pasadas' ? (a.fecha < b.fecha ? 1 : -1)
                                  : (a.fecha > b.fecha ? 1 : -1);
  });

  if (!cs.length) {
    return '<div class="empty">Nada con ese filtro.</div>';
  }

  var h = '<div class="empty" style="padding:4px 0 12px;text-align:left">' +
    cs.length + (CAL.modo === 'pasadas' ? ' ya corridas' : ' por delante') + '</div>';
  var mes = '';
  cs.forEach(function (c) {
    var fe = fecha(c.fecha), etiqueta = fe.m + ' ' + fe.anio;
    if (etiqueta !== mes) { mes = etiqueta; h += '<div class="month">' + esc(mes) + '</div>'; }
    h += filaCarrera(c, true);
  });
  return h;
}

function pintaCaballos() {
  var cs = (D.caballos || []).slice();
  cs.sort(function (a, b) { return (sigue(b.nombre) ? 1 : 0) - (sigue(a.nombre) ? 1 : 0); });
  var h = cs.map(function (c) {
    var prox = c.proxima ? carrera(c.proxima) : null;
    return '<div class="horse tap" onclick="verCaballo(\'' + esc(c.nombre) + '\')">' +
      '<div class="silk" style="background:' + color(c.nombre) + '">' + esc(iniciales(c.nombre)) + '</div>' +
      '<div class="n"><b>' + esc(c.nombre) + '</b>' +
      '<div class="sub">' + esc(c.perfil || '') + (c.jockey ? ' · ' + esc(c.jockey) : '') + '</div>' +
      (c.forma && c.forma.length ? '<div class="form">' + c.forma.map(function (p) {
        return '<i class="' + (p === 1 ? 'w' : p <= 3 ? 'p' : '') + '">' + p + '</i>';
      }).join('') + '</div>' : '') +
      (prox ? '<div class="next">Próxima: <b>' + esc(prox.nombre) + '</b> · ' +
        fecha(prox.fecha).d + ' ' + fecha(prox.fecha).m + '</div>' : '') +
      '</div>' + estrella(c.nombre) + '</div>';
  }).join('');
  document.getElementById('p-cab').innerHTML = h +
    '<div class="empty">La lista se llena sola: entra todo caballo que gane o coloque en una ' +
    'carrera graduada, o que se repita en las noticias. La estrella marca a quién sigues.</div>';
}

function pintaResultados() {
  // Entran las que tienen resultado Y las que ya se corrieron aunque no
  // tengamos su clasificación: de esas al menos hay repetición que ver.
  var cs = (D.carreras || []).filter(function (c) {
    return c.estado === 'corrida' || c.estado === 'pasada';
  }).slice().sort(function (a, b) { return a.fecha < b.fecha ? 1 : -1; });
  var h = '<div class="spoiler-hint">Modo sin spoilers activo · toca para revelar</div>';
  var mes = '';
  cs.forEach(function (c) {
    var f = fecha(c.fecha), etiqueta = f.m + ' ' + f.anio;
    if (etiqueta !== mes) { mes = etiqueta; h += '<div class="month">' + esc(mes) + '</div>'; }
    var gana = (c.llegada || [])[0];
    h += '<div class="card tap" onclick="verCarrera(\'' + c.id + '\')">' +
      (c.video_id ? video(c.video_id) : '') +
      '<div class="rhead"><span class="g ' + esc(c.grado) + '">' + esc(c.grado) + '</span>' +
      '<h3>' + esc(c.nombre) + '</h3></div>' +
      '<p class="rsub">' + f.d + ' ' + f.m + ' · ' + esc(c.hipodromo) + ' · ' + c.distancia + ' m' +
      (gana ? ' · <span class="spo">ganó ' + esc(gana.caballo) + '</span>' : '') + '</p></div>';
  });
  document.getElementById('p-res').innerHTML = (h || '') +
    '<div class="empty">La JRA publica repetición de <b>todas</b> sus carreras en menos de 20 minutos.<br>' +
    'Los G1 van además a su canal oficial de YouTube, que es lo que se enlaza aquí.</div>';
}

/* --------------------------------------------------------- ficha carrera */

function verCarrera(id) {
  var c = carrera(id);
  if (!c) return;
  abrir('p-carrera', c.nombre, function () {
    // Una carrera ya corrida usa la ficha de resultado aunque no tengamos su
    // clasificación: lo que interesa ahí es la repetición, no la cuenta atrás.
    document.getElementById('p-carrera').innerHTML =
      (c.estado === 'corrida' || c.estado === 'pasada')
        ? fichaCorrida(c) : fichaFutura(c);
  });
}

function fichaCorrida(c) {
  var f = fecha(c.fecha), g = (c.llegada || [])[0] || {};
  var favorita = (c.llegada || []).reduce(function (a, b) {
    var x = parseFloat(a && a.odds), y = parseFloat(b.odds);
    return (!isNaN(y) && (isNaN(x) || y < x)) ? b : a;
  }, null);

  var h = (c.video_id ? video(c.video_id, 'VER EN EL CANAL OFICIAL DE LA JRA')
                      : videoAlternativo(c)) +
    '<div class="rhead"><span class="g ' + esc(c.grado) + '">' + esc(c.grado) + '</span>' +
    '<h3>' + esc(c.nombre) + (c.alias ? ' · ' + esc(c.alias) : '') + '</h3></div>' +
    '<p class="rsub">' + esc([c.nombre_jp, f.d + ' ' + f.m + ' ' + f.anio, c.hipodromo,
      c.distancia ? c.distancia + ' m' : ''].filter(Boolean).join(' · ')) + '</p>';

  if (g.tiempo) {
    h += '<div class="stats spo"><div><b>' + esc(g.tiempo) + '</b><span>tiempo</span></div>' +
      '<div><b>' + esc((c.llegada[1] || {}).margen || '–') + '</b><span>margen</span></div>' +
      '<div><b>' + c.distancia + '</b><span>metros</span></div></div>';
  }

  if (c.cronica) {
    h += '<h2 class="sec">Qué pasó</h2>' +
      c.cronica.split('\n\n').map(function (p) {
        return '<p class="cron spo">' + esc(p) + '</p>';
      }).join('');
  }

  if ((c.llegada || []).length) {
    h += '<h2 class="sec">' + (favorita && favorita.odds ? 'El cuadro' : 'Orden de llegada') + '</h2>' +
      '<div class="card fin spo" style="padding-top:14px">' +
      c.llegada.map(function (x) {
        return '<div class="fr p' + x.pos + '"><span class="pos">' + x.pos + '</span>' +
          '<span class="hn">' + esc(x.caballo) + '</span>' +
          '<span class="jk">' + esc(x.jockey || '') + '</span>' +
          (favorita && favorita.odds ? '<span class="od' + (x === favorita ? ' fav' : '') + '">' +
            esc(x.odds || '—') + '</span>' : '') +
          '<span class="mg">' + esc(x.pos === 1 ? x.tiempo : x.margen) + '</span></div>';
      }).join('') + '</div>';
    if (favorita && favorita.odds && favorita.pos !== 1) {
      h += '<div class="note">La columna naranja es el <b>favorito</b>: ' + esc(favorita.caballo) +
        ' salía a ' + esc(favorita.odds) + ' y acabó ' + favorita.pos + 'º. ' +
        'Las cuotas no son un consejo, son la foto de lo que esperaba el público.</div>';
    }
  }

  if (c.fuente) h += '<div class="src" style="border:0">Fuente oficial: ' +
    '<a href="' + esc(c.fuente) + '" target="_blank" rel="noopener">ver</a></div>';
  if (!c.cronica && !(c.llegada || []).length) {
    h += '<div class="empty">De esta carrera todavía no tenemos la clasificación.<br>' +
      'La repetición sí está disponible en el enlace de arriba.</div>';
  }
  return h;
}

function fichaFutura(c) {
  var f = fecha(c.fecha), fi = c.ficha || {};
  var he = horaEspanola(c.fecha, c.hora_jst);
  var h = '<div class="hero"><span class="grade">' + esc(c.grado) + '</span>' +
    '<h1>' + esc(c.nombre) + '</h1>' +
    '<p class="jp">' + esc([c.nombre_jp, f.d + ' ' + f.m + ' ' + f.anio, c.hipodromo,
      c.distancia ? c.distancia + ' m' : ''].filter(Boolean).join(' · ')) + '</p>' +
    '<div class="meta">' +
    (he ? '<span class="chip">' + esc(c.hora_jst) + ' JST · ' + he + ' España</span>' : '') +
    (c.dias === 0 ? '<span class="chip">Se corre hoy</span>' :
     c.dias > 0 ? '<span class="chip">faltan ' + c.dias + ' días</span>' : '') + '</div></div>';

  var datos = [];
  if (c.superficie) datos.push(c.superficie === 'cesped' ? 'Césped' : 'Arena');
  if (c.sentido) datos.push('cuerda a ' + c.sentido);
  if (c.edades) datos.push(c.edades);
  if (c.premio) datos.push(c.premio + ' en premios');
  if (datos.length) {
    h += '<h2 class="sec">La carrera</h2><div class="meta" style="margin-bottom:14px">' +
      datos.map(function (x) { return '<span class="chip">' + esc(x) + '</span>'; }).join('') + '</div>';
  }

  if (fi.que_es) h += '<h2 class="sec">Qué es esta carrera</h2><p class="cron">' + esc(fi.que_es) + '</p>';
  if (fi.trazado) h += '<h2 class="sec">El recorrido</h2><p class="cron">' + esc(fi.trazado) + '</p>';

  var lista = (c.participantes || []).length ? c.participantes.map(function (p) { return p.caballo; })
                                            : (c.suenan || []);
  if (lista.length) {
    h += '<h2 class="sec">' + ((c.participantes || []).length ? 'Participantes' : 'Quién suena') + '</h2>';
    if (!(c.participantes || []).length) {
      h += '<div class="note">Las inscripciones definitivas se publican la semana de la carrera. ' +
        'Hasta entonces esta lista sale de quién aparece en las noticias, no de un cuadro confirmado.</div>';
    }
    h += lista.map(function (n) {
      return '<div class="horse tap" onclick="verCaballo(\'' + esc(n) + '\')">' +
        '<div class="silk" style="background:' + color(n) + '">' + esc(iniciales(n)) + '</div>' +
        '<div class="n"><b>' + esc(n) + '</b></div>' +
        '<span style="color:var(--tx3);font-size:18px;align-self:center">›</span></div>';
    }).join('');
  }

  h += '<h2 class="sec">Cuotas</h2>';
  var conOdds = (c.participantes || []).filter(function (p) { return p.odds; });
  if (conOdds.length) {
    h += '<div class="card fin" style="padding-top:14px">' + conOdds.map(function (p) {
      return '<div class="fr"><span class="hn">' + esc(p.caballo) + '</span>' +
        '<span class="od">' + esc(p.odds) + '</span></div>';
    }).join('') + '</div>';
  } else {
    h += '<div class="card" style="text-align:center;padding:22px 16px">' +
      '<div style="font-size:26px;font-weight:800;color:var(--tx3)">—</div>' +
      '<div style="font-size:13px;color:var(--tx2);margin-top:8px;line-height:1.55">' +
      'Todavía no hay mercado. Las cuotas aparecen cuando abre la venta,<br>ya con el cuadro cerrado.</div></div>';
  }

  if (fi.ganadores && fi.ganadores.length) {
    h += '<h2 class="sec">Últimos ganadores</h2><div class="card fin" style="padding-top:14px">' +
      fi.ganadores.map(function (g) {
        return '<div class="fr"><span class="pos">' + esc(String(g[0]).slice(2)) + '</span>' +
          '<span class="hn">' + esc(g[1]) + '</span><span class="jk">' + esc(g[2] || '') + '</span></div>';
      }).join('') + '</div>';
  }

  var enlace = c.fuente || c.url;
  if (enlace) h += '<div class="src" style="border:0">Ficha oficial: ' +
    '<a href="' + esc(enlace) + '" target="_blank" rel="noopener">verla en japanracing.jp</a></div>';
  if (!fi.que_es && !lista.length && !datos.length) {
    h += '<div class="empty">Los detalles de esta carrera aún no se han descargado.<br>' +
      'Se rellenan solos: cada día se abren las fichas de las carreras más cercanas.</div>';
  }
  return h;
}

/* --------------------------------------------------------- ficha caballo */

function verCaballo(nombre) {
  var c = caballo(nombre) || { nombre: nombre, historial: [], forma: [] };
  abrir('p-caballo', nombre, function () {
    var prox = c.proxima ? carrera(c.proxima) : null;
    var h = '<div class="card" style="display:flex;gap:14px;align-items:center">' +
      '<div class="silk" style="background:' + color(nombre) + ';width:56px;height:56px;font-size:19px">' +
      esc(iniciales(nombre)) + '</div><div style="flex:1">' +
      '<div style="font-size:21px;font-weight:800">' + esc(nombre) + '</div>' +
      '<div style="font-size:12.5px;color:var(--tx3);margin-top:2px">' +
      esc([c.perfil, c.jockey].filter(Boolean).join(' · ')) + '</div></div>' +
      estrella(nombre) + '</div>';

    if (c.victorias != null) {
      h += '<div class="stats"><div><b>' + (c.g1 || 0) + '</b><span>G1 ganados</span></div>' +
        '<div><b>' + (c.victorias || 0) + '</b><span>victorias</span></div>' +
        '<div><b>' + (c.historial || []).length + '</b><span>carreras</span></div></div>';
    }

    if (c.porque) h += '<h2 class="sec">Por qué seguirlo</h2><p class="cron">' + esc(c.porque) + '</p>';

    if ((c.historial || []).length) {
      h += '<h2 class="sec">Historial</h2>' + c.historial.slice().reverse().map(function (x) {
        var r = carrera(x.carrera);
        if (!r) return '';
        var f = fecha(x.fecha);
        return '<div class="card tap" onclick="verCarrera(\'' + r.id + '\')" ' +
          'style="display:flex;align-items:center;gap:11px">' +
          '<span class="pos" style="width:24px;height:24px;border-radius:6px;background:' +
          (x.pos === 1 ? '#c8a03a;color:#181207' : '#232b34;color:var(--tx2)') +
          ';font-size:11px;font-weight:800;display:flex;align-items:center;justify-content:center">' +
          x.pos + '</span><div style="flex:1"><b style="font-size:14px">' + esc(r.nombre) + '</b>' +
          '<div style="font-size:11.5px;color:var(--tx3)">' + f.d + ' ' + f.m + ' ' + f.anio +
          ' · ' + esc(r.hipodromo) + ' ' + r.distancia + ' m</div></div>' +
          '<span class="g ' + esc(r.grado) + '">' + esc(r.grado) + '</span></div>';
      }).join('');
    }

    if (prox) h += '<h2 class="sec">Próxima cita</h2>' + filaCarrera(prox, true);
    document.getElementById('p-caballo').innerHTML = h;
  });
}

/* ------------------------------------------------------ perfil y ajustes */

function pintaPerfil() {
  var mios = (D.caballos || []).filter(function (c) { return sigue(c.nombre); });
  var h = '<div class="card" style="display:flex;gap:14px;align-items:center">' +
    '<div class="avatar" style="width:52px;height:52px;font-size:17px">YO</div><div style="flex:1">' +
    '<div style="font-size:19px;font-weight:800">Mi perfil</div>' +
    '<div style="font-size:12px;color:var(--tx3);margin-top:2px">Local · sin cuenta · España</div></div></div>' +
    '<div class="note">Todo lo que marcas vive <b>en este dispositivo</b>. No hay registro ni contraseña ' +
    'y no se envía nada a ningún servidor.</div>';

  h += '<h2 class="sec">Mis caballos <em>' + mios.length + '</em></h2>';
  if (!mios.length) {
    h += '<div class="empty">Todavía no sigues a ninguno.<br>Toca la estrella en cualquier caballo.</div>';
  } else {
    h += mios.map(function (c) {
      var p = c.proxima ? carrera(c.proxima) : null;
      return '<div class="horse tap" onclick="verCaballo(\'' + esc(c.nombre) + '\')">' +
        '<div class="silk" style="background:' + color(c.nombre) + '">' + esc(iniciales(c.nombre)) + '</div>' +
        '<div class="n"><b>' + esc(c.nombre) + '</b><div class="sub">' + esc(c.perfil || '') + '</div>' +
        (p ? '<div class="next">Corre en <b>' + (p.dias != null ? p.dias + ' días' : '—') +
          '</b> · ' + esc(p.nombre) + '</div>' : '<div class="next">Sin carrera confirmada</div>') +
        '</div></div>';
    }).join('') +
    '<button class="btn pri" onclick="descargarICS()">Añadir sus carreras a mi calendario</button>' +
    '<div class="empty" style="padding:6px 20px 18px">Un archivo .ics en hora española. ' +
    'El calendario del móvil hace el resto: sin permisos de notificación, sin servidor.</div>';
  }

  h += '<div class="card tap" onclick="abrir(\'p-stats\',\'Estadísticas\')" style="display:flex;align-items:center;gap:12px">' +
    '<div class="silk" style="background:#3f6f8e;color:#fff">%</div><div style="flex:1">' +
    '<b style="font-size:15px">Estadísticas</b></div><span style="color:var(--tx3);font-size:18px">›</span></div>' +
    '<div class="card tap" onclick="abrir(\'p-ajustes\',\'Ajustes\')" style="display:flex;align-items:center;gap:12px">' +
    '<div class="silk" style="background:#2c343d;color:#a8c2d8">⚙</div><div style="flex:1">' +
    '<b style="font-size:15px">Ajustes</b></div><span style="color:var(--tx3);font-size:18px">›</span></div>';

  document.getElementById('p-perfil').innerHTML = h;
}

function opcion(titulo, desc, activo, accion) {
  return '<div class="opt"><div class="t"><b>' + esc(titulo) + '</b><span>' + esc(desc) + '</span></div>' +
    '<div class="sw' + (activo ? ' on' : '') + '" onclick="' + accion + '"></div></div>';
}

var TEMAS = [
  { id: 'nocturno', nombre: 'Nocturno', bg: '#0d1117', c1: '#e0603f', c2: '#aab8c6', c3: '#28323e' },
  { id: 'papel',    nombre: 'Papel',    bg: '#f2eee4', c1: '#b8342a', c2: '#4d5760', c3: '#ddd6c6' },
  { id: 'turf',     nombre: 'Turf',     bg: '#0b1410', c1: '#d9a038', c2: '#adbcae', c3: '#25392e' }
];

function ponTema(id) {
  P.tema = id;
  document.body.dataset.tema = id;
  guardarPrefs();
  pintaAjustes();
  var m = document.querySelector('meta[name="theme-color"]');
  var t = TEMAS.find(function (x) { return x.id === id; });
  if (m && t) m.setAttribute('content', t.bg);
}

function pintaAjustes() {
  var h = '<h2 class="sec">Aspecto</h2><div class="temas">' +
    TEMAS.map(function (t) {
      return '<button class="tema' + (P.tema === t.id ? ' on' : '') + '" onclick="ponTema(\'' + t.id + '\')">' +
        '<div class="mues" style="background:' + t.bg + '">' +
        '<span class="b1" style="background:' + t.c1 + '"></span>' +
        '<span class="b2" style="background:' + t.c2 + '"></span>' +
        '<span class="b3" style="background:' + t.c3 + '"></span></div>' +
        '<em>' + t.nombre + '</em></button>';
    }).join('') + '</div>' +
    '<h2 class="sec">Cómo ves las carreras</h2>' +
    opcion('Modo sin spoilers',
      'Las carreras japonesas se corren sobre las 08:40 de la mañana en España. Oculta ganadores y posiciones hasta que las toques.',
      P.sinSpoilers, 'ponSpoilers(this)') +
    '<h2 class="sec">Qué te llega</h2>' +
    opcion('Noticias de la JRA', 'La categoría principal.', P.categorias.jra !== false, "ponCat(this,'jra')") +
    opcion('Internacional', 'Salidas de caballos japoneses al extranjero e invitados.', P.categorias.internacional !== false, "ponCat(this,'internacional')") +
    opcion('Cría y ventas', 'De dónde salen los caballos que dominarán en dos años.', P.categorias.cria !== false, "ponCat(this,'cria')") +
    opcion('Hípica local (NAR)', 'Más volumen, fuera del circuito principal.', P.categorias.nar === true, "ponCat(this,'nar')") +
    '<h2 class="sec">Tus datos</h2>' +
    '<button class="btn" onclick="exportar()">Exportar mi perfil</button>' +
    '<button class="btn" onclick="borrar()">Borrar todo lo guardado</button>' +
    '<div class="empty" style="padding:8px 20px 20px">Datos de JRA y netkeiba · publicación independiente<br>' +
    'sin relación con la Japan Racing Association</div>';
  document.getElementById('p-ajustes').innerHTML = h;
}

function ponSpoilers(el) {
  el.classList.toggle('on');
  P.sinSpoilers = el.classList.contains('on');
  document.body.classList.toggle('nospo', P.sinSpoilers);
  document.querySelectorAll('.spo').forEach(function (x) { x.classList.remove('shown'); });
  guardarPrefs();
}

function ponCat(el, cat) {
  el.classList.toggle('on');
  P.categorias[cat] = el.classList.contains('on');
  guardarPrefs();
  pintaHoy();
}

function exportar() {
  descargar('keiba-es-perfil.json', JSON.stringify(P, null, 1), 'application/json');
}

function borrar() {
  if (!confirm('¿Borrar tus caballos y ajustes de este dispositivo?')) return;
  try { localStorage.removeItem('keiba-es'); } catch (e) {}
  location.reload();
}

function descargar(nombre, contenido, tipo) {
  var a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([contenido], { type: tipo }));
  a.download = nombre;
  a.click();
  setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
}

/** Genera un .ics con las próximas carreras de los caballos seguidos.
    Mejor que las notificaciones push: sin permisos, sin servidor, nativo. */
function descargarICS() {
  var vistas = {};
  P.seguidos.forEach(function (n) {
    var c = caballo(n);
    if (c && c.proxima) vistas[c.proxima] = (vistas[c.proxima] || []).concat(n);
  });

  var l = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//keiba-es//ES', 'CALSCALE:GREGORIAN'];
  Object.keys(vistas).forEach(function (id) {
    var c = carrera(id);
    if (!c || !c.fecha) return;
    var hh = (c.hora_jst || '15:00').split(':');
    var ini = new Date(Date.UTC(+c.fecha.slice(0,4), +c.fecha.slice(5,7) - 1,
                                +c.fecha.slice(8,10), +hh[0] - 9, +hh[1]));
    var z = function (d) { return d.toISOString().replace(/[-:]|\.\d{3}/g, ''); };
    l.push('BEGIN:VEVENT',
      'UID:' + id + '@keiba-es',
      'DTSTAMP:' + z(new Date()),
      'DTSTART:' + z(ini),
      'DTEND:' + z(new Date(ini.getTime() + 45 * 60000)),
      'SUMMARY:' + c.nombre + ' (' + c.grado + ') — ' + vistas[id].join(', '),
      'DESCRIPTION:' + c.hipodromo + ' · ' + c.distancia + ' m',
      'BEGIN:VALARM', 'TRIGGER:-PT30M', 'ACTION:DISPLAY',
      'DESCRIPTION:' + vistas[id].join(', ') + ' corre en 30 minutos', 'END:VALARM',
      'END:VEVENT');
  });
  l.push('END:VCALENDAR');
  descargar('mis-carreras.ics', l.join('\r\n'), 'text/calendar');
}

/* -------------------------------------------------------- estadísticas */

function pintaStats() {
  var e = D.estadisticas || {};
  var mios = (D.caballos || []).filter(function (c) { return sigue(c.nombre); });
  var h = '';

  if (mios.length) {
    var max = Math.max.apply(null, mios.map(function (c) { return c.victorias || 0; }).concat([1]));
    h += '<h2 class="sec">Mis caballos</h2><div class="kpi">' +
      '<div><b>' + mios.reduce(function (s, c) { return s + (c.g1 || 0); }, 0) + '</b><span>victorias en G1</span></div>' +
      '<div><b>' + mios.length + '</b><span>caballos seguidos</span></div></div>' +
      '<div class="card">' + mios.map(function (c, i) {
        return '<div class="bar"><span class="rk">' + (i + 1) + '</span>' +
          '<span class="nm">' + esc(c.nombre) + '</span>' +
          '<span class="track"><span class="fill" style="width:' +
          Math.round((c.victorias || 0) / max * 100) + '%"></span></span>' +
          '<span class="vl">' + (c.g1 ? c.g1 + ' G1' : (c.victorias || 0) + ' v') + '</span></div>';
      }).join('') + '</div>';
  }

  if ((e.jockeys || []).length) {
    var mx = Math.max.apply(null, e.jockeys.map(function (j) { return j.victorias; }));
    h += '<h2 class="sec">Jockeys líderes</h2><div class="card">' + e.jockeys.map(function (j, i) {
      return '<div class="bar"><span class="rk">' + (i + 1) + '</span>' +
        '<span class="nm">' + esc(j.nombre) + '</span>' +
        '<span class="track"><span class="fill" style="width:' +
        Math.round(j.victorias / mx * 100) + '%"></span></span>' +
        '<span class="vl">' + j.victorias + '</span></div>';
    }).join('') + '</div>';
  }

  if ((e.records || []).length) {
    h += '<h2 class="sec">Récords que conviene saber</h2><div class="card">' +
      e.records.map(function (r) {
        return '<div class="bar"><span class="nm">' + esc(r.que) + '</span>' +
          '<span class="vl" style="width:auto;font-weight:800;color:var(--tx)">' + r.valor + '</span></div>';
      }).join('') + '</div>';
  }

  document.getElementById('p-stats').innerHTML = h ||
    '<div class="empty">Aún no hay estadísticas. Sigue a algún caballo para empezar.</div>';
}

/* ------------------------------------------------------------- buscador */

function pintaBuscar() {
  document.getElementById('p-buscar').innerHTML =
    '<input class="srch" id="q" placeholder="Caballo, jockey, carrera o hipódromo" ' +
    'oninput="buscar(this.value)" autocomplete="off">' +
    '<div id="res"></div>' +
    '<div class="empty" id="res-vacio">El buscador funciona sin conexión: ' +
    'busca sobre los datos ya descargados.</div>';
  setTimeout(function () { var q = document.getElementById('q'); if (q) q.focus(); }, 60);
}

function norm(x) {
  return String(x).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
}

function buscar(q) {
  var res = document.getElementById('res'), vac = document.getElementById('res-vacio');
  q = norm(q.trim());
  if (q.length < 2) { res.innerHTML = ''; vac.style.display = 'block'; return; }
  vac.style.display = 'none';

  var hits = [];
  (D.caballos || []).forEach(function (c) {
    if (norm(c.nombre + ' ' + (c.perfil || '') + ' ' + (c.jockey || '')).indexOf(q) > -1)
      hits.push({ t: c.nombre, s: c.perfil || 'caballo', f: "verCaballo('" + c.nombre + "')" });
  });
  (D.carreras || []).forEach(function (c) {
    if (norm(c.nombre + ' ' + (c.alias || '') + ' ' + (c.hipodromo || '')).indexOf(q) > -1)
      hits.push({ t: c.nombre, s: c.grado + ' · ' + (c.hipodromo || '') + ' · ' + (c.fecha || ''),
                  f: "verCarrera('" + c.id + "')" });
  });
  (D.noticias || []).forEach(function (n) {
    if (norm(n.titular + ' ' + (n.resumen || '')).indexOf(q) > -1)
      hits.push({ t: n.titular, s: 'noticia · ' + (n.fecha_texto || '').slice(0, 10), f: '' });
  });

  if (!hits.length) { res.innerHTML = '<div class="empty">Sin resultados.</div>'; return; }
  res.innerHTML = hits.slice(0, 25).map(function (i) {
    return '<div class="card' + (i.f ? ' tap' : '') + '"' + (i.f ? ' onclick="' + i.f + '"' : '') +
      ' style="display:flex;align-items:center;gap:12px"><div style="flex:1">' +
      '<b style="font-size:15px">' + esc(i.t) + '</b>' +
      '<div style="font-size:12px;color:var(--tx3);margin-top:2px">' + esc(i.s) + '</div></div>' +
      (i.f ? '<span style="color:var(--tx3);font-size:18px">›</span>' : '') + '</div>';
  }).join('');
}

/* ----------------------------------------------------------------- guía */

function pintaGuia() {
  document.getElementById('p-guia').innerHTML =
    '<h2 class="sec">Los grados</h2><p class="cron">G1 es la élite: unas dos docenas al año y son las que ' +
    'deciden campeones. G2 y G3 funcionan casi siempre como escalón previo, la carrera donde un caballo se ' +
    'gana el billete para el G1.</p>' +
    '<h2 class="sec">Las cuotas</h2><p class="cron">El número que acompaña a cada caballo es lo que pagaría ' +
    'un acierto en el tote japonés: cuanto más bajo, más gente ha apostado por él. Aquí sirven como ' +
    'termómetro, no como consejo — te dicen a quién daba por ganador el público antes de correr, que es ' +
    'justo el dato que hace legible una sorpresa.</p>' +
    '<div class="note">Esta app no da pronósticos ni enlaza a casas de apuestas.</div>' +
    '<h2 class="sec">El voto de los aficionados</h2><p class="cron">Dos carreras al año no las llena un ' +
    'comité: las votan los aficionados. La Takarazuka Kinen en junio y la Arima Kinen en diciembre. Por eso ' +
    'se llaman Grand Prix.</p>' +
    '<h2 class="sec">Las triples coronas</h2><p class="cron">Hay dos. La masculina: Satsuki Sho (abril), ' +
    'Tokyo Yushun o Derby (mayo) y Kikuka Sho (octubre). La femenina: Oka Sho (abril), Yushun Himba u Oaks ' +
    '(mayo) y Shuka Sho (octubre).</p>';
}

/* ------------------------------------------------------------- arranque */

function ir(id) {
  PILA = [];
  document.getElementById('hd-main').hidden = false;
  document.getElementById('hd-back').hidden = true;
  document.querySelectorAll('.nb').forEach(function (b) {
    b.classList.toggle('on', b.dataset.p === id);
  });
  mostrar(id);
}

document.querySelectorAll('.nb').forEach(function (b) {
  b.addEventListener('click', function () { ir(b.dataset.p); });
});

// Revelar spoilers al tocar
document.addEventListener('click', function (e) {
  if (!document.body.classList.contains('nospo')) return;
  var s = e.target.closest && e.target.closest('.spo');
  if (s && !s.classList.contains('shown')) {
    e.preventDefault(); e.stopPropagation();
    s.classList.add('shown');
  }
}, true);

function arrancar() {
  cargarPrefs();
  fetch('datos.json?v=' + Date.now())
    .then(function (r) { return r.json(); })
    .then(function (d) {
      D = d;
      pintaHoy(); pintaCalendario(); pintaCaballos(); pintaResultados();
    })
    .catch(function () {
      document.getElementById('p-hoy').innerHTML =
        '<div class="empty">No se han podido cargar los datos.<br>' +
        'Si estás sin conexión y ya habías abierto la app antes, vuelve a intentarlo.</div>';
    });
}

arrancar();

if ('serviceWorker' in navigator) {
  window.addEventListener('load', function () {
    navigator.serviceWorker.register('sw.js').catch(function () {});
  });
}

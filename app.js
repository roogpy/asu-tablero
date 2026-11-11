/* Tablero ASU — plain JS, no framework, no build step.
   Reads data/index.json and data/<fecha>.json produced by collect.py.
   If no real day has been collected yet it falls back to sample/. */

(function () {
  'use strict';

  var TZ = 'America/Asuncion';
  var DELAY_THRESHOLD = 15;

  var STATUS_LABEL = {
    // Used in the Resumen tab, where arrivals and departures are counted together.
    neutral: {
      unknown: 'Sin dato',
      scheduled: 'Programado',
      active: 'En vuelo',
      landed: 'Finalizado',
      cancelled: 'Cancelado',
      incident: 'Incidente',
      diverted: 'Desviado'
    },
    arrival: {
      scheduled: 'Programado',
      active: 'En vuelo',
      landed: 'Aterrizó',
      cancelled: 'Cancelado',
      incident: 'Incidente',
      diverted: 'Desviado'
    },
    departure: {
      scheduled: 'Programado',
      active: 'En vuelo',
      landed: 'Finalizado',
      cancelled: 'Cancelado',
      incident: 'Incidente',
      diverted: 'Desviado'
    }
  };

  // A flight already on the ground is not what the board is for, so the lists
  // leave it out. Cancelled, diverted and incident stay: those still matter to
  // whoever is waiting. The toggle brings the finished ones back.
  var FINISHED = ['landed'];

  var state = {
    base: 'data',
    index: null,
    date: null,
    day: null,
    tab: 'arrivals',
    showFinished: false,
    filters: { arrivals: '', departures: '' }
  };

  var timeFormat = new Intl.DateTimeFormat('es-PY', {
    timeZone: TZ, hour: '2-digit', minute: '2-digit', hour12: false
  });
  var dayFormat = new Intl.DateTimeFormat('es-PY', {
    timeZone: TZ, weekday: 'short', day: '2-digit', month: 'short'
  });

  // ---------------------------------------------------------------- helpers
  function $(id) { return document.getElementById(id); }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    return node;
  }

  function clear(node) { while (node.firstChild) { node.removeChild(node.firstChild); } }

  function remember(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* private mode */ }
  }

  function recall(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }

  function fetchJSON(url) {
    return fetch(url, { cache: 'no-cache' }).then(function (response) {
      if (!response.ok) { throw new Error(url + ' -> ' + response.status); }
      return response.json();
    });
  }

  function hhmm(iso) {
    if (!iso) { return null; }
    var moment = new Date(iso);
    if (isNaN(moment.getTime())) { return null; }
    return timeFormat.format(moment);
  }

  function dayLabel(date) {
    var moment = new Date(date + 'T12:00:00Z');
    if (isNaN(moment.getTime())) { return date; }
    return dayFormat.format(moment).replace('.', '') + ' · ' + date;
  }

  function statusLabel(flight) {
    var table = STATUS_LABEL[flight.direction] || STATUS_LABEL.arrival;
    if (!flight.status) { return 'Sin dato'; }
    return table[flight.status] || flight.status;
  }

  function statusClass(status) {
    var known = ['scheduled', 'active', 'landed', 'cancelled', 'incident', 'diverted'];
    return 'chip chip-' + (known.indexOf(status) >= 0 ? status : 'unknown');
  }

  function placeName(flight) {
    var other = flight.other || {};
    var name = other.airport || other.iata || other.icao;
    if (!name) { return 'Sin dato'; }
    if (other.airport && other.iata) { return other.airport + ' (' + other.iata + ')'; }
    return name;
  }

  // ------------------------------------------------------------- flight row
  function flightRow(flight) {
    var item = el('li', 'flight');

    var scheduled = hhmm(flight.scheduled_utc);
    var time = el('div', 'time', scheduled || '--:--');
    var effective = flight.actual_utc || flight.estimated_utc;
    var effectiveText = hhmm(effective);
    if (effectiveText && effectiveText !== scheduled) {
      var late = el('small', flight.delay_minutes && flight.delay_minutes >= DELAY_THRESHOLD ? 'late' : '');
      late.textContent = (flight.actual_utc ? 'real ' : 'est. ') + effectiveText;
      time.appendChild(late);
    } else if (flight.delay_minutes && flight.delay_minutes >= DELAY_THRESHOLD) {
      time.appendChild(el('small', 'late', '+' + flight.delay_minutes + ' min'));
    }
    item.appendChild(time);

    var head = el('div', 'place');
    head.textContent = (flight.direction === 'arrival' ? 'desde ' : 'hacia ') + placeName(flight);
    item.appendChild(head);

    var chip = el('span', statusClass(flight.status), statusLabel(flight));
    item.appendChild(chip);

    var meta = el('div', 'meta');
    var bits = [];
    var number = flight.flight.iata || flight.flight.icao || 'sin número';
    bits.push(number);
    if (flight.airline && flight.airline.name) { bits.push(flight.airline.name); }
    var asu = flight.asu || {};
    if (asu.gate) { bits.push('Puerta ' + asu.gate); }
    if (asu.terminal) { bits.push('Terminal ' + asu.terminal); }
    if (flight.direction === 'arrival' && asu.baggage) { bits.push('Cinta ' + asu.baggage); }
    if (flight.marketing && flight.marketing.length) {
      bits.push('también ' + flight.marketing.join(', '));
    }
    if (flight.codeshare_of) { bits.push('operado como ' + flight.codeshare_of); }
    bits.forEach(function (bit, position) {
      if (position > 0) { meta.appendChild(el('span', 'sep', '·')); }
      meta.appendChild(document.createTextNode(bit));
    });
    item.appendChild(meta);

    return item;
  }

  function matchesFilter(flight, needle) {
    if (!needle) { return true; }
    var haystack = [
      flight.flight.iata, flight.flight.icao, flight.flight.number,
      flight.airline ? flight.airline.name : '', flight.airline ? flight.airline.iata : '',
      flight.other ? flight.other.airport : '', flight.other ? flight.other.iata : '',
      statusLabel(flight)
    ].join(' ').toLowerCase();
    return haystack.indexOf(needle) >= 0;
  }

  function isFinished(flight) {
    return FINISHED.indexOf(flight.status) >= 0;
  }

  function renderFlights(kind) {
    var list = $('list-' + kind);
    clear(list);
    var flights = (state.day && state.day[kind]) || [];
    var finished = flights.filter(isFinished).length;
    var pending = flights.filter(function (flight) {
      return state.showFinished || !isFinished(flight);
    });
    var needle = state.filters[kind].trim().toLowerCase();
    var shown = pending.filter(function (flight) { return matchesFilter(flight, needle); });

    updateToggle(kind, finished);

    if (!shown.length) {
      var message;
      if (!flights.length) {
        message = 'Sin vuelos para este día.';
      } else if (needle) {
        message = 'Ningún vuelo coincide con el filtro.';
      } else if (finished) {
        message = 'Todos los vuelos de este día ya ' +
          (kind === 'arrivals' ? 'aterrizaron' : 'salieron') +
          '. Tocá “Ver ' + finished + ' finalizados” para verlos.';
      } else {
        message = 'Sin vuelos para este día.';
      }
      list.appendChild(el('li', 'empty', message));
      return;
    }
    shown.forEach(function (flight) { list.appendChild(flightRow(flight)); });
  }

  function updateToggle(kind, finished) {
    var button = $('toggle-' + kind);
    if (!button) { return; }
    if (!finished) {
      button.hidden = true;
      return;
    }
    button.hidden = false;
    button.textContent = state.showFinished
      ? 'Ocultar finalizados'
      : 'Ver ' + finished + ' finalizados';
    button.setAttribute('aria-pressed', state.showFinished ? 'true' : 'false');
  }

  function setShowFinished(value) {
    state.showFinished = value;
    remember('asu.showFinished', value ? '1' : '0');
    renderFlights('arrivals');
    renderFlights('departures');
    describeState();
  }

  // ---------------------------------------------------------------- resumen
  function card(value, label) {
    var box = el('div', 'card');
    box.appendChild(el('div', 'value', value));
    box.appendChild(el('div', 'label', label));
    return box;
  }

  function barBlock(title, rows, total, limit) {
    var block = el('section', 'block');
    block.appendChild(el('h2', null, title));
    var bars = el('div', 'bars');
    var slice = rows.slice(0, limit || 6);
    if (!slice.length) {
      block.appendChild(el('p', 'label', 'Sin datos.'));
      return block;
    }
    var top = slice[0].count || 1;
    slice.forEach(function (row) {
      var line = el('div', 'bar-row');
      line.appendChild(el('div', 'name', row.name));
      var track = el('div', 'bar-track');
      var fill = el('div', 'bar-fill');
      fill.style.width = Math.max(4, Math.round((row.count / top) * 100)) + '%';
      track.appendChild(fill);
      line.appendChild(track);
      var share = total ? ' (' + Math.round((row.count / total) * 100) + '%)' : '';
      line.appendChild(el('div', 'count', row.count + share));
      bars.appendChild(line);
    });
    block.appendChild(bars);
    return block;
  }

  function renderSummary() {
    var panel = $('panel-summary');
    clear(panel);
    if (!state.day) { panel.appendChild(el('p', 'empty', 'Sin datos.')); return; }

    var summary = state.day.summary;
    var cards = el('div', 'cards');
    cards.appendChild(card(summary.arrivals, 'Llegadas'));
    cards.appendChild(card(summary.departures, 'Salidas'));
    cards.appendChild(card(summary.cancelled, 'Cancelados'));
    cards.appendChild(card(summary.delayed, 'Demorados 15+'));
    panel.appendChild(cards);

    var statusRows = Object.keys(summary.by_status.all).map(function (key) {
      return { name: STATUS_LABEL.neutral[key] || key, count: summary.by_status.all[key] };
    }).sort(function (a, b) { return b.count - a.count; });
    panel.appendChild(barBlock('Estado de los vuelos', statusRows, summary.total, 8));
    panel.appendChild(barBlock('Aerolíneas', summary.airlines, summary.total, 8));
    panel.appendChild(barBlock('Orígenes y destinos', summary.places, summary.total, 8));

    var notes = el('section', 'block');
    notes.appendChild(el('h2', null, 'Sobre esta foto'));
    var list = el('div', 'bars');
    list.appendChild(el('div', 'label', 'Tomada: ' + (hhmm(state.day.collected_at) || '—') +
      ' del ' + (state.day.collected_at || '').slice(0, 10) + ' (hora de Asunción)'));
    list.appendChild(el('div', 'label', 'Codeshares unificados: ' + summary.codeshares_merged));
    list.appendChild(el('div', 'label', 'Total de operaciones: ' + summary.total));
    notes.appendChild(list);
    panel.appendChild(notes);
  }

  // -------------------------------------------------------------- historial
  function svgNode(name, attributes) {
    var node = document.createElementNS('http://www.w3.org/2000/svg', name);
    Object.keys(attributes || {}).forEach(function (key) {
      node.setAttribute(key, attributes[key]);
    });
    return node;
  }

  function historyChart(days) {
    var width = 320;
    var height = 150;
    var padLeft = 22;
    var padBottom = 18;
    var padTop = 8;
    var svg = svgNode('svg', {
      'class': 'chart',
      viewBox: '0 0 ' + width + ' ' + height,
      role: 'img',
      'aria-label': 'Vuelos por día'
    });

    var maximum = days.reduce(function (top, day) { return Math.max(top, day.total); }, 1);
    var plotWidth = width - padLeft - 6;
    var plotHeight = height - padTop - padBottom;
    var slot = plotWidth / days.length;
    var barWidth = Math.max(2, Math.min(18, slot - 2));

    svg.appendChild(svgNode('line', {
      'class': 'axis', x1: padLeft, y1: height - padBottom, x2: width - 4, y2: height - padBottom
    }));

    [0, Math.round(maximum / 2), maximum].forEach(function (value) {
      var y = height - padBottom - (value / maximum) * plotHeight;
      var label = svgNode('text', { 'class': 'label', x: 0, y: y + 3 });
      label.textContent = String(value);
      svg.appendChild(label);
    });

    days.forEach(function (day, position) {
      var x = padLeft + position * slot + (slot - barWidth) / 2;
      var totalHeight = (day.total / maximum) * plotHeight;
      svg.appendChild(svgNode('rect', {
        'class': 'bar-total',
        x: x, y: height - padBottom - totalHeight,
        width: barWidth, height: Math.max(1, totalHeight), rx: 2
      }));
      var bad = (day.cancelled || 0) + (day.delayed || 0);
      if (bad > 0) {
        var badHeight = (Math.min(bad, day.total) / maximum) * plotHeight;
        svg.appendChild(svgNode('rect', {
          'class': 'bar-bad',
          x: x, y: height - padBottom - badHeight,
          width: barWidth, height: Math.max(1, badHeight), rx: 2
        }));
      }
      if (days.length <= 10 || position % Math.ceil(days.length / 7) === 0) {
        var tick = svgNode('text', {
          'class': 'label', x: x + barWidth / 2, y: height - 6, 'text-anchor': 'middle'
        });
        tick.textContent = day.date.slice(8) + '/' + day.date.slice(5, 7);
        svg.appendChild(tick);
      }
    });

    return svg;
  }

  function renderHistory() {
    var panel = $('panel-history');
    clear(panel);
    var days = (state.index && state.index.days) || [];
    if (!days.length) {
      panel.appendChild(el('p', 'empty', 'Todavía no hay días guardados.'));
      return;
    }

    var recent = days.slice(-30);
    var totals = recent.reduce(function (acc, day) {
      acc.total += day.total;
      acc.cancelled += day.cancelled;
      acc.delayed += day.delayed;
      return acc;
    }, { total: 0, cancelled: 0, delayed: 0 });

    var cards = el('div', 'cards');
    cards.appendChild(card(recent.length, 'Días guardados'));
    cards.appendChild(card(Math.round(totals.total / recent.length), 'Vuelos por día'));
    cards.appendChild(card(
      totals.total ? Math.round((totals.cancelled / totals.total) * 100) + '%' : '—', 'Cancelados'));
    cards.appendChild(card(
      totals.total ? Math.round((totals.delayed / totals.total) * 100) + '%' : '—', 'Demorados'));
    panel.appendChild(cards);

    var chartBlock = el('section', 'block');
    chartBlock.appendChild(el('h2', null, 'Vuelos por día'));
    chartBlock.appendChild(historyChart(recent));
    var legend = el('div', 'legend');
    legend.appendChild(el('span', 'k-total', 'Total'));
    legend.appendChild(el('span', 'k-bad', 'Cancelados + demorados'));
    chartBlock.appendChild(legend);
    panel.appendChild(chartBlock);

    var tableBlock = el('section', 'block');
    tableBlock.appendChild(el('h2', null, 'Últimos días'));
    var table = el('table', 'table');
    var head = el('thead');
    var headRow = el('tr');
    ['Día', 'Lleg.', 'Sal.', 'Canc.', 'Dem.'].forEach(function (title) {
      headRow.appendChild(el('th', null, title));
    });
    head.appendChild(headRow);
    table.appendChild(head);
    var body = el('tbody');
    recent.slice(-14).reverse().forEach(function (day) {
      var row = el('tr');
      row.appendChild(el('td', null, day.date.slice(5)));
      row.appendChild(el('td', null, day.arrivals));
      row.appendChild(el('td', null, day.departures));
      row.appendChild(el('td', null, day.cancelled));
      row.appendChild(el('td', null, day.delayed));
      body.appendChild(row);
    });
    table.appendChild(body);
    tableBlock.appendChild(table);
    panel.appendChild(tableBlock);
  }

  // ------------------------------------------------------------------ chrome
  function setStatus(message, warn) {
    var line = $('status-line');
    line.textContent = message;
    line.className = 'status-line' + (warn ? ' warn' : '');
  }

  function describeState() {
    var bits = [];
    if (state.day) {
      var summary = state.day.summary;
      var open = state.day.arrivals.concat(state.day.departures)
        .filter(function (flight) { return !isFinished(flight); }).length;
      bits.push(
        state.showFinished || open === summary.total
          ? summary.total + ' operaciones'
          : open + ' pendientes de ' + summary.total
      );
      if (state.day.collected_at) {
        bits.push('tomado ' + (hhmm(state.day.collected_at) || '') + ' hs');
      }
    }
    if (state.base === 'sample') { bits.push('DATOS DE MUESTRA'); }
    if (!navigator.onLine) { bits.push('sin conexión'); }
    setStatus(bits.join(' · ') || 'Sin datos', state.base === 'sample' || !navigator.onLine);
  }

  function showTab(name) {
    state.tab = name;
    remember('asu.tab', name);
    ['arrivals', 'departures', 'summary', 'history'].forEach(function (key) {
      var panel = $('panel-' + key);
      if (key === name) { panel.removeAttribute('hidden'); panel.classList.add('is-active'); }
      else { panel.setAttribute('hidden', ''); panel.classList.remove('is-active'); }
    });
    Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (tab) {
      var active = tab.getAttribute('data-tab') === name;
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    if (name === 'summary') { renderSummary(); }
    if (name === 'history') { renderHistory(); }
    window.scrollTo(0, 0);
  }

  function fillDayPicker() {
    var select = $('day-select');
    clear(select);
    var days = (state.index && state.index.days) || [];
    days.slice().reverse().forEach(function (day) {
      var option = el('option', null, dayLabel(day.date));
      option.value = day.date;
      select.appendChild(option);
    });
    select.value = state.date;
    updateStepButtons();
  }

  function updateStepButtons() {
    var days = (state.index && state.index.days) || [];
    var position = days.map(function (day) { return day.date; }).indexOf(state.date);
    $('prev-day').disabled = position <= 0;
    $('next-day').disabled = position < 0 || position >= days.length - 1;
  }

  function stepDay(delta) {
    var days = (state.index && state.index.days) || [];
    var dates = days.map(function (day) { return day.date; });
    var position = dates.indexOf(state.date) + delta;
    if (position < 0 || position >= dates.length) { return; }
    loadDay(dates[position]);
  }

  // -------------------------------------------------------------- data load
  function loadDay(date) {
    setStatus('Cargando ' + date + '…');
    return fetchJSON(state.base + '/' + date + '.json').then(function (day) {
      state.date = date;
      state.day = day;
      $('day-select').value = date;
      updateStepButtons();
      renderFlights('arrivals');
      renderFlights('departures');
      if (state.tab === 'summary') { renderSummary(); }
      if (state.tab === 'history') { renderHistory(); }
      describeState();
    }).catch(function (error) {
      setStatus('No se pudo cargar el día ' + date + '.', true);
      console.error(error);
    });
  }

  function loadIndex() {
    return fetchJSON('data/index.json').then(function (index) {
      if (index && index.days && index.days.length) { return { base: 'data', index: index }; }
      throw new Error('empty index');
    }).catch(function () {
      return fetchJSON('sample/index.json').then(function (index) {
        return { base: 'sample', index: index };
      });
    });
  }

  function start() {
    Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (tab) {
      tab.addEventListener('click', function () { showTab(tab.getAttribute('data-tab')); });
    });
    $('day-select').addEventListener('change', function (event) { loadDay(event.target.value); });
    $('prev-day').addEventListener('click', function () { stepDay(-1); });
    $('next-day').addEventListener('click', function () { stepDay(1); });
    ['arrivals', 'departures'].forEach(function (kind) {
      $('filter-' + kind).addEventListener('input', function (event) {
        state.filters[kind] = event.target.value;
        renderFlights(kind);
      });
      $('toggle-' + kind).addEventListener('click', function () {
        setShowFinished(!state.showFinished);
      });
    });
    state.showFinished = recall('asu.showFinished') === '1';
    window.addEventListener('online', describeState);
    window.addEventListener('offline', describeState);

    var savedTab = recall('asu.tab');
    if (savedTab) { showTab(savedTab); }

    loadIndex().then(function (result) {
      state.base = result.base;
      state.index = result.index;
      var days = result.index.days || [];
      if (!days.length) { setStatus('Todavía no hay datos recolectados.', true); return; }
      // A daily board always opens on the newest day; browsing back is a
      // deliberate act with the picker, not something to remember.
      var dates = days.map(function (day) { return day.date; });
      state.date = dates[dates.length - 1];
      fillDayPicker();
      return loadDay(state.date);
    }).catch(function (error) {
      setStatus('No se pudieron cargar los datos. Probá de nuevo con conexión.', true);
      console.error(error);
    });

    if ('serviceWorker' in navigator) {
      window.addEventListener('load', function () {
        navigator.serviceWorker.register('sw.js').catch(function (error) {
          console.warn('service worker no registrado', error);
        });
      });
    }
  }

  document.addEventListener('DOMContentLoaded', start);
}());

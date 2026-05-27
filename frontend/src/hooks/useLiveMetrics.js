import { useEffect, useRef, useState, useCallback } from "react";

/**
 * Single shared WebSocket connection for metrics.
 * Prevents the reconnect storm that was happening (dozens of
 * connect/disconnect per second when React re-renders).
 */
let _metricsWs = null;
let _metricsListeners = new Set();
let _metricsReconnectTimer = null;

function _ensureMetricsWs() {
  if (_metricsWs && _metricsWs.readyState <= 1) return; // CONNECTING or OPEN

  const wsUrl = (window.location.protocol === "https:" ? "wss:" : "ws:") +
                "//" + window.location.host + "/ws/metrics";

  try {
    _metricsWs = new WebSocket(wsUrl);
    _metricsWs.onmessage = (ev) => {
      _metricsListeners.forEach((fn) => fn(ev.data));
    };
    _metricsWs.onclose = () => {
      _metricsWs = null;
      if (_metricsReconnectTimer) clearTimeout(_metricsReconnectTimer);
      _metricsReconnectTimer = setTimeout(_ensureMetricsWs, 3000);
    };
    _metricsWs.onerror = () => {}; // onclose will fire
  } catch (e) {
    if (_metricsReconnectTimer) clearTimeout(_metricsReconnectTimer);
    _metricsReconnectTimer = setTimeout(_ensureMetricsWs, 3000);
  }
}

export function useLiveMetrics() {
  const [snapshot, setSnapshot] = useState(null);
  const [history, setHistory] = useState([]);
  const [status, setStatus] = useState("connecting");

  useEffect(() => {
    function handler(raw) {
      try {
        const msg = JSON.parse(raw);
        if (msg.type === "snapshot" && msg.data) {
          setSnapshot(msg.data);
          setHistory((h) => [...h, msg.data].slice(-120));
          setStatus("live");
        }
      } catch {}
    }

    _metricsListeners.add(handler);
    _ensureMetricsWs();

    return () => {
      _metricsListeners.delete(handler);
    };
  }, []);

  return { snapshot, history, status };
}

/* ── Events WebSocket (same shared pattern) ── */
let _eventsWs = null;
let _eventsListeners = new Set();
let _eventsReconnectTimer = null;

function _ensureEventsWs() {
  if (_eventsWs && _eventsWs.readyState <= 1) return;

  const wsUrl = (window.location.protocol === "https:" ? "wss:" : "ws:") +
                "//" + window.location.host + "/ws/events";

  try {
    _eventsWs = new WebSocket(wsUrl);
    _eventsWs.onmessage = (ev) => {
      _eventsListeners.forEach((fn) => fn(ev.data));
    };
    _eventsWs.onclose = () => {
      _eventsWs = null;
      if (_eventsReconnectTimer) clearTimeout(_eventsReconnectTimer);
      _eventsReconnectTimer = setTimeout(_ensureEventsWs, 3000);
    };
    _eventsWs.onerror = () => {};
  } catch (e) {
    if (_eventsReconnectTimer) clearTimeout(_eventsReconnectTimer);
    _eventsReconnectTimer = setTimeout(_ensureEventsWs, 3000);
  }
}

export function useEventStream() {
  const [events, setEvents] = useState([]);
  const [rlDecisions, setRlDecisions] = useState([]);

  useEffect(() => {
    function handler(raw) {
      try {
        const msg = JSON.parse(raw);
        if (msg.type === "events" && Array.isArray(msg.data))
          setEvents((c) => [...msg.data, ...c].slice(0, 100));
        if (msg.type === "rl-decisions" && Array.isArray(msg.data))
          setRlDecisions((c) => [...msg.data, ...c].slice(0, 100));
      } catch {}
    }

    _eventsListeners.add(handler);
    _ensureEventsWs();

    return () => {
      _eventsListeners.delete(handler);
    };
  }, []);

  return { events, rlDecisions };
}

/* ── REST polling ── */
export function usePolling(path, ms = 5000) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let cancelled = false;
    async function tick() {
      try {
        const r = await fetch(path);
        if (r.ok && !cancelled) setData(await r.json());
      } catch {}
    }
    tick();
    const t = setInterval(tick, ms);
    return () => { cancelled = true; clearInterval(t); };
  }, [path, ms]);
  return data;
}

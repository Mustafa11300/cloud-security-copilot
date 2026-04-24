import { useState, useEffect, useRef, useCallback } from 'react';

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "wss://cloudgaurd-backend.onrender.com/ws/war-room";
const HEALTH_URL = process.env.NEXT_PUBLIC_API_BASE || "https://cloudgaurd-backend.onrender.com";
const MAX_EVENTS = 200;
const MAX_AMBER_ALERTS = 50;
const MAX_NEGOTIATIONS = 120;

/**
 * Wake up the Render free-tier backend with an HTTP ping before opening
 * the WebSocket. Returns true if the backend is alive, false otherwise.
 */
async function wakeBackend() {
  try {
    const res = await fetch(`${HEALTH_URL}/`, { method: "GET", signal: AbortSignal.timeout(30000) });
    return res.ok;
  } catch {
    return false;
  }
}

export function useSovereignStream() {
  const [isConnected, setIsConnected] = useState(false);
  const [lastError, setLastError] = useState(null);
  
  const [jScore, setJScore] = useState(1.0);
  const [wR, setWr] = useState(0.5);
  const [wC, setWc] = useState(0.5);
  
  const [events, setEvents] = useState([]);
  const [topology, setTopology] = useState([]);
  const [amberAlerts, setAmberAlerts] = useState([]);
  const [negotiations, setNegotiations] = useState([]);
  const [backoffStatus, setBackoffStatus] = useState({ active: false, reason: '', retryAfterS: 0 });
  
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const pingIntervalRef = useRef(null);
  const backoffResetTimeoutRef = useRef(null);
  const reconnectAttemptsRef = useRef(0);
  const manualCloseRef = useRef(false);

  // ── Batch accumulator (uses a simple timer instead of rAF) ─────────────
  const pendingRef = useRef({
    events: [],
    amberAlerts: [],
    negotiations: [],
    topology: null,
    jScore: null,
    wR: null,
    wC: null,
    backoff: null,
  });
  const flushTimerRef = useRef(null);

  const flushPending = useCallback(() => {
    flushTimerRef.current = null;
    const p = pendingRef.current;

    if (p.events.length > 0) {
      const batch = p.events.splice(0);
      setEvents(prev => {
        const existingIds = new Set(prev.map(e => e.event_id).filter(Boolean));
        const unique = batch.filter(e => !e.event_id || !existingIds.has(e.event_id));
        return [...prev, ...unique].slice(-MAX_EVENTS);
      });
    }

    if (p.amberAlerts.length > 0) {
      const batch = p.amberAlerts.splice(0);
      setAmberAlerts(prev => {
        const existingIds = new Set(prev.map(e => e.event_id).filter(Boolean));
        const unique = batch.filter(e => !e.event_id || !existingIds.has(e.event_id));
        return [...prev, ...unique].slice(-MAX_AMBER_ALERTS);
      });
    }

    if (p.negotiations.length > 0) {
      const batch = p.negotiations.splice(0);
      setNegotiations(prev => {
        const existingIds = new Set(prev.map(e => e.event_id).filter(Boolean));
        const unique = batch.filter(e => !e.event_id || !existingIds.has(e.event_id));
        return [...prev, ...unique].slice(-MAX_NEGOTIATIONS);
      });
    }

    if (p.topology) {
      setTopology(p.topology);
      p.topology = null;
    }

    if (typeof p.jScore === 'number') {
      setJScore(p.jScore);
      p.jScore = null;
    }

    if (typeof p.wR === 'number') {
      setWr(p.wR);
      p.wR = null;
    }

    if (typeof p.wC === 'number') {
      setWc(p.wC);
      p.wC = null;
    }

    if (p.backoff) {
      setBackoffStatus(p.backoff);
      clearTimeout(backoffResetTimeoutRef.current);
      const resetInMs = Math.max((p.backoff.retryAfterS || 5) * 1000, 1000);
      backoffResetTimeoutRef.current = setTimeout(() => {
        setBackoffStatus({ active: false, reason: '', retryAfterS: 0 });
      }, resetInMs);
      p.backoff = null;
    }
  }, []);

  const scheduleFlush = useCallback(() => {
    if (!flushTimerRef.current) {
      flushTimerRef.current = setTimeout(flushPending, 50);
    }
  }, [flushPending]);

  const ingestEvent = useCallback((data, includeInFeed = true) => {
    if (!data || typeof data !== 'object') return;

    const type = data.event_type;
    if (!type || type === 'Heartbeat') return;

    const body = data.message_body || {};
    const p = pendingRef.current;

    if (includeInFeed) {
      p.events.push(data);
    }

    if (typeof data.j_score === 'number') p.jScore = data.j_score;
    if (typeof data.w_R === 'number') p.wR = data.w_R;
    if (typeof data.w_C === 'number') p.wC = data.w_C;

    if (type === 'Negotiation' || type === 'NarrativeChunk' || type === 'TickerUpdate') {
      p.negotiations.push(data);
    }

    if (type === 'ForecastSignal' && body.type === 'Amber_Alert') {
      p.amberAlerts.push(data);
    }

    if (type === 'TopologySync' && Array.isArray(body.resources)) {
      p.topology = body.resources;
    }

    if (type === 'SwarmCoolingDown') {
      p.backoff = {
        active: true,
        reason: body.reason || 'Swarm cooling down',
        retryAfterS: Number(body.retry_after_s || 5),
      };
    }

    scheduleFlush();
  }, [scheduleFlush]);

  const connect = useCallback(async () => {
    if (wsRef.current?.readyState === WebSocket.OPEN || wsRef.current?.readyState === WebSocket.CONNECTING) {
      return;
    }

    // Wake up the Render free-tier backend before attempting WebSocket upgrade.
    // The HTTP request will trigger a cold start (~10-30s) if the service is asleep.
    const isAlive = await wakeBackend();
    if (!isAlive) {
      // Backend is not responding — schedule a retry instead of opening a dead WS
      const backoffMs = Math.min(3000 * Math.pow(2, reconnectAttemptsRef.current), 30000);
      reconnectAttemptsRef.current++;
      setLastError(new Error("Backend is waking up — retrying..."));
      reconnectTimeoutRef.current = setTimeout(connect, backoffMs);
      return;
    }
    
    try {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        setLastError(null);
        reconnectAttemptsRef.current = 0;
        
        // Keepalive ping expected by backend is a raw string "ping".
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send('ping');
          }
        }, 20000);
      };

      ws.onmessage = (message) => {
        try {
          const data = JSON.parse(message.data);

          if (data.event_type === 'BufferReplay') {
            const replayEvents = data.message_body?.events;
            if (Array.isArray(replayEvents)) {
              replayEvents.forEach((event) => ingestEvent(event, true));
            }
            return;
          }

          ingestEvent(data, true);
        } catch (e) {
          setLastError(e);
        }
      };

      ws.onclose = () => {
        setIsConnected(false);
        wsRef.current = null;
        clearInterval(pingIntervalRef.current);

        if (manualCloseRef.current) {
          return;
        }
        
        // Exponential backoff (min 3s for Render cold starts)
        const backoffMs = Math.min(3000 * Math.pow(2, reconnectAttemptsRef.current), 30000);
        reconnectAttemptsRef.current++;
        
        reconnectTimeoutRef.current = setTimeout(connect, backoffMs);
      };

      ws.onerror = (err) => {
        setLastError(err);
      };
      
    } catch (err) {
      setLastError(err);
    }
  }, [ingestEvent]);

  useEffect(() => {
    manualCloseRef.current = false;
    connect();
    
    return () => {
      manualCloseRef.current = true;
      if (wsRef.current) {
        wsRef.current.close();
      }
      clearTimeout(reconnectTimeoutRef.current);
      clearInterval(pingIntervalRef.current);
      clearTimeout(backoffResetTimeoutRef.current);
      clearTimeout(flushTimerRef.current);
    };
  }, [connect]);

  return { isConnected, events, jScore, wR, wC, topology, amberAlerts, negotiations, backoffStatus, lastError };
}

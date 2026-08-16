import React, { useEffect, useRef, useState } from 'react';
import { Terminal as XTerm } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { Terminal as TerminalIcon, Copy, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

export function Terminal({ sessionName, onCopy }) {
  const terminalRef = useRef(null);
  const termInstanceRef = useRef(null);
  const fitAddonRef = useRef(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!terminalRef.current) return;

    // Initialize xterm
    const term = new XTerm({
      cursorBlink: true,
      fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      fontSize: 13,
      lineHeight: 1.35,
      theme: {
        background: '#030712',
        foreground: '#f1f5f9',
        cursor: '#38bdf8',
        selectionBackground: 'rgba(56, 189, 248, 0.3)',
        black: '#0f172a',
        red: '#f43f5e',
        green: '#10b981',
        yellow: '#f59e0b',
        blue: '#3b82f6',
        magenta: '#d946ef',
        cyan: '#06b6d4',
        white: '#f8fafc',
      },
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(terminalRef.current);
    
    try {
      fitAddon.fit();
    } catch (e) {}

    termInstanceRef.current = term;
    fitAddonRef.current = fitAddon;

    term.writeln(`\x1b[36m⚡ Attaching to in-browser tmux session: ${sessionName}...\x1b[0m\r\n`);

    // Keystroke forwarding
    const dataListener = term.onData((data) => {
      fetch(`/api/terminals/${sessionName}/input`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ input: data }),
      }).catch(() => {});
    });

    // Stream SSE terminal
    const es = new EventSource(`/api/terminals/${sessionName}/stream`);
    es.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload && payload.output) {
          setConnected(true);
          term.clear();
          term.write(payload.output.replace(/\r?\n/g, '\r\n'));
        }
      } catch (err) {
        term.write(event.data);
      }
    };

    es.onerror = () => {
      setConnected(false);
    };

    const handleResize = () => {
      try {
        fitAddon.fit();
        fetch(`/api/terminals/${sessionName}/resize`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cols: term.cols, rows: term.rows }),
        }).catch(() => {});
      } catch (e) {}
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      dataListener.dispose();
      es.close();
      term.dispose();
    };
  }, [sessionName]);

  const sendKey = (key) => {
    fetch(`/api/terminals/${sessionName}/input`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ input: key }),
    }).catch(() => {});
  };

  return (
    <div className="rounded-xl overflow-hidden border border-border/80 bg-zinc-950 shadow-2xl flex flex-col">
      {/* Terminal Header Toolbar */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-zinc-900/90 border-b border-border/60">
        <div className="flex items-center gap-2.5 font-mono text-xs">
          <TerminalIcon className="w-4 h-4 text-sky-400" />
          <span className="text-zinc-200 font-semibold">{sessionName}</span>
          {connected ? (
            <Badge variant="success" className="text-[10px] h-5 py-0 px-2">
              ● LIVE STREAMING
            </Badge>
          ) : (
            <Badge variant="warning" className="text-[10px] h-5 py-0 px-2">
              CONNECTING
            </Badge>
          )}
        </div>

        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => sendKey('\x03')} className="h-7 text-xs px-2.5">
            Ctrl+C
          </Button>
          <Button variant="secondary" size="sm" onClick={() => sendKey('\r')} className="h-7 text-xs px-2.5">
            Enter
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => onCopy && onCopy(`tmux attach -t ${sessionName}`)}
            className="h-7 text-xs px-2.5 gap-1.5"
          >
            <Copy className="w-3 h-3" />
            SSH Command
          </Button>
        </div>
      </div>

      {/* Terminal Viewport */}
      <div ref={terminalRef} className="p-3 bg-zinc-950 min-h-[340px]" />
    </div>
  );
}

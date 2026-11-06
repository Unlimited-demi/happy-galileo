import React, { useState, useEffect, useRef } from 'react';
import {
  Play,
  Pause,
  SkipBack,
  SkipForward,
  Terminal,
  Cpu,
  GitBranch,
  ShieldAlert,
  CheckCircle2,
  Clock,
  Copy,
  Check,
  Radio,
  FileCode2,
  Sparkles,
  RefreshCw,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';

export function IncidentFlightRecorder({ incidentId, incident, onCopy }) {
  const [flightRecord, setFlightRecord] = useState(null);
  const [loading, setLoading] = useState(true);
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const [copiedCode, setCopiedCode] = useState(false);
  const timerRef = useRef(null);

  // Fetch structured flight record from Hub API
  const fetchFlightRecord = async () => {
    if (!incidentId) return;
    try {
      setLoading(true);
      const res = await fetch(`/api/incidents/${encodeURIComponent(incidentId)}/flight-record`);
      if (res.ok) {
        const data = await res.json();
        if (data.flight_record) {
          setFlightRecord(data.flight_record);
          const steps = data.flight_record.timeline || [];
          // Default to the last step or active step
          if (steps.length > 0) {
            setCurrentStepIndex(steps.length - 1);
          }
        }
      }
    } catch (err) {
      console.error('[FlightRecorder] Failed to fetch flight record:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchFlightRecord();
  }, [incidentId]);

  // Automated playback loop
  useEffect(() => {
    if (!isPlaying || !flightRecord) return;
    const steps = flightRecord.timeline || [];
    if (steps.length === 0) return;

    const intervalMs = 2600 / playbackSpeed;
    timerRef.current = setInterval(() => {
      setCurrentStepIndex((prev) => {
        if (prev >= steps.length - 1) {
          setIsPlaying(false);
          return prev;
        }
        return prev + 1;
      });
    }, intervalMs);

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [isPlaying, playbackSpeed, flightRecord]);

  if (loading && !flightRecord) {
    return (
      <div className="flex flex-col items-center justify-center p-12 text-muted-foreground text-xs gap-3">
        <RefreshCw className="w-5 h-5 animate-spin text-sky-400" />
        <span>Initializing Flight Recorder & Telemetry Stream...</span>
      </div>
    );
  }

  const timeline = flightRecord?.timeline || [];
  const currentStep = timeline[currentStepIndex] || timeline[0] || {};
  const totalSteps = timeline.length;
  const isComplete = flightRecord?.status === 'COMPLETED';
  const isRunning = flightRecord?.status === 'RUNNING';

  const handleCopy = (text) => {
    if (onCopy) {
      onCopy(text);
    } else {
      navigator.clipboard.writeText(text);
    }
    setCopiedCode(true);
    setTimeout(() => setCopiedCode(false), 2000);
  };

  const formatOffset = (seconds = 0) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `+${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}s`;
  };

  return (
    <div className="space-y-4 pt-1">
      {/* Flight Control Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-3.5 rounded-xl bg-zinc-950/90 border border-border/80 shadow-inner">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-sky-500/10 border border-sky-500/30 flex items-center justify-center text-sky-400 shadow-sm">
            <Radio className={`w-4 h-4 ${isRunning ? 'animate-pulse text-amber-400' : ''}`} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold text-slate-100">OpenCode Autonomous Flight Recorder</span>
              <Badge
                variant={isComplete ? 'success' : isRunning ? 'warning' : 'outline'}
                className="text-[10px] uppercase font-mono tracking-wide px-1.5 py-0.2"
              >
                {isComplete ? '✓ Verified Complete' : isRunning ? '● Live Telemetry' : flightRecord?.status || 'Active'}
              </Badge>
            </div>
            <div className="text-[11px] text-muted-foreground font-mono mt-0.5">
              Worker: <span className="text-slate-300">opencode-{incidentId}</span> • Target: <span className="text-sky-300">{flightRecord?.service_name || incident?.service_name}</span> ({flightRecord?.source_node || incident?.source_node})
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div className="text-right font-mono text-xs pr-2 hidden sm:block">
            <div className="text-slate-400 text-[10px] uppercase">Mission Elapsed</div>
            <div className="text-slate-200 font-bold">{formatOffset(currentStep.offset_seconds || 0)}</div>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={fetchFlightRecord}
            className="h-8 text-xs gap-1.5 border-border/70 bg-card/60"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Sync
          </Button>
        </div>
      </div>

      {/* Time-Travel Replay Scrubber & Control Bar */}
      <div className="p-3.5 rounded-xl bg-card/70 border border-border/80 space-y-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <Button
              variant="outline"
              size="icon"
              className="h-7 w-7 border-border/60"
              onClick={() => {
                setIsPlaying(false);
                setCurrentStepIndex((prev) => Math.max(0, prev - 1));
              }}
              disabled={currentStepIndex <= 0}
              title="Previous Step"
            >
              <SkipBack className="w-3.5 h-3.5" />
            </Button>
            <Button
              variant={isPlaying ? 'amber' : 'default'}
              size="sm"
              className="h-7 px-3 text-xs gap-1.5 font-semibold"
              onClick={() => {
                if (currentStepIndex >= totalSteps - 1 && !isPlaying) {
                  setCurrentStepIndex(0);
                }
                setIsPlaying(!isPlaying);
              }}
            >
              {isPlaying ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
              {isPlaying ? 'Pause' : currentStepIndex >= totalSteps - 1 ? 'Replay' : 'Play'}
            </Button>
            <Button
              variant="outline"
              size="icon"
              className="h-7 w-7 border-border/60"
              onClick={() => {
                setIsPlaying(false);
                setCurrentStepIndex((prev) => Math.min(totalSteps - 1, prev + 1));
              }}
              disabled={currentStepIndex >= totalSteps - 1}
              title="Next Step"
            >
              <SkipForward className="w-3.5 h-3.5" />
            </Button>
          </div>

          {/* Speed Controls */}
          <div className="flex items-center gap-1 bg-zinc-950/80 p-0.5 rounded-lg border border-border/60 text-xs font-mono">
            {[1, 2, 4].map((spd) => (
              <button
                key={spd}
                type="button"
                onClick={() => setPlaybackSpeed(spd)}
                className={`px-2 py-0.5 rounded text-[11px] font-semibold transition-colors ${
                  playbackSpeed === spd
                    ? 'bg-sky-500 text-white shadow-sm'
                    : 'text-muted-foreground hover:text-slate-200'
                }`}
              >
                {spd}x
              </button>
            ))}
          </div>

          {/* Step Indicator */}
          <div className="text-xs font-mono text-slate-300">
            Step <span className="font-bold text-sky-400">{currentStepIndex + 1}</span> of{' '}
            <span className="font-bold">{totalSteps}</span>
          </div>
        </div>

        {/* Clickable Step Segments Progress */}
        <div className="grid grid-cols-5 gap-1.5 pt-1">
          {timeline.map((st, idx) => {
            const isCurrent = idx === currentStepIndex;
            const isPassed = idx < currentStepIndex;
            return (
              <button
                key={st.step}
                type="button"
                onClick={() => {
                  setIsPlaying(false);
                  setCurrentStepIndex(idx);
                }}
                className={`group relative h-2.5 rounded-full transition-all duration-300 text-left ${
                  isCurrent
                    ? 'bg-sky-400 ring-2 ring-sky-400/40 shadow-[0_0_8px_rgba(56,189,248,0.5)]'
                    : isPassed
                    ? 'bg-emerald-500 hover:bg-emerald-400'
                    : 'bg-zinc-800 hover:bg-zinc-700'
                }`}
                title={`Step ${idx + 1}: ${st.title}`}
              />
            );
          })}
        </div>
      </div>

      {/* Active Step Details Card */}
      {currentStep && (
        <div className="rounded-xl bg-zinc-950 border border-border/80 overflow-hidden shadow-lg space-y-3 p-4">
          {/* Phase Badge & Step Title */}
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/40 pb-3">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="text-[10px] font-mono tracking-wider bg-sky-950/40 border-sky-500/40 text-sky-300 uppercase">
                  {currentStep.phase || 'EXECUTION'}
                </Badge>
                <span className="text-[11px] font-mono text-muted-foreground">
                  {formatOffset(currentStep.offset_seconds || 0)}
                </span>
              </div>
              <h4 className="text-sm font-bold text-slate-100 flex items-center gap-2">
                {currentStep.title}
              </h4>
            </div>

            <div className="flex items-center gap-1.5 text-xs font-mono text-emerald-400 bg-emerald-500/10 px-2.5 py-1 rounded-md border border-emerald-500/20">
              <CheckCircle2 className="w-3.5 h-3.5" />
              <span>Step Status: {currentStep.status || 'Success'}</span>
            </div>
          </div>

          {/* Agent Thought / Cognitive Blueprint */}
          {currentStep.agent_thought && (
            <div className="rounded-lg bg-sky-950/20 border border-sky-500/20 p-3.5 space-y-1">
              <div className="text-[11px] font-semibold text-sky-300 uppercase tracking-wider flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-amber-400" />
                <span>Agent Reasoning & Thought</span>
              </div>
              <p className="text-xs text-slate-200 leading-relaxed font-sans">
                {currentStep.agent_thought}
              </p>
            </div>
          )}

          {/* Command Executed */}
          {currentStep.command && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-[11px] text-muted-foreground uppercase tracking-wider font-semibold">
                <span className="flex items-center gap-1">
                  <Terminal className="w-3 h-3 text-slate-400" /> Executed Command
                </span>
                <button
                  type="button"
                  onClick={() => handleCopy(currentStep.command)}
                  className="text-xs text-slate-400 hover:text-slate-100 flex items-center gap-1 transition-colors"
                >
                  {copiedCode ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                  {copiedCode ? 'Copied' : 'Copy'}
                </button>
              </div>
              <div className="rounded-lg bg-black/80 border border-border/80 px-3.5 py-2.5 font-mono text-xs text-amber-300 selection:bg-amber-500/30 overflow-x-auto whitespace-pre">
                $ {currentStep.command}
              </div>
            </div>
          )}

          {/* Terminal STDOUT / Execution Stream */}
          {currentStep.stdout && (
            <div className="space-y-1.5">
              <div className="text-[11px] text-muted-foreground uppercase tracking-wider font-semibold flex items-center gap-1">
                <Terminal className="w-3 h-3 text-slate-400" /> Terminal Output / Telemetry Stream
              </div>
              <div className="rounded-lg bg-black border border-border/80 p-3.5 font-mono text-xs text-emerald-300/90 max-h-56 overflow-y-auto whitespace-pre-wrap leading-relaxed shadow-inner">
                {currentStep.stdout}
              </div>
            </div>
          )}

          {/* Git Code Diff (If produced at this step) */}
          {currentStep.git_diff && (
            <div className="space-y-1.5 pt-1">
              <div className="text-[11px] text-muted-foreground uppercase tracking-wider font-semibold flex items-center gap-1">
                <FileCode2 className="w-3.5 h-3.5 text-sky-400" /> Staged Code Diff
              </div>
              <div className="rounded-lg bg-black border border-border/80 p-3.5 font-mono text-xs text-slate-300 max-h-48 overflow-y-auto whitespace-pre-wrap leading-relaxed">
                {currentStep.git_diff}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Stepper Summary Timeline */}
      <div className="rounded-xl bg-card/40 border border-border/60 p-3 space-y-2">
        <div className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider px-1">
          Remediation Execution Timeline
        </div>
        <div className="divide-y divide-border/40">
          {timeline.map((st, idx) => {
            const isSelected = idx === currentStepIndex;
            return (
              <div
                key={st.step}
                onClick={() => {
                  setIsPlaying(false);
                  setCurrentStepIndex(idx);
                }}
                className={`p-2.5 rounded-lg flex items-center justify-between cursor-pointer transition-colors ${
                  isSelected
                    ? 'bg-sky-500/15 border border-sky-500/30'
                    : 'hover:bg-muted/40'
                }`}
              >
                <div className="flex items-center gap-2.5">
                  <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-mono font-bold ${
                    isSelected
                      ? 'bg-sky-400 text-black'
                      : 'bg-zinc-800 text-slate-300'
                  }`}>
                    {st.step}
                  </div>
                  <div>
                    <div className="text-xs font-semibold text-slate-200">{st.title}</div>
                    <div className="text-[10px] text-muted-foreground font-mono">{st.phase}</div>
                  </div>
                </div>
                <div className="text-[11px] font-mono text-muted-foreground">
                  {formatOffset(st.offset_seconds || 0)}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

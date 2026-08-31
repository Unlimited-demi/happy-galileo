"""
Universal Heuristic Anomaly Classifier for AI-Ops.
Uses syntactic grammar analysis and structural anomaly heuristics to detect
unhandled exceptions, HTTP 5xx/4xx upstream errors, stack traces, and crash signals
across ANY programming language, SDK, or framework without hardcoding vendor names.
"""

import re
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple


def _load_pattern_file(path: Path) -> List[str]:
    """Load one regex per line; '#' lines are comments. Invalid regexes are skipped."""
    patterns = []
    try:
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    re.compile(line)
                    patterns.append(line)
                except re.error:
                    print(f"[classifier] Skipping invalid regex in {path.name}: {line}")
    except Exception:
        pass
    return patterns


class AnomalyClassifier:
    """Universal grammar-based anomaly detector and classifier.

    Operators can extend classification WITHOUT code changes by dropping regex
    files into the devctl state directory (~/.devctl by default):
      - noise_patterns.txt : one regex per line; matching log lines are IGNORED
      - error_patterns.txt : one regex per line; matching log lines are flagged
        as "Operator-Defined Error" anomalies
    Files are re-read at most every 60s.
    """

    _custom_noise: List[str] = []
    _custom_errors: List[str] = []
    _custom_loaded_at: float = 0.0

    @classmethod
    def _refresh_custom_patterns(cls):
        import time
        if time.time() - cls._custom_loaded_at < 60:
            return
        cls._custom_loaded_at = time.time()
        try:
            from devctl.core.config import Config
            state_dir = Config.DEVCTL_STATE_DIR
        except Exception:
            return
        cls._custom_noise = _load_pattern_file(state_dir / "noise_patterns.txt")
        cls._custom_errors = _load_pattern_file(state_dir / "error_patterns.txt")

    # 1. Structural Noise Patterns to Discard (Routine access traffic, self-logs, scanner noise)
    NOISE_PATTERNS = [
        # Standard HTTP Server Access Logs (Combined/Common log formats: "... METHOD URI ..." 200)
        r'"\s*(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|CONNECT)\s+.*"\s+[1-4]\d\d\s+',
        r'handled request.*"status":\s*[1-4]\d\d',
        r'HTTP/\d\.\d"\s+[1-4]\d\d',
        r'\[HTTP\]\s+\d{3}\s+',
        
        # Self-daemon Monitoring Output (Prevents feedback loops)
        r'AI-Ops ALERT',
        r'Cycle #\d+:',
        r'\[Level \d\]',
        r'No registered services to monitor',
        r'ALREADY_REPORTED',
        
        # Public Internet Scanner / Port Prober Noise (Routine internet background radiation)
        r'Connection reset by peer',
        r'unexpected eof while reading',
        r'connection with http server terminated incorrectly',
        r'SSL_accept error',
        r'lost connection after STARTTLS',
        r'HANGUP after',
        r'DISCONNECT',
        r'PASS NEW',
        r'statistics: max connection',
        r'invalid length of startup packet',
        r'unsupported frontend protocol',
        r'no PostgreSQL user name specified',
        r'lookup.*on whitelist, result',
        
        # Routine Daemon Lifecycle & Normal Initialization
        r'supervisord started',
        r'syslog-ng starting up',
        r'syslog-ng entered RUNNING state',
        r'success:.*entered RUNNING state',
        r'spawned:.*with pid',
        r'checkpoint starting',
        r'checkpoint complete',
        r'database system is ready to accept connections',
        r'database system was shut down',
        r'listening on (?:IPv4|IPv6|Unix socket)',
        r'starting PostgreSQL',
        r'got renewal info',
        r'updated and stored ACME renewal information',
        r'maxprocs: Leaving GOMAXPROCS',
        r'GOMEMLIMIT is updated',
        r'using config from file',
    ]

    # Containers excluded from log-level inspection
    SELF_MONITOR_CONTAINERS = {"ai-ops-daemon", "devctl-dashboard", "caddy"}

    # 2. Universal Syntactic Error Grammars (Language-Agnostic)
    
    # Generic Exception Class Grammar: Matches [Package.][Name]Error/Exception/Fault/Panic: <Message>
    GENERIC_EXCEPTION_REGEX = re.compile(
        r'(?:^|\s)([a-zA-Z0-9_.]*(?:Error|Exception|Fault|Panic|Failure|Crash|Warning))\s*[:\-]\s*(.+)',
        re.IGNORECASE
    )

    # Generic HTTP Client / Upstream Status Code Grammar: 5xx server errors, 429 rate limits
    HTTP_STATUS_ERROR_REGEX = re.compile(
        r'(?:status(?:\s*code)?\s*[:=]?\s*|HTTP\s*|code\s*[:=]\s*|\b)([54]\d{2})\b(?:\s*[:\-]?\s*(.*))?',
        re.IGNORECASE
    )

    # Generic Stack Frame Signatures (Python, Node/JS, Go, Rust, Java/C#, PHP)
    STACK_FRAME_PATTERNS = [
        (r'Traceback \(most recent call last\):', 'Python Stack Trace'),
        (r'^\s*File\s+"[^"]+",\s+line\s+\d+', 'Python Execution Frame'),
        (r'^\s*at\s+(?:[a-zA-Z0-9_$.<>]+\s+\()?.*:\d+:\d+\)?', 'JavaScript/TypeScript Stack Frame'),
        (r'UnhandledPromiseRejection(?:Warning)?:', 'Unhandled Promise Rejection'),
        (r'goroutine\s+\d+\s+\[running\]:', 'Go Panic Stack Trace'),
        (r'^\s*at\s+[a-zA-Z0-9_$.]+\([a-zA-Z0-9_]+:\d+\)', 'JVM / CLR Stack Frame'),
        (r'fatal error:\s+.*', 'Fatal Process Error'),
        (r'panic:\s+(.*)', 'Runtime Panic'),
        (r'Segmentation fault', 'Memory Segmentation Fault (SIGSEGV)'),
        (r'OOMKilled|out of memory|killed\s+process\s+\d+', 'Process Memory Exhaustion (OOM)'),
    ]

    # Generic Socket / Network Drops (Cross-language POSIX error codes)
    NETWORK_ERROR_REGEX = re.compile(
        r'\b(ECONNREFUSED|ECONNRESET|ETIMEDOUT|ENOTFOUND|EHOSTUNREACH|EAI_AGAIN|Connection refused|Connection timed out|Network is unreachable)\b(?:\s*[:\-]?\s*(.*))?',
        re.IGNORECASE
    )

    # Generic Configuration / Ingress Parser Crashes
    CONFIG_ERROR_PATTERNS = [
        (r'Error:\s+adapting config using caddyfile:\s*(.*)', 'Caddyfile Syntax / Option Error'),
        (r'nginx:\s*\[emerg\]\s*(.*)', 'Nginx Syntax / Configuration Crash'),
        (r'httpd:\s*\[emerg\]\s*(.*)', 'Apache Syntax / Configuration Crash'),
        (r'apache2:\s*\[emerg\]\s*(.*)', 'Apache Syntax / Configuration Crash'),
        (r'FATAL:\s+password authentication failed for user "([^"]+)"', 'Database Authentication Refusal'),
        (r'FATAL:\s+database "([^"]+)" does not exist', 'Target Database Not Found'),
        (r'FATAL:\s+Role "([^"]+)" does not exist', 'Database Role Not Found'),
    ]

    @classmethod
    def is_noise(cls, line: str) -> bool:
        """Check if a log line is routine access traffic or benign operational output."""
        clean = line.strip()
        if not clean:
            return True
        for pattern in cls.NOISE_PATTERNS:
            if re.search(pattern, clean, re.IGNORECASE):
                return True
        for pattern in cls._custom_noise:
            if re.search(pattern, clean, re.IGNORECASE):
                return True
        return False

    @classmethod
    def classify_log_error(cls, container_name: str, logs: str) -> Optional[Tuple[str, str]]:
        """
        Syntactically analyze container logs to detect unhandled exceptions,
        upstream 5xx/429 HTTP failures, network drops, and fatal runtime crashes.
        
        Returns:
            (error_snippet, descriptive_category) or None if clean.
        """
        c_lower = container_name.lower()
        if any(sc in c_lower for sc in cls.SELF_MONITOR_CONTAINERS):
            return None

        cls._refresh_custom_patterns()
        candidates: List[Tuple[str, str]] = []

        for line in logs.splitlines():
            if cls.is_noise(line):
                continue

            clean_line = line.strip()

            # 0. Operator-defined error patterns (from ~/.devctl/error_patterns.txt)
            matched_custom = False
            for pat in cls._custom_errors:
                if re.search(pat, clean_line, re.IGNORECASE):
                    candidates.append((clean_line, "Operator-Defined Error"))
                    matched_custom = True
                    break
            if matched_custom:
                continue

            # 1. Check Configuration & Database Authentication Crashes
            for pat, cat in cls.CONFIG_ERROR_PATTERNS:
                m = re.search(pat, clean_line, re.IGNORECASE)
                if m:
                    detail = m.group(1) if m.groups() else clean_line
                    candidates.append((clean_line, f"{cat}: {detail}"))
                    break

            # 2. Check Stack Frame Boundaries (Python, Node, Go, JVM)
            for pat, cat in cls.STACK_FRAME_PATTERNS:
                if re.search(pat, clean_line, re.IGNORECASE):
                    candidates.append((clean_line, cat))
                    break

            # 3. Check Universal Exception Grammar: [AnyName]Error / Exception: <msg>
            exc_match = cls.GENERIC_EXCEPTION_REGEX.search(clean_line)
            if exc_match:
                err_type = exc_match.group(1).strip()
                err_msg = exc_match.group(2).strip()
                # Ensure it's a real class name and not just casual conversational text
                if any(err_type.lower().endswith(suffix) for suffix in ["error", "exception", "fault", "panic", "failure", "crash"]):
                    category = f"Unhandled Exception ({err_type})"
                    candidates.append((clean_line, category))
                    continue

            # 4. Check Upstream / Downstream HTTP Status Code Failures (500-599, 429)
            if any(term in clean_line.lower() for term in ["failed", "status", "http", "error", "response", "upstream"]):
                http_m = cls.HTTP_STATUS_ERROR_REGEX.search(clean_line)
                if http_m:
                    code = int(http_m.group(1))
                    if 500 <= code <= 599:
                        candidates.append((clean_line, f"Upstream / Downstream HTTP {code} Server Outage"))
                        continue
                    elif code == 429:
                        candidates.append((clean_line, f"Upstream API Rate Limit / Quota Exceeded (HTTP 429)"))
                        continue

            # 5. Check Network & Connection Drops
            net_m = cls.NETWORK_ERROR_REGEX.search(clean_line)
            if net_m:
                net_code = net_m.group(1)
                candidates.append((clean_line, f"Network / Socket Failure ({net_code})"))
                continue

        if candidates:
            # Return the most recent high-confidence anomaly
            return candidates[-1]
        return None

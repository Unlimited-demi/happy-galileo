"""
Anomaly Classifier for AI-Ops.
Filters out noise (routine HTTP access traffic, port scan disconnects, self-daemon outputs)
and accurately classifies high-confidence runtime crashes, exceptions, and OOM kills.
"""

import re
from typing import Optional, Dict, Any, List, Tuple


class AnomalyClassifier:
    """Intelligent classifier distinguishing benign log lines from fatal application anomalies."""

    # 1. Benign Log Noise Patterns — MUST BE IGNORED
    NOISE_PATTERNS = [
        # HTTP Access Logs (2xx, 3xx, 4xx routine web traffic)
        r'"\s*(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|CONNECT)\s+.*"\s+[1-4]\d\d\s+',
        r'handled request.*"status":\s*[1-4]\d\d',
        r'HTTP/\d\.\d"\s+[1-4]\d\d',
        r'\[HTTP\]\s+\d{3}\s+',
        
        # Self-daemon & Internal Monitoring Logs
        r'AI-Ops ALERT',
        r'Cycle #\d+:',
        r'\[Level \d\]',
        r'No registered services to monitor',
        r'ALREADY_REPORTED',
        
        # Public Internet Scanner / Port Probing Noise
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
        
        # Routine Daemon Lifecycle Logs
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

    # 2. High-Confidence Application Crash & Fatal Error Signatures
    CRITICAL_ERROR_SIGNATURES = [
        # Python
        (r"Traceback \(most recent call last\):", "Python Unhandled Exception / Traceback"),
        (r"IndentationError:.*", "Python Syntax / Indentation Error"),
        (r"ModuleNotFoundError:\s+No module named\s+.*", "Missing Python Dependency"),
        
        # JavaScript / TypeScript / Node.js
        (r"UnhandledPromiseRejection(?:Warning)?:.*", "Node.js Unhandled Promise Rejection"),
        (r"TypeError:\s+Cannot read properties of.*", "JavaScript TypeError (Null Property Access)"),
        (r"ReferenceError:\s+.*is not defined", "JavaScript ReferenceError (Undefined Variable)"),
        (r"SyntaxError:\s+.*", "JavaScript Syntax Error"),
        (r"PrismaClient(?:KnownRequest|UnknownRequest|Initialization)Error:.*", "Prisma Database ORM Crash"),
        
        # Go / Rust / C++
        (r"panic:\s+.*", "Go Runtime Panic"),
        (r"fatal error:\s+.*", "Fatal Runtime Panic"),
        (r"Segmentation fault", "Memory Segmentation Fault"),
        
        # System & Memory
        (r"OOMKilled", "Out of Memory (OOM Killed)"),
        (r"out of memory", "Memory Exhaustion"),
        (r"killed\s+process\s+\d+", "Process Killed by OS Kernel"),
        
        # Ingress & Configuration Failures
        (r"Error:\s+adapting config using caddyfile:\s+(.*)", "Caddyfile Configuration Adaptation Failure"),
        (r"nginx:\s+\[emerg\]\s+(.*)", "Nginx Fatal Configuration Error"),
        
        # External LLM & AI API Failures (Gemini, OpenAI, Anthropic)
        (r"(?:GoogleAPIError|GoogleGenerativeAIError|ResourceExhausted|API_KEY_INVALID|API key not valid|Quota exceeded for quota metric).*", "Google Gemini API / LLM Upstream Outage"),
        (r"(?:OpenAIError|AnthropicError|RateLimitError|429 Too Many Requests|insufficient_quota).*", "External LLM / Cloud AI Rate Limit & Quota Failure"),
        
        # HTTP 502, 503, 504 Gateway & Upstream Proxy Crashes
        (r"(?:502 Bad Gateway|503 Service Unavailable|504 Gateway Timeout)", "HTTP 5xx Upstream / Gateway Outage"),
        (r"(?:upstream connect error|no live upstreams|connection refused while connecting to upstream)", "Reverse Proxy Upstream Disconnection"),
        (r"(?:AxiosError:\s*Request failed with status code 5\d\d|HTTPError:\s*5\d\d\s+.*|FetchError:.*ECONNREFUSED.*)", "Downstream HTTP 5xx Service Failure"),

        # Object Storage & Payment Gateways
        (r"(?:MinioError|S3Error|NoSuchBucket|SignatureDoesNotMatch|AccessDenied).*", "Object Storage (S3 / MinIO) Failure"),
        (r"(?:StripeError|PaymentError|WebhookDeliveryError).*", "Payment Gateway / Webhook Outage"),
        (r"(?:ConnectionRefusedError|ECONNREFUSED\s+\d+\.\d+\.\d+\.\d+:\d+).*", "Critical Service Connection Drop"),
        
        # Database Authentication Failures (True App Outages)
        (r"FATAL:\s+password authentication failed for user \"([^\"]+)\"", "Database Authentication Failure"),
        (r"FATAL:\s+database \"([^\"]+)\" does not exist", "Missing Production Database"),
    ]

    # Containers that must never be flagged via log inspection
    SELF_MONITOR_CONTAINERS = {"ai-ops-daemon", "devctl-dashboard", "caddy"}

    @classmethod
    def is_noise(cls, line: str) -> bool:
        """Check if a log line is benign traffic or routine daemon output."""
        clean = line.strip()
        if not clean:
            return True
        for pattern in cls.NOISE_PATTERNS:
            if re.search(pattern, clean, re.IGNORECASE):
                return True
        return False

    @classmethod
    def classify_log_error(cls, container_name: str, logs: str) -> Optional[Tuple[str, str]]:
        """
        Scan logs and return (error_snippet, error_category) if a true critical error is found.
        Returns None if logs contain only routine traffic or noise.
        """
        c_lower = container_name.lower()
        if any(sc in c_lower for sc in cls.SELF_MONITOR_CONTAINERS):
            return None

        matched_errors = []
        for line in logs.splitlines():
            if cls.is_noise(line):
                continue
            for pattern, category in cls.CRITICAL_ERROR_SIGNATURES:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    matched_errors.append((line.strip(), category))
                    break

        if matched_errors:
            return matched_errors[-1]
        return None

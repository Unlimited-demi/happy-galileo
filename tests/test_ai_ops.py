"""
Unit tests for AI-Ops monitoring and remediation logic.
"""

import pytest
from ai_ops.dossier_builder import DossierBuilder
from ai_ops.remediation import RemediationEngine


def test_dossier_stack_trace_extraction():
    """Verify extraction of error logs and stack traces."""
    builder = DossierBuilder()

    sample_logs = """
2026-08-13T20:00:00Z [info] Starting server on port 8000
2026-08-13T20:00:01Z [info] Connected to PostgreSQL
2026-08-13T20:01:15Z [error] TypeError: Cannot read property 'id' of undefined
    at UserService.getUserById (/app/src/user.js:42:15)
    at handleRequest (/app/src/server.js:108:22)
2026-08-13T20:01:15Z [info] Request completed in 45ms
"""
    extracted = builder.extract_stack_trace(sample_logs)
    assert "TypeError: Cannot read property 'id' of undefined" in extracted
    assert "UserService.getUserById" in extracted


def test_dossier_recommendation_generation():
    """Verify intelligent recommendations based on error symptoms."""
    builder = DossierBuilder()

    # JS TypeError
    ev1 = {"stack_trace": "TypeError: null is not an object", "status_code": 500}
    rec1 = builder.generate_recommendation(ev1)
    assert "runtime JavaScript/TypeScript bug" in rec1

    # Database / connection refused
    ev2 = {"stack_trace": "PrismaClientInitializationError: Connection refused at localhost:5432", "status_code": 500}
    rec2 = builder.generate_recommendation(ev2)
    assert "DATABASE_URL" in rec2 or "Database" in rec2

    # Bad Gateway 502
    ev3 = {"stack_trace": "", "status_code": 502}
    rec3 = builder.generate_recommendation(ev3)
    assert "Bad Gateway" in rec3 or "port" in rec3

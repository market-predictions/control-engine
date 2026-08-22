#!/usr/bin/env python3
"""Run the existing integration executor with bounded assurance-successor reconciliation."""

from __future__ import annotations

from control_engine import scheduled_worker_a as worker_a
from control_engine import scheduled_worker_a_retry_guard as retry_guard
from scripts import project_integration_executor as integration


# project_integration_executor imports resume_a_unavailable inside its reconcile
# function. Replace that exact public module attribute for this process only; no
# private code/state is modified by this bootstrap.
worker_a.resume_a_unavailable = retry_guard.resume_a_unavailable


if __name__ == "__main__":
    raise SystemExit(integration.main())

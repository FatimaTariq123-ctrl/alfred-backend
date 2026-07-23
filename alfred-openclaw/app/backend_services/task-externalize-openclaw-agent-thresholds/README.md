# Task: Externalize OpenClaw Agent Thresholds and Prompts

## Overview
Moved hardcoded agent thresholds and duplicate trade prevention configuration into centralized application settings, allowing dynamic modification per environment.

## Changes Implemented
- Externalized `DUPLICATE_TRADE_WINDOW_SECONDS` (previously hardcoded to 60s).
- Externalized `DUPLICATE_TRADE_PROMPT`.
- Defined `AGENT_SYSTEM_PROMPT` and `AGENT_TEMPERATURE` inside `app.core.config.Settings`.
- Refactored `trade_prevention_service.py` to pull these rules directly from configuration.

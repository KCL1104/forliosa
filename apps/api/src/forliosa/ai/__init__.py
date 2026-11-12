"""Forliosa AI (M4): Claude chat with our own tools, drafts, usage quotas and the shared "why" sentence.

Layout:

* ``keypool``  – API keys (``CLAUDE_API_KEY_<n>`` / ``ANTHROPIC_API_KEY``), one client per key, failover.
* ``tools``    – client tools wrapping our services (always scoped to the signed-in user) + web search / fetch.
* ``prompts``  – the frozen zh-TW system prompts and the per-turn page context.
* ``chat``     – the streaming tool loop behind ``POST /ai/chat`` (SSE).
* ``store``    – threads, messages, drafts, usage and quotas.
* ``suggestions`` – rule-based questions and actions per page (no model call).
* ``why``      – the optional one-sentence AI explanation for ``/instruments/{symbol}/why``.
* ``smoke``    – ``python -m forliosa.ai.smoke``: a live check against the real API.
"""

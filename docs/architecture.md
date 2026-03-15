# Architecture

See the main `README.md` for the core architecture diagram and platform capabilities.

Aethelgard uses a stream-processing architecture. Log files and prometheus telemetry are scooped up by a log listener (e.g. FluentBit) and converted into structured events inside the Redis Event Bus (Redis Streams).

The multi-agent orchestration layer listens to the event bus and pulls telemetry down for detection.

The sandbox is an isolated layer that safely triggers Docker containers for validation without exposing the host OS to LLM-generated execution risks.

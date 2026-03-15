# Infrastructure

Aethelgard deploys a full local infrastructure stack to simulate real production incident response.

The core services running under Docker Compose are:

- `aethelgard-api`: The FastAPI Python backend hosting the orchestration logic and agents.
- `dashboard`: The real-time Streamlit dashboard (`localhost:8501`).
- `redis`: The event bus backing all inter-agent communication and metric buffers.
- `payment-service`: The target microservice we perform chaos engineering against.
- `prometheus`: Real-time telemetry scraping from the `payment-service` and orchestration instances (`localhost:9090`).
- `grafana`: Platform observability dashboard (`localhost:3001`).

**Safety Disclaimer**: All automated deployment and Kubernetes rollout orchestration logic is handled behind a controlled, simulated boundary. Aethelgard clones the state of failing containers into an isolated sandbox to prevent unintended side constraints on production infrastructure.

# Agents

Aethelgard's core control loop relies on five distinct agents, each dedicated to a specific part of the incident response lifecycle.

1. **Detection Agent (🔍)**
   Observes distributed telemetry (Prometheus metrics, logs). It utilizes statistical z-score methods to identify significant deviations from baseline performance (e.g., latency spikes, error rate increases).

2. **Diagnosis Agent (🧠)**
   When an anomaly is detected, this agent infers the root cause using a ReAct sequence. It analyzes the context of the incident and maps symptoms to probable failures.

3. **Remediation Agent (🔧)**
   Responsible for patch generation. It queries the RAG knowledge base for internal playbooks and then autonomously crafts a code or configuration patch targeting the compromised service.

4. **Validation Agent (🛡)**
   Executes the generated patch inside a safe, cloned sandboxed Docker container. It returns a risk score based on static AST safety, test results, and runtime stability.

5. **Deployment Agent (🚀)**
   If a patch passes validation with a low enough risk score, this agent deploys it to the affected service, restarting or rolling over the workload to restore operational health.

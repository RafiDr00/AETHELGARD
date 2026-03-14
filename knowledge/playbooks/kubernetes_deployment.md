# Kubernetes Deployment Rules

## Deployment Strategies
### Rolling Update (Default)
- `maxSurge: 25%` — Allow 25% extra pods during update
- `maxUnavailable: 25%` — Allow 25% pods unavailable
- Ensures zero-downtime deployments

### Canary Deployment
- Deploy new version to small percentage of traffic
- Monitor error rates and latency
- Gradually increase traffic if metrics are healthy
- Rollback immediately if anomalies detected

### Blue/Green Deployment
- Maintain two identical environments
- Switch traffic via service selector update
- Instant rollback by switching back

## Resource Management
```yaml
resources:
  requests:
    cpu: "250m"
    memory: "256Mi"
  limits:
    cpu: "1000m"
    memory: "1Gi"
```
- Always set both requests and limits
- requests = guaranteed resources
- limits = maximum burst capacity
- Ratio: limits should be 2-4x requests

## Health Checks
```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 15
  periodSeconds: 10
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /ready
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 5
  failureThreshold: 3
```

## Horizontal Pod Autoscaler
- Target CPU utilization: 70%
- Min replicas: 2 (for high availability)
- Max replicas: based on load testing data
- Scale-down stabilization: 300 seconds

## Pod Disruption Budget
- Always set PDB for production services
- `minAvailable: 1` or `maxUnavailable: 1`
- Prevents accidental total outage during node drain

## Rollback Procedures
1. `kubectl rollout undo deployment/<name>`
2. Verify health checks pass
3. Check metrics dashboard
4. Update incident record

## Common K8s Issues
| Issue | Root Cause | Fix |
|-------|-----------|-----|
| CrashLoopBackOff | App crash on startup | Check logs, fix config |
| Pending pods | Insufficient resources | Scale cluster or reduce requests |
| OOMKilled | Memory limit exceeded | Increase limits + optimize |
| ImagePullBackOff | Image not found | Verify image tag and registry |

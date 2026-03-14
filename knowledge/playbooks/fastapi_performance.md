# FastAPI Performance Best Practices

## Server Configuration
- Use `uvicorn` with `uvloop` and `httptools`
- Set workers: `2 * CPU + 1` (minimum)
- Enable `--limit-concurrency` to prevent thread exhaustion
- Configure `--timeout-keep-alive 30` for persistent connections

## Middleware Optimization
- Order middleware by frequency (most used first)
- Use lazy loading for heavy dependencies
- Implement response caching with `Cache-Control` headers
- Add GZIP compression for responses > 1KB

## Database Integration
- Use async database drivers (asyncpg, motor)
- Implement connection pooling with `SQLAlchemy` async
- Use `pool_pre_ping=True` for connection validation
- Set `pool_recycle=1800` to prevent stale connections

## API Design
- Use dependency injection for shared resources
- Implement pagination for list endpoints
- Use background tasks for non-critical operations
- Add rate limiting per client/endpoint

## Monitoring
- Export Prometheus metrics via `/metrics` endpoint
- Track request duration, error rate, active connections
- Implement structured logging with correlation IDs
- Add health check endpoints: `/health`, `/ready`

## Common Issues
| Issue | Root Cause | Fix |
|-------|-----------|-----|
| High latency | Worker exhaustion | Increase worker count |
| Memory growth | Connection leaks | Enable pool recycling |
| 502 errors | Timeout mismatch | Align proxy/server timeouts |
| CPU spikes | Sync in async | Use run_in_executor |

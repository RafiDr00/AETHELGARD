# Python Async Optimization Strategies

## Worker Pool Configuration
- Default uvicorn workers: `2 * CPU_COUNT + 1`
- For I/O-bound services: increase to `4 * CPU_COUNT`
- Use `uvloop` for superior event loop performance
- Set `limit_concurrency` to prevent overload

## Async Best Practices
- Always use `async/await` for I/O operations
- Use `asyncio.gather()` for concurrent operations
- Implement connection pooling for database/HTTP clients
- Use `asyncio.Semaphore` for rate limiting
- Avoid blocking calls in async context (use `run_in_executor`)

## Connection Pooling
```python
# Recommended pool settings
POOL_SIZE = 20
MAX_OVERFLOW = 40
POOL_TIMEOUT = 30
POOL_RECYCLE = 1800  # Recycle connections every 30 minutes
```

## Memory Management
- Use generators for large data streams
- Implement request-level memory budgets
- Profile with `tracemalloc` for leak detection
- Set container memory limits with overhead margin (20%)

## Error Handling
- Implement exponential backoff for retries
- Use circuit breakers for external dependencies
- Set appropriate timeouts for all async operations
- Log correlation IDs for distributed tracing

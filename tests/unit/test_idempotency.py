import pytest
from unittest.mock import AsyncMock
from infrastructure.persistence import FingerprintStore

@pytest.mark.asyncio
async def test_fingerprint_idempotency():
    mock_redis = AsyncMock()
    # First call returns True (OK), second call returns False (DUPLICATE)
    mock_redis.set.side_effect = [True, False]
    
    store = FingerprintStore(redis_client=mock_redis)
    
    # First attempt
    result1 = await store.claim_fingerprint("abcd", ttl_seconds=60)
    assert result1 is True
    
    # Concurrent attempt
    result2 = await store.claim_fingerprint("abcd", ttl_seconds=60)
    assert result2 is False

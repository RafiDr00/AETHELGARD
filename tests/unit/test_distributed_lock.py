import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from infrastructure.distributed_lock import DistributedLock

@pytest.mark.asyncio
async def test_distributed_lock_acquire_success():
    mock_redis = AsyncMock()
    mock_redis.set.return_value = True
    lock = DistributedLock(redis_client=mock_redis)
    
    result = await lock.acquire("my_service")
    assert result is True
    mock_redis.set.assert_called_with("aethelgard:lock:my_service", "locked", nx=True, px=30000)

@pytest.mark.asyncio
async def test_distributed_lock_acquire_fail():
    mock_redis = AsyncMock()
    mock_redis.set.return_value = False
    lock = DistributedLock(redis_client=mock_redis)
    
    result = await lock.acquire("my_service")
    assert result is False

@pytest.mark.asyncio
async def test_distributed_lock_release():
    mock_redis = AsyncMock()
    lock = DistributedLock(redis_client=mock_redis)
    
    await lock.release("my_service")
    mock_redis.delete.assert_called_with("aethelgard:lock:my_service")

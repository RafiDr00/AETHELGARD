import pytest
import uuid
from unittest.mock import AsyncMock
from infrastructure.distributed_lock import DistributedLock, RELEASE_SCRIPT


@pytest.mark.asyncio
async def test_acquire_success_returns_token():
    mock_redis = AsyncMock()
    mock_redis.set.return_value = True
    lock = DistributedLock(redis_client=mock_redis)

    token = await lock.acquire("my_service")

    assert token is not None
    assert isinstance(token, str)
    assert len(token) == 32  # uuid4().hex
    call_args = mock_redis.set.call_args
    assert call_args.args[1] == token  # token passed to Redis matches what was returned
    assert call_args.kwargs == {"nx": True, "px": 30000}


@pytest.mark.asyncio
async def test_acquire_failure_returns_none():
    mock_redis = AsyncMock()
    mock_redis.set.return_value = False
    lock = DistributedLock(redis_client=mock_redis)

    token = await lock.acquire("my_service")

    assert token is None


@pytest.mark.asyncio
async def test_acquire_redis_error_returns_none():
    mock_redis = AsyncMock()
    mock_redis.set.side_effect = Exception("connection refused")
    lock = DistributedLock(redis_client=mock_redis)

    token = await lock.acquire("my_service")

    assert token is None


@pytest.mark.asyncio
async def test_release_calls_lua_script_with_token():
    mock_redis = AsyncMock()
    lock = DistributedLock(redis_client=mock_redis)
    token = uuid.uuid4().hex

    await lock.release("my_service", token)

    mock_redis.eval.assert_called_once_with(
        RELEASE_SCRIPT, 1, "aethelgard:lock:my_service", token
    )


@pytest.mark.asyncio
async def test_release_race_condition_stale_token_does_not_delete():
    """Race condition: lock expired and was re-acquired by another process.

    The caller presents a stale token. The Lua script returns 0 (no-op) because
    the key now holds a different token. Critically, no unconditional delete fires.
    """
    stale_token = uuid.uuid4().hex

    mock_redis = AsyncMock()
    mock_redis.eval.return_value = 0  # Lua: token mismatch → no delete
    lock = DistributedLock(redis_client=mock_redis)

    await lock.release("my_service", stale_token)

    mock_redis.eval.assert_called_once_with(
        RELEASE_SCRIPT, 1, "aethelgard:lock:my_service", stale_token
    )
    mock_redis.delete.assert_not_called()

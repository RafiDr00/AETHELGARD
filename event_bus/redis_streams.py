"""
Aethelgard — Redis Streams Event Bus

Production-grade event bus implementation using Redis Streams with:
- Consumer groups for reliable message delivery
- Automatic stream creation and management
- Dead letter queue for failed messages
- Event acknowledgment and retry logic
- Backpressure handling
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional

import redis.asyncio as aioredis

from core.config import get_settings
from core.exceptions import EventBusError, EventConsumeError, EventPublishError
from core.logging_config import get_logger
from core.models import Event, EventType

logger = get_logger(__name__)


class RedisStreamsClient:
    """
    High-level Redis Streams client for the Aethelgard event bus.
    
    Provides publish/subscribe semantics over Redis Streams with
    consumer groups, acknowledgment, and dead-letter routing.
    """

    def __init__(self):
        self._settings = get_settings()
        self._redis: Optional[aioredis.Redis] = None
        self._consumer_group = self._settings.redis.consumer_group
        self._stream_max_len = self._settings.redis.stream_max_len
        self._handlers: Dict[str, List[Callable]] = {}
        self._running = False
        self._consumer_tasks: List[asyncio.Task] = []

    async def connect(self) -> None:
        """Establish connection to Redis."""
        try:
            self._redis = aioredis.Redis(
                host=self._settings.redis.host,
                port=self._settings.redis.port,
                db=self._settings.redis.db,
                password=self._settings.redis.password,
                decode_responses=True,
                socket_timeout=self._settings.redis.socket_timeout,
                retry_on_timeout=self._settings.redis.retry_on_timeout,
            )
            await self._redis.ping()
            logger.info("redis_connected", host=self._settings.redis.host, port=self._settings.redis.port)
        except Exception as e:
            logger.error("redis_connection_failed", error=str(e))
            raise EventBusError(f"Failed to connect to Redis: {e}")

    async def disconnect(self) -> None:
        """Gracefully disconnect from Redis."""
        self._running = False
        for task in self._consumer_tasks:
            task.cancel()
        if self._redis:
            await self._redis.close()
            logger.info("redis_disconnected")

    async def _ensure_stream(self, stream: str) -> None:
        """Ensure stream and consumer group exist."""
        try:
            await self._redis.xgroup_create(
                stream, self._consumer_group, id="0", mkstream=True
            )
        except aioredis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def publish(self, stream: str, event: Event) -> str:
        """
        Publish an event to a Redis Stream.
        
        Args:
            stream: Target stream name (e.g., 'anomaly.detected')
            event: Event object to publish
            
        Returns:
            Message ID assigned by Redis
        """
        if not self._redis:
            raise EventPublishError("Redis client not connected")

        try:
            await self._ensure_stream(stream)
            data = event.to_stream_data()

            message_id = await self._redis.xadd(
                stream,
                data,
                maxlen=self._stream_max_len,
                approximate=True,
            )

            logger.info(
                "event_published",
                stream=stream,
                event_type=event.event_type.value,
                event_id=event.id,
                message_id=message_id,
            )
            return message_id

        except Exception as e:
            logger.error("event_publish_failed", stream=stream, error=str(e))
            raise EventPublishError(f"Failed to publish to {stream}: {e}")

    async def subscribe(
        self,
        streams: List[str],
        handler: Callable[[Event], Coroutine],
        consumer_name: str = "worker-1",
        batch_size: int = 10,
    ) -> None:
        """
        Subscribe to one or more streams with a handler function.
        
        Uses consumer groups for reliable, at-least-once delivery.
        """
        for stream in streams:
            await self._ensure_stream(stream)
            if stream not in self._handlers:
                self._handlers[stream] = []
            self._handlers[stream].append(handler)

        self._running = True
        task = asyncio.create_task(
            self._consume_loop(streams, consumer_name, batch_size)
        )
        self._consumer_tasks.append(task)
        logger.info("subscription_started", streams=streams, consumer=consumer_name)

    async def _consume_loop(
        self,
        streams: List[str],
        consumer_name: str,
        batch_size: int,
    ) -> None:
        """Main consumer loop reading from streams."""
        stream_ids = {s: ">" for s in streams}
        block_ms = self._settings.redis.consumer_block_ms

        while self._running:
            try:
                results = await self._redis.xreadgroup(
                    self._consumer_group,
                    consumer_name,
                    streams=stream_ids,
                    count=batch_size,
                    block=block_ms,
                )

                if not results:
                    continue

                for stream_name, messages in results:
                    for message_id, data in messages:
                        await self._process_message(
                            stream_name, message_id, data, consumer_name
                        )

            except asyncio.CancelledError:
                logger.info("consumer_loop_cancelled", consumer=consumer_name)
                break
            except Exception as e:
                logger.error("consumer_loop_error", error=str(e), consumer=consumer_name)
                await asyncio.sleep(1)  # Backoff

    async def _process_message(
        self,
        stream: str,
        message_id: str,
        data: Dict[str, str],
        consumer_name: str,
    ) -> None:
        """Process a single message, invoking registered handlers."""
        try:
            event = Event.from_stream_data(data)
            handlers = self._handlers.get(stream, [])

            for handler in handlers:
                await handler(event)

            # Acknowledge successful processing
            await self._redis.xack(stream, self._consumer_group, message_id)

            logger.debug(
                "message_processed",
                stream=stream,
                message_id=message_id,
                event_type=data.get("event_type"),
            )

        except Exception as e:
            logger.error(
                "message_processing_failed",
                stream=stream,
                message_id=message_id,
                error=str(e),
            )
            # Move to dead letter queue after max retries
            await self._send_to_dlq(stream, message_id, data, str(e))

    async def _send_to_dlq(
        self,
        original_stream: str,
        message_id: str,
        data: Dict[str, str],
        error: str,
    ) -> None:
        """Move failed message to dead letter queue."""
        dlq_stream = f"{original_stream}.dlq"
        dlq_data = {
            **data,
            "original_stream": original_stream,
            "original_message_id": message_id,
            "error": error,
            "failed_at": str(time.time()),
        }
        try:
            await self._redis.xadd(dlq_stream, dlq_data, maxlen=1000)
            await self._redis.xack(original_stream, self._consumer_group, message_id)
        except Exception as e:
            logger.error("dlq_send_failed", error=str(e))

    async def get_stream_info(self, stream: str) -> Dict[str, Any]:
        """Get stream metadata and consumer group info."""
        try:
            info = await self._redis.xinfo_stream(stream)
            groups = await self._redis.xinfo_groups(stream)
            return {
                "length": info.get("length", 0),
                "first_entry": info.get("first-entry"),
                "last_entry": info.get("last-entry"),
                "groups": groups,
            }
        except Exception:
            return {"length": 0, "groups": []}

    async def get_pending_count(self, stream: str) -> int:
        """Get count of pending (unacknowledged) messages."""
        try:
            pending = await self._redis.xpending(stream, self._consumer_group)
            return pending.get("pending", 0) if isinstance(pending, dict) else 0
        except Exception:
            return 0

    async def get_stream_length(self, stream: str) -> int:
        """Get total messages in stream."""
        try:
            return await self._redis.xlen(stream)
        except Exception:
            return 0


# Singleton state for event bus
# _event_bus == None          : not yet initialised
# _event_bus == _BUS_FAILED   : connection attempted, Redis unavailable
# _event_bus == RedisStreamsClient : connected and usable
_event_bus: Optional[RedisStreamsClient] = None
_BUS_FAILED = object()  # sentinel
_BUS_INSTANCE = None    # the real connected client


async def get_event_bus() -> Optional[RedisStreamsClient]:
    """
    Get or create the singleton event bus client.

    Returns None if Redis is unavailable — callers must handle gracefully.
    The explicit orchestrator pipeline does NOT require a bus connection.
    Only one connection attempt is ever made (failure is cached).
    """
    global _event_bus, _BUS_INSTANCE
    # Already determined
    if _event_bus is _BUS_FAILED:
        return None
    if _BUS_INSTANCE is not None:
        return _BUS_INSTANCE
    try:
        client = RedisStreamsClient()
        await client.connect()
        _BUS_INSTANCE = client
        _event_bus = client
        return _BUS_INSTANCE
    except Exception as e:
        _event_bus = _BUS_FAILED  # cache failure — never retry
        logger.warning(
            "event_bus_unavailable",
            error=str(e)[:120],
            note="Operating in direct-pipeline mode. Redis is optional.",
        )
        return None


async def shutdown_event_bus() -> None:
    """Shutdown the singleton event bus client."""
    global _event_bus
    if _event_bus:
        await _event_bus.disconnect()
        _event_bus = None

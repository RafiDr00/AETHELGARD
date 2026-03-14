"""
Aethelgard v2 — Base Agent with ReAct Reasoning Loop

Abstract base class implementing the ReAct (Reason + Act) paradigm.
All agents in the system inherit from this class and implement
domain-specific reasoning logic.

The ReAct loop follows: Thought → Action → Observation → (repeat or decide)
"""

from __future__ import annotations

import asyncio
import time
import traceback
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.config import get_settings
from core.exceptions import AgentReasoningError, AgentTimeoutError
from core.logging_config import get_logger
from core.models import AgentType, Event, EventType, ReActStep
from core.telemetry import record_react_iteration    # FIX #8
from event_bus.redis_streams import RedisStreamsClient, get_event_bus

logger = get_logger(__name__)


class BaseAgent(ABC):
    """
    Abstract base agent implementing the ReAct reasoning loop.
    
    All specialized agents (Detection, Diagnosis, Remediation, 
    Validation, Deployment) inherit from this class and implement:
    - think(): Generate a thought based on current state
    - act(): Execute an action based on the thought
    - observe(): Process the result of the action
    - decide(): Determine if reasoning is complete
    
    The agent communicates exclusively through the event bus,
    never directly with other agents.
    """

    def __init__(self, agent_type: AgentType):
        self.agent_type = agent_type
        self.agent_id = f"{agent_type.value}-{uuid.uuid4().hex[:8]}"
        self._settings = get_settings()
        self._event_bus: Optional[RedisStreamsClient] = None
        self._reasoning_chain: List[ReActStep] = []
        self._max_iterations = self._settings.agents.react_max_iterations
        self._timeout = self._settings.agents.agent_timeout
        self._is_running = False
        self._current_context: Dict[str, Any] = {}

    async def initialize(self) -> None:
        """Initialize agent — event bus connection is optional (graceful degradation)."""
        try:
            self._event_bus = await get_event_bus()
        except Exception as e:
            # Event bus is used for observability publishing only.
            # The explicit orchestrator pipeline does NOT require it.
            self._event_bus = None
            logger.warning(
                "agent_event_bus_unavailable",
                agent_id=self.agent_id,
                reason=str(e)[:120],
                note="Operating in direct-pipeline mode. Redis is optional.",
            )
        await self._setup_subscriptions()
        self._is_running = True
        logger.info(
            "agent_initialized",
            agent_id=self.agent_id,
            agent_type=self.agent_type.value,
            event_bus="connected" if self._event_bus else "unavailable",
        )

    async def shutdown(self) -> None:
        """Gracefully shutdown the agent."""
        self._is_running = False
        logger.info("agent_shutdown", agent_id=self.agent_id)

    @abstractmethod
    async def _setup_subscriptions(self) -> None:
        """Set up event bus subscriptions. Implemented by each agent type."""
        pass

    @abstractmethod
    async def think(self, context: Dict[str, Any]) -> str:
        """
        Generate a thought based on current context.
        
        Returns:
            A string describing the agent's reasoning about the situation.
        """
        pass

    @abstractmethod
    async def act(self, thought: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute an action based on the thought.
        
        Args:
            thought: The reasoning output from think()
            context: Current execution context
            
        Returns:
            Action result data.
        """
        pass

    @abstractmethod
    async def observe(self, action_result: Dict[str, Any], context: Dict[str, Any]) -> str:
        """
        Process the observation from the action.
        
        Args:
            action_result: Data returned from act()
            context: Current execution context
            
        Returns:
            Observation summary string.
        """
        pass

    @abstractmethod
    async def decide(self, context: Dict[str, Any]) -> bool:
        """
        Determine if the reasoning loop should terminate.
        
        Returns:
            True if the agent has reached a decision, False to continue reasoning.
        """
        pass

    @abstractmethod
    async def emit_result(self, context: Dict[str, Any]) -> None:
        """Emit the final result as an event to the bus."""
        pass

    async def execute_react_loop(self, initial_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the full ReAct reasoning loop.
        
        Thought → Action → Observation → (Continue or Decide)
        
        Args:
            initial_context: Starting context for reasoning
            
        Returns:
            Final context with reasoning results
        """
        self._reasoning_chain = []
        self._current_context = {**initial_context}
        start_time = time.time()

        logger.info(
            "react_loop_started",
            agent_id=self.agent_id,
            context_keys=list(initial_context.keys()),
        )

        for iteration in range(1, self._max_iterations + 1):
            # Check timeout
            elapsed = time.time() - start_time
            if elapsed > self._timeout:
                record_react_iteration(
                    agent_type=self.agent_type.value,
                    iterations=iteration,
                    outcome="timeout",
                )
                raise AgentTimeoutError(
                    f"Agent {self.agent_id} timed out after {elapsed:.1f}s",
                    details={"iteration": iteration, "elapsed": elapsed},
                )

            try:
                # Set iteration BEFORE think/act/observe so agents can branch correctly
                self._current_context["iteration"] = iteration

                # THOUGHT
                thought = await self.think(self._current_context)
                logger.debug("react_thought", agent_id=self.agent_id, iteration=iteration, thought=thought[:200])

                # ACTION
                action_result = await self.act(thought, self._current_context)
                action_desc = str(action_result)[:200]
                logger.debug("react_action", agent_id=self.agent_id, iteration=iteration, action=action_desc)

                # OBSERVATION
                observation = await self.observe(action_result, self._current_context)
                logger.debug("react_observation", agent_id=self.agent_id, iteration=iteration, observation=observation[:200])

                # Record step
                step = ReActStep(
                    step_number=iteration,
                    thought=thought,
                    action=action_desc,
                    observation=observation,
                )
                self._reasoning_chain.append(step)

                # Update context with results
                self._current_context["last_thought"] = thought
                self._current_context["last_action_result"] = action_result
                self._current_context["last_observation"] = observation
                self._current_context["reasoning_chain"] = self._reasoning_chain

                # DECIDE
                if await self.decide(self._current_context):
                    total_time = time.time() - start_time
                    self._current_context["total_reasoning_time"] = total_time
                    self._current_context["total_iterations"] = iteration

                    logger.info(
                        "react_loop_complete",
                        agent_id=self.agent_id,
                        iterations=iteration,
                        duration_s=round(total_time, 2),
                    )

                    # FIX #8 — Emit iteration count metric
                    record_react_iteration(
                        agent_type=self.agent_type.value,
                        iterations=iteration,
                        outcome="decided",
                    )

                    # Emit result to event bus
                    await self.emit_result(self._current_context)
                    return self._current_context

            except (AgentTimeoutError, AgentReasoningError):
                raise
            except Exception as e:
                logger.error(
                    "react_step_error",
                    agent_id=self.agent_id,
                    iteration=iteration,
                    error=str(e),
                    traceback=traceback.format_exc(),
                )
                self._current_context["error"] = str(e)
                if iteration >= self._max_iterations:
                    record_react_iteration(
                        agent_type=self.agent_type.value,
                        iterations=iteration,
                        outcome="error",
                    )
                    raise AgentReasoningError(
                        f"Agent {self.agent_id} failed after {iteration} iterations: {e}"
                    )

        record_react_iteration(
            agent_type=self.agent_type.value,
            iterations=self._max_iterations,
            outcome="exhausted",
        )
        raise AgentReasoningError(
            f"Agent {self.agent_id} exhausted max iterations ({self._max_iterations})"
        )

    async def publish_event(self, event_type: EventType, payload: Dict[str, Any], correlation_id: Optional[str] = None) -> None:
        """Publish an event to the event bus. Silently skips in direct mode."""
        if not self._event_bus:
            logger.debug("publish_skipped_no_bus", event_type=event_type.value, agent=self.agent_id)
            return

        event = Event(
            event_type=event_type,
            source_agent=self.agent_type,
            payload=payload,
            correlation_id=correlation_id,
        )
        stream = event_type.value
        await self._event_bus.publish(stream, event)

    async def handle_event(self, event: Event) -> None:
        """
        Handle an incoming event from the bus.
        Converts event payload to context and starts reasoning.
        """
        logger.info(
            "event_received",
            agent_id=self.agent_id,
            event_type=event.event_type.value,
            event_id=event.id,
        )

        context = {
            "event": event.model_dump(),
            "event_type": event.event_type.value,
            "correlation_id": event.correlation_id or event.id,
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        context.update(event.payload)

        try:
            await self.execute_react_loop(context)
        except Exception as e:
            logger.error(
                "event_handling_failed",
                agent_id=self.agent_id,
                event_id=event.id,
                error=str(e),
            )

    @property
    def reasoning_history(self) -> List[ReActStep]:
        """Get the current reasoning chain."""
        return self._reasoning_chain.copy()

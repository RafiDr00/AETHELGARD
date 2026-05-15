"""
Aethelgard v2 — Custom Exception Hierarchy

Domain-specific exceptions for precise error handling
across the autonomous remediation pipeline.
"""

from __future__ import annotations


class AethelgardError(Exception):
    """Base exception for all Aethelgard platform errors."""
    
    def __init__(self, message: str, details: dict | None = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


# --- Agent Errors ---

class AgentError(AethelgardError):
    """Base error for agent operations."""
    pass


class AgentTimeoutError(AgentError):
    """Agent exceeded maximum execution time."""
    pass


class AgentReasoningError(AgentError):
    """Agent failed during ReAct reasoning loop."""
    pass


class AgentCommunicationError(AgentError):
    """Agent failed to communicate via event bus."""
    pass


# --- Event Bus Errors ---

class EventBusError(AethelgardError):
    """Base error for event bus operations."""
    pass


class EventPublishError(EventBusError):
    """Failed to publish event to stream."""
    pass


class EventConsumeError(EventBusError):
    """Failed to consume event from stream."""
    pass


class EventSerializationError(EventBusError):
    """Failed to serialize/deserialize event."""
    pass


# --- Sandbox Errors ---

class SandboxError(AethelgardError):
    """Base error for sandbox operations."""
    pass


class SandboxTimeoutError(SandboxError):
    """Sandbox execution exceeded timeout."""
    pass


class SandboxSecurityViolation(SandboxError):
    """Sandbox detected a security policy violation."""
    pass


class SandboxResourceExhausted(SandboxError):
    """Sandbox exhausted allocated resources."""
    pass


# --- Knowledge Errors ---

class KnowledgeError(AethelgardError):
    """Base error for knowledge system operations."""
    pass


class EmbeddingError(KnowledgeError):
    """Failed to generate embeddings."""
    pass


class VectorStoreError(KnowledgeError):
    """Vector store operation failed."""
    pass


class RAGRetrievalError(KnowledgeError):
    """RAG retrieval failed."""
    pass


# --- Deployment Errors ---

class DeploymentError(AethelgardError):
    """Base error for deployment operations."""
    pass


class ImageBuildError(DeploymentError):
    """Docker image build failed."""
    pass


class RegistryPushError(DeploymentError):
    """Failed to push image to registry."""
    pass


class KubernetesDeployError(DeploymentError):
    """Kubernetes deployment failed."""
    pass


class HealthCheckError(DeploymentError):
    """Post-deployment health check failed."""
    pass


class RollbackError(DeploymentError):
    """Deployment rollback failed."""
    pass


# --- Validation Errors ---

class ValidationError(AethelgardError):
    """Base error for validation operations."""
    pass


class StaticAnalysisError(ValidationError):
    """Static code analysis failed."""
    pass


class PolicyViolationError(ValidationError):
    """Patch violated security policies."""
    pass


class RiskThresholdExceeded(ValidationError):
    """Patch risk score exceeded safety threshold."""
    pass

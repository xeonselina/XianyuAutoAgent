"""
Event handler base and hook registry.
T044 - EventHandler base class and HookRegistry.
"""

from typing import Dict, List, Callable, Any
from abc import ABC, abstractmethod
from ai_kefu.config.constants import EventType
from ai_kefu.utils.logging import logger


class EventHandler(ABC):
    """Base class for event handlers (hooks)."""
    
    @abstractmethod
    def handle(self, event_type: EventType, event_data: Dict[str, Any]) -> None:
        """
        Handle an event.
        
        Args:
            event_type: Type of event
            event_data: Event data
        """
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """Get handler name."""
        pass


class HookRegistry:
    """Registry for managing event hooks."""
    
    def __init__(self):
        """Initialize hook registry."""
        self._hooks: Dict[EventType, List[EventHandler]] = {
            event_type: [] for event_type in EventType
        }
        self._global_hooks: List[EventHandler] = []
    
    def register(
        self,
        handler: EventHandler,
        event_types: List[EventType] = None
    ) -> None:
        """
        Register an event handler.
        
        Args:
            handler: Event handler
            event_types: Event types to listen to (None = all events)
        """
        if event_types is None:
            # Register as global hook (receives all events)
            self._global_hooks.append(handler)
            logger.info(f"Registered global hook: {handler.get_name()}")
        else:
            # Register for specific event types
            for event_type in event_types:
                self._hooks[event_type].append(handler)
            logger.info(f"Registered hook '{handler.get_name()}' for events: {[e.value for e in event_types]}")
    
    def emit(self, event_type: EventType, event_data: Dict[str, Any]) -> None:
        """
        Emit an event to all registered handlers.
        
        Args:
            event_type: Type of event
            event_data: Event data
        """
        # Call global hooks
        for handler in self._global_hooks:
            try:
                handler.handle(event_type, event_data)
            except Exception as e:
                logger.error(f"Global hook '{handler.get_name()}' failed: {e}")
        
        # Call event-specific hooks
        for handler in self._hooks.get(event_type, []):
            try:
                handler.handle(event_type, event_data)
            except Exception as e:
                logger.error(f"Hook '{handler.get_name()}' failed for event {event_type.value}: {e}")
    
    def unregister(self, handler: EventHandler) -> None:
        """
        Unregister an event handler.
        
        Args:
            handler: Event handler to remove
        """
        # Remove from global hooks
        if handler in self._global_hooks:
            self._global_hooks.remove(handler)
        
        # Remove from event-specific hooks
        for event_type in EventType:
            if handler in self._hooks[event_type]:
                self._hooks[event_type].remove(handler)
        
        logger.info(f"Unregistered hook: {handler.get_name()}")
    
    def get_registered_hooks(self) -> Dict[str, List[str]]:
        """
        Get information about registered hooks.
        
        Returns:
            Dict mapping event types to handler names
        """
        result = {
            "global": [h.get_name() for h in self._global_hooks]
        }
        
        for event_type, handlers in self._hooks.items():
            if handlers:
                result[event_type.value] = [h.get_name() for h in handlers]
        
        return result


# Global hook registry instance
_hook_registry = HookRegistry()


def get_hook_registry() -> HookRegistry:
    """
    Get global hook registry instance.
    
    Returns:
        HookRegistry singleton
    """
    return _hook_registry

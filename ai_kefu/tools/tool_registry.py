"""
Tool registry for managing and executing tools.
T035 - Tool registry implementation.
"""

from typing import Dict, List, Callable, Any, Optional
from ai_kefu.utils.errors import ToolExecutionError
from ai_kefu.utils.logging import logger


class ToolRegistry:
    """Registry for managing agent tools."""
    
    def __init__(self):
        """Initialize tool registry."""
        self._tools: Dict[str, Callable] = {}
        self._tool_definitions: Dict[str, Dict[str, Any]] = {}
    
    def register_tool(
        self,
        name: str,
        function: Callable,
        definition: Dict[str, Any]
    ) -> None:
        """
        Register a tool.
        
        Args:
            name: Tool name
            function: Tool function
            definition: Tool definition (parameters, description)
        """
        self._tools[name] = function
        self._tool_definitions[name] = definition
        logger.info(f"Registered tool: {name}")
    
    def get_tool(self, name: str) -> Optional[Callable]:
        """
        Get tool function by name.
        
        Args:
            name: Tool name
            
        Returns:
            Tool function if found, None otherwise
        """
        return self._tools.get(name)
    
    def get_all_tools(self) -> List[str]:
        """
        Get list of all registered tool names.
        
        Returns:
            List of tool names
        """
        return list(self._tools.keys())
    
    def to_qwen_format(self) -> List[Dict[str, Any]]:
        """
        Convert tool definitions to Qwen Function Calling format.
        
        Returns:
            List of tool definitions in Qwen format
        """
        qwen_tools = []
        
        for name, definition in self._tool_definitions.items():
            qwen_tools.append({
                "type": "function",
                "function": {
                    "name": definition["name"],
                    "description": definition["description"],
                    "parameters": definition["parameters"]
                }
            })
        
        return qwen_tools
    
    def execute_tool(self, name: str, args: Dict[str, Any]) -> Any:
        """
        Execute a tool by name with arguments.
        
        Args:
            name: Tool name
            args: Tool arguments
            
        Returns:
            Tool execution result
            
        Raises:
            ToolExecutionError: If tool not found or execution fails
        """
        tool = self.get_tool(name)
        
        if tool is None:
            raise ToolExecutionError(name, f"Tool '{name}' not found")
        
        try:
            logger.info(f"Executing tool: {name} with args: {args}")
            result = tool(**args)
            logger.info(f"Tool {name} executed successfully")
            return result
        except Exception as e:
            error_msg = f"Tool execution failed: {str(e)}"
            logger.error(f"Tool {name} failed: {error_msg}")
            raise ToolExecutionError(name, error_msg)
    
    def has_tool(self, name: str) -> bool:
        """
        Check if tool is registered.
        
        Args:
            name: Tool name
            
        Returns:
            True if tool is registered
        """
        return name in self._tools

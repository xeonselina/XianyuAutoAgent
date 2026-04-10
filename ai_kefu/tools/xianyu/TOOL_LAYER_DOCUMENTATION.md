# Xianyu Tools Layer Documentation

## Overview

The `ai_kefu/tools/xianyu/` directory provides high-level tool wrappers for agent integration. These tools are exposed to the AI agent through the `AgentExecutor` and allow the agent to call Xianyu APIs during conversation.

## Architecture

```
┌─────────────────────────────────────────────┐
│ Agent (LLM) with function-calling           │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ AgentExecutor (tools_registry)              │
│ - Manages tool registration                 │
│ - Routes function calls to tools            │
│ - Executes tools synchronously              │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ Tool Layer (tools/xianyu/)                  │
│ - get_item_info.py                          │
│ - get_order_detail.py                       │
│ - get_buyer_info.py ← NEW                   │
│ - send_message.py                           │
│ - ...others...                              │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ XianyuProvider Layer (xianyu_provider/)     │
│ - Abstract interface (base.py)              │
│ - Implementation (goofish_provider.py)      │
│ - Async/sync dual pattern                   │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ HTTP APIs to Xianyu/Taobao                  │
│ https://h5api.m.goofish.com/h5/...          │
│ wss://wss-goofish.dingtalk.com/             │
└─────────────────────────────────────────────┘
```

## New Tool: get_buyer_info

### Purpose
Fetch buyer information including purchase history and location for shipping estimation and customer risk assessment.

### File Location
`ai_kefu/tools/xianyu/get_buyer_info.py`

### Function Signature
```python
def get_buyer_info(buyer_id: str) -> Dict[str, Any]:
    """
    Fetch Xianyu buyer information including purchase history and location.
    
    Returns:
    {
        "success": bool,
        "buyer_id": str,
        "buyer_nick": str,
        "buy_count": int,
        "deal_count": int,
        "trade_count": int,
        "has_bought": bool,
        "user_type": int,
        "location": str,
        "error": str,  # only if success=False
        "_raw_api_response": dict
    }
    """
```

### Tool Definition for Agent
```json
{
    "name": "get_buyer_info",
    "description": "查询闲鱼买家信息和购买历史统计。...",
    "parameters": {
        "type": "object",
        "properties": {
            "buyer_id": {
                "type": "string",
                "description": "闲鱼买家ID"
            }
        },
        "required": ["buyer_id"]
    }
}
```

### Use Cases
1. **Repeat Customer Detection** - Check if buyer has purchased before
2. **Risk Assessment** - Evaluate buyer creditworthiness using purchase history
3. **Shipping Estimation** - Get buyer location for logistics calculation
4. **Customer Service** - Personalize response based on buyer reputation

### Implementation Details
- **Synchronous wrapper**: Calls `asyncio.run()` to execute async provider method
- **Error handling**: Gracefully handles API failures and returns error dict
- **Logging**: Logs success/failure at INFO and WARNING levels
- **Registry**: Automatically registered in `AgentExecutor._register_tools()`

## Integration Points

### 1. Tool Export (__init__.py)
```python
from ai_kefu.tools.xianyu.get_buyer_info import (
    get_buyer_info,
    get_tool_definition as get_buyer_info_definition,
)

__all__ = [
    "get_buyer_info",
    "get_buyer_info_definition",
    ...
]
```

### 2. AgentExecutor Registration (executor.py)
```python
from ai_kefu.tools.xianyu import (
    get_buyer_info,
    get_buyer_info_definition,
)

self.tools_registry.register_tool(
    "get_buyer_info",
    get_buyer_info,
    get_buyer_info_definition()
)
```

### 3. Tool Invocation in Turns
When agent decides to call `get_buyer_info`:
1. LLM returns function call: `{"name": "get_buyer_info", "arguments": {"buyer_id": "user123"}}`
2. `turn.execute_turn()` finds tool in registry
3. Tool is called with arguments
4. Result is returned to LLM for context

## Testing

### Unit Tests
```bash
python3 -m pytest ai_kefu/tools/xianyu/test_get_buyer_info.py -v
```

### Integration Tests
```bash
# Test tool registration
python3 -c "
from ai_kefu.agent.executor import AgentExecutor
from ai_kefu.storage.session_store import SessionStore
executor = AgentExecutor(SessionStore())
assert 'get_buyer_info' in executor.tools_registry.get_all_tools()
print('✓ Tool registered')
"
```

### End-to-End Test (with real Xianyu credentials)
```python
from ai_kefu.tools.xianyu import get_buyer_info

# With valid Xianyu cookies in .env
result = get_buyer_info("buyer_123")
assert result["success"] == True
assert "buyer_nick" in result
print(f"Buyer: {result['buyer_nick']}, Purchases: {result['buy_count']}")
```

## Tool Lifecycle

### Registration Phase
1. `AgentExecutor.__init__()` calls `_register_tools()`
2. Tool is imported and function/definition are extracted
3. Tool is registered in `tools_registry` with name, function, definition

### Execution Phase
1. LLM generates function call in response
2. `turn.execute_turn()` parses function call
3. Registry looks up tool by name
4. Tool function is called with provided arguments
5. Result is captured and returned to LLM

### Error Handling
- **Import errors**: Caught during registration, logged as warning
- **Execution errors**: Caught in try-catch, returned as error dict
- **Async errors**: Handled by `asyncio.run()` wrapper
- **Provider errors**: Propagated from `XianyuProvider` layer

## Performance Considerations

### Caching Opportunity
Since buyer info rarely changes:
```python
# Future enhancement: Add caching decorator
@cache_result(ttl=3600)  # 1 hour
def get_buyer_info(buyer_id: str) -> Dict[str, Any]:
    ...
```

### Async Pattern
The tool currently uses `asyncio.run()` which blocks on async provider. For high-concurrency:
```python
# Consider: Make tool itself async in executor
async def execute_tool(name: str, args: dict):
    if name == "get_buyer_info":
        return await provider.get_buyer_info(args["buyer_id"])
```

## Security Considerations

1. **Input Validation**: buyer_id is converted to string and passed to provider
2. **Authentication**: Relies on xianyu_cookie from environment
3. **Error Messages**: Redacted to avoid exposing internal API details
4. **Rate Limiting**: None currently - add if needed for production

## Related Files Modified/Created

- `ai_kefu/tools/xianyu/get_buyer_info.py` - NEW: Tool implementation
- `ai_kefu/tools/xianyu/__init__.py` - MODIFIED: Added exports
- `ai_kefu/agent/executor.py` - MODIFIED: Added tool registration
- `ai_kefu/xianyu_provider/base.py` - MODIFIED: Added abstract method
- `ai_kefu/xianyu_provider/goofish_provider.py` - MODIFIED: Added implementation

## Next Steps

1. **Testing**: Run integration tests with real environment
2. **Monitoring**: Add metrics tracking for tool calls
3. **Documentation**: Add to system prompt with examples
4. **Optimization**: Consider caching for frequently queried buyers
5. **Enhancement**: Add batch get_buyer_info for multiple buyer IDs

# Qwen 模型集成说明

**创建日期**: 2025-12-23  
**关联**: plan.md, data-model.md

## 概述

本文档说明如何将 Alibaba Qwen 模型集成到 AI 客服系统中，替代原有的 Google Gemini 模型。

## Qwen 模型选择

### 推荐模型

**主模型**: `qwen-plus` 或 `qwen-turbo`

**选择理由**:
- **qwen-plus**: 更强的推理能力,适合复杂客服场景
- **qwen-turbo**: 更快的响应速度,适合高并发场景

**功能支持**:
- 多轮对话
- Function Calling (工具调用)
- 长上下文支持 (最高 32K tokens)
- 中文优化

### API 访问方式

**方式 1**: 阿里云 DashScope SDK (推荐)

```python
from dashscope import Generation

# 配置
api_key = "your-dashscope-api-key"
model_name = "qwen-plus"

# 调用示例
response = Generation.call(
    model=model_name,
    messages=[
        {"role": "system", "content": "你是一个专业的客服助手"},
        {"role": "user", "content": "用户问题"}
    ],
    result_format='message'
)
```

**方式 2**: OpenAI 兼容 API (备选)

Qwen 提供 OpenAI 兼容接口,可以使用 `openai` Python SDK:

```python
from openai import OpenAI

client = OpenAI(
    api_key="your-dashscope-api-key",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

response = client.chat.completions.create(
    model="qwen-plus",
    messages=[...]
)
```

## 集成要点

### 1. Function Calling 适配

Qwen 的 Function Calling 格式与 Gemini 类似但有差异:

**工具定义格式**:
```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "knowledge_search",
            "description": "搜索知识库",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词"
                    }
                },
                "required": ["query"]
            }
        }
    }
]
```

**工具调用响应处理**:
```python
# Qwen 返回格式
if response.output.choices[0].message.tool_calls:
    for tool_call in response.output.choices[0].message.tool_calls:
        function_name = tool_call.function.name
        arguments = json.loads(tool_call.function.arguments)
        # 执行工具调用
```

### 2. 系统提示词适配

Qwen 对中文优化较好,系统提示词可以使用中文:

```python
SYSTEM_PROMPT = """你是一个专业的客服 AI 助手。

你的职责:
1. 理解用户问题并识别意图
2. 使用知识库工具搜索相关信息
3. 提供准确、友好的回答
4. 遇到无法解决的问题时,请求人工协助

可用工具:
- knowledge_search: 搜索知识库
- ask_human_agent: 请求人工客服
- complete_task: 标记问题已解决

请始终保持专业、礼貌的态度。
"""
```

### 3. 错误处理

**常见错误码**:
- `400`: 请求参数错误
- `401`: API key 无效
- `429`: 请求频率超限
- `500`: 服务端错误

**重试策略**:
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
def call_qwen_with_retry(messages, tools=None):
    return Generation.call(
        model="qwen-plus",
        messages=messages,
        tools=tools
    )
```

### 4. 流式响应 (可选)

支持 SSE 流式返回,提升用户体验:

```python
responses = Generation.call(
    model="qwen-plus",
    messages=messages,
    stream=True
)

for response in responses:
    if response.output.choices[0].message.content:
        yield response.output.choices[0].message.content
```

## 配置管理

### 环境变量

```bash
# .env 文件
QWEN_API_KEY=your-dashscope-api-key
QWEN_MODEL=qwen-plus
QWEN_TIMEOUT=60
QWEN_MAX_RETRIES=3
```

### 配置类

```python
# ai_kefu/config/settings.py
from pydantic import BaseSettings

class QwenConfig(BaseSettings):
    api_key: str
    model: str = "qwen-plus"
    timeout: int = 60
    max_retries: int = 3
    temperature: float = 0.7
    top_p: float = 0.9
    
    class Config:
        env_prefix = "QWEN_"
        env_file = ".env"
```

## 性能考虑

### 并发限制

- DashScope 免费版: 10 QPS
- 付费版: 可申请更高限制

**应对策略**:
- 使用连接池管理并发请求
- 实现请求队列和限流
- 缓存常见问题的回答

### 响应时间

**预期延迟**:
- qwen-turbo: 500ms - 1.5s (P95)
- qwen-plus: 1s - 2.5s (P95)

**优化建议**:
- 优化提示词长度
- 使用流式响应改善体验
- 对高频问题启用缓存

## 成本估算

**按 Token 计费** (参考价格,以实际为准):
- qwen-turbo: ¥0.003/1K tokens (输入), ¥0.006/1K tokens (输出)
- qwen-plus: ¥0.008/1K tokens (输入), ¥0.02/1K tokens (输出)

**月度估算** (假设):
- 日均 10,000 次对话
- 每次平均 500 tokens (300 输入 + 200 输出)
- 使用 qwen-plus

计算: 10,000 × 30 × (300 × 0.008 + 200 × 0.02) / 1000 = ¥192/月

## 迁移检查清单

从 Gemini 迁移到 Qwen 需要修改的部分:

- [ ] 更新依赖: 移除 `google-generativeai`, 添加 `dashscope`
- [ ] 修改 Agent 执行器: 适配 Qwen API 调用格式
- [ ] 更新工具定义: 使用 Qwen Function Calling 格式
- [ ] 调整系统提示词: 利用 Qwen 中文优化特性
- [ ] 配置环境变量: QWEN_API_KEY 等
- [ ] 更新错误处理: 处理 Qwen 特定错误码
- [ ] 性能测试: 验证响应时间和并发能力
- [ ] 成本监控: 实现 Token 使用量统计

## 参考资料

- [DashScope 文档](https://help.aliyun.com/zh/dashscope/)
- [Qwen 模型介绍](https://help.aliyun.com/zh/dashscope/developer-reference/model-introduction)
- [Function Calling 指南](https://help.aliyun.com/zh/dashscope/developer-reference/use-qwen-by-calling-api)

# Gemini-CLI Agent 架构分析报告

> 本报告分析 gemini-cli 项目的 agent 架构，评估其对构建 AI 客服 agent 的参考价值。

## 一、核心架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户输入                                  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    AgentExecutor (主循环)                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  while(true) {                                           │   │
│  │    1. CHECK: checkTermination() - 检查终止条件            │   │
│  │    2. CHECK: 检查超时/外部中止信号                        │   │
│  │    3. ACTION: executeTurn() - 执行一轮对话               │   │
│  │    4. CHECK: 检查结果状态 (stop/continue)                │   │
│  │    5. PLAN: 准备下一轮消息                               │   │
│  │  }                                                       │   │
│  │  RECOVERY: executeFinalWarningTurn() - 恢复机制          │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 项目结构

```
gemini-cli/
├── packages/
│   ├── cli/          # 用户界面层 (前端)
│   ├── core/         # 核心逻辑层 (后端)
│   ├── a2a-server/   # Agent-to-Agent 服务器
│   ├── test-utils/   # 测试工具
│   └── vscode-ide-companion/  # VS Code 集成
```

## 二、Plan-Action-Check 模式详解

### 2.1 Plan（规划）

系统提示中定义的工作流程：

```
1. Understand: 理解用户请求和代码上下文
2. Plan: 建立连贯的计划来解决用户任务
```

**关键实现：**

| 组件 | 文件路径 | 职责 |
|------|----------|------|
| 系统提示构建 | `packages/core/src/core/prompts.ts` | 定义 agent 的行为规范 |
| 模型路由 | `packages/core/src/routing/modelRouterService.ts` | 根据上下文选择最佳模型 |
| 工具选择 | `packages/core/src/hooks/types.ts` | 通过 hooks 动态调整可用工具 |

### 2.2 Action（执行）

```typescript
// packages/core/src/agents/executor.ts (第411-417行)
const turnResult = await this.executeTurn(
  chat,
  currentMessage,
  turnCounter++,
  combinedSignal,
  timeoutController.signal,
);
```

**关键组件：**

| 组件 | 文件路径 | 职责 |
|------|----------|------|
| Turn 管理器 | `packages/core/src/core/turn.ts` | 管理单轮对话 |
| CoreToolScheduler | `packages/core/src/core/coreToolScheduler.ts` | 工具调度器 |
| 工具集 | `packages/core/src/tools/` | shell、文件编辑、搜索、网络等 |

### 2.3 Check（检查）

```typescript
// packages/core/src/agents/executor.ts (第394-400行)
const reason = this.checkTermination(startTime, turnCounter);
if (reason) {
  terminateReason = reason;
  break;
}
```

**检查机制：**

| 机制 | 说明 |
|------|------|
| 循环检测 | 检测重复的工具调用和内容 |
| 超时检查 | 最大时间限制 |
| 最大轮次检查 | 防止无限循环 |
| 目标完成检查 | 任务是否完成 |

## 三、核心组件详解

### 3.1 AgentExecutor - 主执行器

**文件位置**: `packages/core/src/agents/executor.ts`

这是 Agent 的核心执行引擎，实现了完整的 Plan-Action-Check 循环：

```typescript
async run(inputs: AgentInputs, signal: AbortSignal): Promise<OutputObject> {
  const startTime = Date.now();
  let turnCounter = 0;
  let terminateReason: AgentTerminateMode = AgentTerminateMode.ERROR;

  while (true) {
    // CHECK: 检查终止条件
    const reason = this.checkTermination(startTime, turnCounter);
    if (reason) { terminateReason = reason; break; }
    
    // CHECK: 检查超时或外部中止
    if (combinedSignal.aborted) { ... break; }
    
    // ACTION: 执行一个 turn
    const turnResult = await this.executeTurn(...);
    
    // CHECK: 检查结果状态
    if (turnResult.status === 'stop') { ... break; }
    
    // PLAN: 准备下一轮消息
    currentMessage = turnResult.nextMessage;
  }

  // RECOVERY: 恢复机制
  if (needsRecovery) {
    await this.executeFinalWarningTurn(...);
  }
}
```

**关键方法：**

| 方法 | 行号 | 职责 |
|------|------|------|
| `run()` | 363-550 | 主执行入口 |
| `executeTurn()` | 182-238 | 单轮执行 |
| `checkTermination()` | 1051-1062 | 终止条件检查 |
| `processFunctionCalls()` | 687-905 | 处理工具调用 |
| `executeFinalWarningTurn()` | 272-354 | 恢复机制 |

#### 3.1.1 executeTurn 详解 - 单轮执行的核心逻辑

`executeTurn` 是 Agent 执行的核心方法，负责完成一轮完整的"调用模型 → 处理工具调用 → 返回结果"流程。

**方法签名：**

```typescript
private async executeTurn(
  chat: GeminiChat,           // 聊天会话对象
  currentMessage: Content,     // 当前要发送的消息
  turnCounter: number,         // 当前轮次计数
  combinedSignal: AbortSignal, // 组合的中止信号（外部+超时）
  timeoutSignal: AbortSignal,  // 超时信号（用于区分中止原因）
): Promise<AgentTurnResult>
```

**返回类型：**

```typescript
type AgentTurnResult = 
  | { status: 'stop'; terminateReason: AgentTerminateMode; finalResult: string | null }
  | { status: 'continue'; nextMessage: Content }
```

**执行流程图：**

```
┌─────────────────────────────────────────────────────────────────┐
│                      executeTurn 执行流程                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Step 1: 尝试压缩历史记录                                 │    │
│  │ await this.tryCompressChat(chat, promptId)              │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              ↓                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Step 2: 调用模型                                         │    │
│  │ const { functionCalls } = await this.callModel(...)     │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              ↓                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Step 3: 检查是否被中止                                   │    │
│  │ if (combinedSignal.aborted) → return STOP               │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              ↓                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Step 4: 检查是否有工具调用                               │    │
│  │ if (functionCalls.length === 0) → return ERROR          │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              ↓                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Step 5: 处理工具调用                                     │    │
│  │ const result = await this.processFunctionCalls(...)     │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              ↓                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Step 6: 检查任务是否完成                                 │    │
│  │ if (taskCompleted) → return GOAL                        │    │
│  │ else → return CONTINUE with nextMessage                 │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**完整代码解析：**

```typescript
private async executeTurn(
  chat: GeminiChat,
  currentMessage: Content,
  turnCounter: number,
  combinedSignal: AbortSignal,
  timeoutSignal: AbortSignal,
): Promise<AgentTurnResult> {
  // 生成唯一的 promptId，用于追踪和日志
  const promptId = `${this.agentId}#${turnCounter}`;

  // ============ Step 1: 历史压缩 ============
  // 当对话历史过长时，压缩历史以节省 token
  await this.tryCompressChat(chat, promptId);

  // ============ Step 2: 调用模型 ============
  // 在 promptId 上下文中调用模型，获取响应
  const { functionCalls } = await promptIdContext.run(promptId, async () =>
    this.callModel(chat, currentMessage, combinedSignal, promptId),
  );

  // ============ Step 3: 检查中止信号 ============
  // 区分是超时还是外部中止
  if (combinedSignal.aborted) {
    const terminateReason = timeoutSignal.aborted
      ? AgentTerminateMode.TIMEOUT    // 超时导致的中止
      : AgentTerminateMode.ABORTED;   // 用户/外部导致的中止
    return {
      status: 'stop',
      terminateReason,
      finalResult: null,
    };
  }

  // ============ Step 4: 检查工具调用 ============
  // 如果模型没有调用任何工具，也没有调用 complete_task，视为协议违规
  if (functionCalls.length === 0) {
    this.emitActivity('ERROR', {
      error: `Agent stopped calling tools but did not call 'complete_task' to finalize the session.`,
      context: 'protocol_violation',
    });
    return {
      status: 'stop',
      terminateReason: AgentTerminateMode.ERROR_NO_COMPLETE_TASK_CALL,
      finalResult: null,
    };
  }

  // ============ Step 5: 处理工具调用 ============
  // 执行所有工具调用，收集结果
  const { nextMessage, submittedOutput, taskCompleted } =
    await this.processFunctionCalls(functionCalls, combinedSignal, promptId);

  // ============ Step 6: 返回结果 ============
  if (taskCompleted) {
    // 任务完成，返回最终结果
    const finalResult = submittedOutput ?? 'Task completed successfully.';
    return {
      status: 'stop',
      terminateReason: AgentTerminateMode.GOAL,
      finalResult,
    };
  }

  // 任务未完成，继续下一轮
  return {
    status: 'continue',
    nextMessage,  // 工具调用的结果，作为下一轮的输入
  };
}
```

**关键子方法解析：**

##### callModel - 调用模型

```typescript
private async callModel(
  chat: GeminiChat,
  message: Content,
  signal: AbortSignal,
  promptId: string,
): Promise<{ functionCalls: FunctionCall[]; textResponse: string }> {
  // 发送消息到模型，获取流式响应
  const responseStream = await chat.sendMessageStream(...);

  const functionCalls: FunctionCall[] = [];
  let textResponse = '';

  // 处理流式响应
  for await (const resp of responseStream) {
    if (signal.aborted) break;

    if (resp.type === StreamEventType.CHUNK) {
      const chunk = resp.value;
      const parts = chunk.candidates?.[0]?.content?.parts;

      // 1. 提取并发送 "思考" 内容（用于 UI 显示）
      const { subject } = parseThought(parts?.find((p) => p.thought)?.text || '');
      if (subject) {
        this.emitActivity('THOUGHT_CHUNK', { text: subject });
      }

      // 2. 收集工具调用请求
      if (chunk.functionCalls) {
        functionCalls.push(...chunk.functionCalls);
      }

      // 3. 收集文本响应（非思考内容）
      const text = parts?.filter((p) => !p.thought && p.text).map((p) => p.text).join('') || '';
      if (text) {
        textResponse += text;
      }
    }
  }

  return { functionCalls, textResponse };
}
```

##### processFunctionCalls - 处理工具调用

```typescript
private async processFunctionCalls(
  functionCalls: FunctionCall[],
  signal: AbortSignal,
  promptId: string,
): Promise<{
  nextMessage: Content;        // 下一轮的消息（包含工具执行结果）
  submittedOutput: string | null;  // 最终输出（如果任务完成）
  taskCompleted: boolean;      // 任务是否完成
}> {
  const allowedToolNames = new Set(this.toolRegistry.getAllToolNames());
  allowedToolNames.add(TASK_COMPLETE_TOOL_NAME);  // 始终允许完成工具

  let submittedOutput: string | null = null;
  let taskCompleted = false;
  
  const toolExecutionPromises: Array<Promise<Part[] | void>> = [];
  const syncResponseParts: Part[] = [];

  for (const [index, functionCall] of functionCalls.entries()) {
    const callId = functionCall.id ?? `${promptId}-${index}`;
    const args = (functionCall.args ?? {}) as Record<string, unknown>;

    // 发送工具调用开始事件
    this.emitActivity('TOOL_CALL_START', { name: functionCall.name, args });

    // ========== 处理 complete_task 工具 ==========
    if (functionCall.name === TASK_COMPLETE_TOOL_NAME) {
      // 验证输出、标记任务完成
      taskCompleted = true;
      submittedOutput = processOutput(args);
      continue;
    }

    // ========== 处理未授权的工具 ==========
    if (!allowedToolNames.has(functionCall.name)) {
      syncResponseParts.push({
        functionResponse: {
          name: functionCall.name,
          response: { error: 'Unauthorized tool call' },
        },
      });
      continue;
    }

    // ========== 处理普通工具（并行执行）==========
    const executionPromise = (async () => {
      const { response: toolResponse } = await executeToolCall(
        this.runtimeContext,
        requestInfo,
        signal,
      );
      return toolResponse.responseParts;
    })();

    toolExecutionPromises.push(executionPromise);
  }

  // 等待所有工具执行完成
  const asyncResults = await Promise.all(toolExecutionPromises);

  // 合并所有响应
  const toolResponseParts: Part[] = [...syncResponseParts];
  for (const result of asyncResults) {
    if (result) toolResponseParts.push(...result);
  }

  return {
    nextMessage: { role: 'user', parts: toolResponseParts },
    submittedOutput,
    taskCompleted,
  };
}
```

**executeTurn 的设计亮点：**

| 设计点 | 说明 | 客服场景参考 |
|--------|------|--------------|
| **历史压缩** | 对话过长时自动压缩，节省 token | 长对话客服场景必备 |
| **中止信号区分** | 区分超时和用户中止，便于不同处理 | 区分用户主动结束和系统超时 |
| **协议违规检测** | 模型不调用工具时报错 | 确保 agent 按预期工作 |
| **并行工具执行** | 多个工具调用并行执行 | 提高响应速度 |
| **任务完成标记** | 通过 complete_task 工具显式标记完成 | 明确的会话结束机制 |

**客服场景的 executeTurn 改造建议：**

```typescript
// 客服场景的 executeTurn 可能需要增加：
private async executeTurn(...): Promise<AgentTurnResult> {
  // 1. 情绪分析（在调用模型前）
  const sentiment = await this.analyzeSentiment(currentMessage);
  if (sentiment === 'angry') {
    // 触发安抚策略或转人工
  }

  // 2. 意图识别
  const intent = await this.recognizeIntent(currentMessage);
  
  // 3. 调用模型（可能根据意图选择不同的 prompt）
  const { functionCalls } = await this.callModel(...);

  // 4. 处理工具调用
  const result = await this.processFunctionCalls(...);

  // 5. 满意度检查（如果任务完成）
  if (result.taskCompleted) {
    await this.requestSatisfactionFeedback();
  }

  return result;
}
```

### 3.2 Turn 管理器

**文件位置**: `packages/core/src/core/turn.ts`

管理与 Gemini API 的单次交互：

```typescript
export class Turn {
  readonly pendingToolCalls: ToolCallRequestInfo[] = [];
  
  async *run(modelConfigKey, req, signal): AsyncGenerator<ServerGeminiStreamEvent> {
    // 发送消息到模型，处理响应流
    // 收集 function calls，处理 thoughts
  }
}
```

**事件类型：**

| 事件 | 说明 |
|------|------|
| `Content` | 文本内容 |
| `ToolCallRequest` | 工具调用请求 |
| `ToolCallResponse` | 工具调用响应 |
| `Thought` | 思考过程 |
| `LoopDetected` | 循环检测 |
| `Finished` | 完成 |

### 3.3 CoreToolScheduler - 工具调度器

**文件位置**: `packages/core/src/core/coreToolScheduler.ts`

管理工具调用的完整生命周期：

```typescript
// 工具调用状态机
type ToolCall = 
  | ValidatingToolCall    // 验证中
  | ScheduledToolCall     // 已调度
  | ExecutingToolCall     // 执行中
  | WaitingToolCall       // 等待审批
  | SuccessfulToolCall    // 成功
  | ErroredToolCall       // 错误
  | CancelledToolCall;    // 已取消
```

**状态流转：**

```
Validating → Scheduled → Executing → Success
                ↓            ↓
             Waiting      Error/Cancelled
           (需要用户确认)
```

**核心流程：**

| 方法 | 职责 |
|------|------|
| `schedule()` | 调度工具调用 |
| `_processNextInQueue()` | 处理队列 |
| `attemptExecutionOfScheduledCalls()` | 执行调度的调用 |
| `handleConfirmationResponse()` | 处理用户确认 |

### 3.4 LoopDetectionService - 循环检测

**文件位置**: `packages/core/src/services/loopDetectionService.ts`

防止 agent 陷入无限循环：

```typescript
// 关键阈值
const TOOL_CALL_LOOP_THRESHOLD = 5;    // 工具调用重复阈值
const CONTENT_LOOP_THRESHOLD = 10;      // 内容重复阈值
const LLM_CHECK_AFTER_TURNS = 30;       // 30轮后启用 LLM 辅助检测
const LLM_CONFIDENCE_THRESHOLD = 0.9;   // LLM 检测置信度阈值
```

**检测策略：**

| 策略 | 说明 |
|------|------|
| 工具调用重复检测 | 检测相同工具+参数的重复调用 |
| 内容重复检测 | 检测重复的响应内容 |
| LLM 辅助检测 | 30轮后启用，使用 LLM 判断是否陷入循环 |

### 3.5 Hooks 系统

**文件位置**: `packages/core/src/hooks/`

提供可扩展的事件钩子：

```typescript
export enum HookEventName {
  BeforeTool = 'BeforeTool',           // 工具执行前
  AfterTool = 'AfterTool',             // 工具执行后
  BeforeAgent = 'BeforeAgent',         // Agent 处理前
  AfterAgent = 'AfterAgent',           // Agent 处理后
  BeforeModel = 'BeforeModel',         // 模型调用前
  AfterModel = 'AfterModel',           // 模型调用后
  BeforeToolSelection = 'BeforeToolSelection',  // 工具选择前
  SessionStart = 'SessionStart',       // 会话开始
  SessionEnd = 'SessionEnd',           // 会话结束
  PreCompress = 'PreCompress',         // 压缩前
  Notification = 'Notification',       // 通知
}
```

**核心组件：**

| 组件 | 职责 |
|------|------|
| `HookEventHandler` | 事件处理器 |
| `HookPlanner` | 执行计划器 |
| `HookRunner` | 执行器 |
| `HookAggregator` | 结果聚合器 |

## 四、任务计划与执行机制详解

Gemini-CLI 的任务计划和执行是通过**系统提示（System Prompt）+ 工具调用（Tool Calls）+ 子代理（Sub-agents）**三者协同实现的。

### 4.1 任务执行的整体流程

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        用户输入任务                                          │
│                    "帮我修复登录功能的 bug"                                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Phase 1: UNDERSTAND (理解)                               │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  简单任务：直接使用 grep/glob/read_file 工具搜索                     │    │
│  │  复杂任务：调用 delegate_to_agent → codebase_investigator          │    │
│  │           子代理进行深度代码分析，返回结构化报告                      │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Phase 2: PLAN (计划)                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  简单任务：直接在思考中规划步骤                                       │    │
│  │  复杂任务：调用 write_todos 工具创建任务清单                          │    │
│  │           1. [pending] 修改 auth.ts 中的验证逻辑                     │    │
│  │           2. [pending] 更新相关的单元测试                            │    │
│  │           3. [pending] 运行测试验证修复                              │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Phase 3: IMPLEMENT (实现)                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  循环执行每个子任务：                                                 │    │
│  │  1. write_todos: 标记当前任务为 in_progress                         │    │
│  │  2. 使用工具执行：edit/write_file/shell 等                          │    │
│  │  3. write_todos: 标记任务为 completed                               │    │
│  │  4. 继续下一个任务...                                               │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Phase 4: VERIFY (验证)                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  1. 运行测试：shell → npm test / pytest 等                          │    │
│  │  2. 代码检查：shell → tsc / eslint / ruff 等                        │    │
│  │  3. 构建验证：shell → npm run build 等                              │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Phase 5: FINALIZE (完成)                                  │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  调用 complete_task 工具，标记任务完成                                │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 系统提示中的工作流定义

系统提示（`prompts.ts`）定义了 Agent 的标准工作流程：

#### 软件工程任务工作流

```
1. Understand（理解）
   - 使用 grep/glob 工具搜索代码库
   - 使用 read_file 读取相关文件
   - 复杂任务：委托给 codebase_investigator 子代理

2. Plan（计划）
   - 基于理解阶段的信息制定计划
   - 复杂任务：使用 write_todos 工具记录子任务
   - 向用户展示简洁的计划摘要

3. Implement（实现）
   - 使用 edit/write_file 修改代码
   - 使用 shell 执行命令
   - 严格遵循项目约定

4. Verify - Tests（测试验证）
   - 运行项目的测试套件
   - 检查测试是否通过

5. Verify - Standards（标准验证）
   - 运行 lint、type-check、build
   - 确保代码质量

6. Finalize（完成）
   - 所有验证通过后完成任务
```

#### 新应用开发工作流

```
1. Understand Requirements（理解需求）
   - 分析核心功能、UX、技术栈

2. Propose Plan（提出计划）
   - 制定开发计划
   - 选择技术栈（React/Vue/Python 等）

3. User Approval（用户确认）- 交互模式
   - 获取用户对计划的确认

4. Implementation（实现）
   - 脚手架搭建（npm init 等）
   - 逐步实现功能

5. Verify（验证）
   - 检查是否符合需求
   - 确保无编译错误

6. Solicit Feedback（收集反馈）
   - 提供启动说明
   - 请求用户反馈
```

### 4.3 write_todos 工具 - 任务追踪

**文件位置**: `packages/core/src/tools/write-todos.ts`

这是 Gemini-CLI 用于追踪复杂任务进度的核心工具。

#### 任务状态定义

```typescript
const TODO_STATUSES = [
  'pending',      // 待处理：工作尚未开始
  'in_progress',  // 进行中：正在处理（同一时间只能有一个）
  'completed',    // 已完成：成功完成
  'cancelled',    // 已取消：不再需要
] as const;
```

#### 使用方法论

```
1. 收到用户请求后，根据任务复杂度决定是否使用 todo list
2. 追踪每个子任务的状态
3. 开始工作前将任务标记为 in_progress（同一时间只能有一个）
4. 随着执行进展更新任务列表（列表是动态的，会随新信息演变）
5. 完成后标记为 completed
6. 不再需要的任务标记为 cancelled
7. 必须及时更新，不要批量更新
```

#### 使用示例

**用户请求**: "创建一个使用 gemini-2.5-flash-image 生成 logo 的 React 网站"

**Agent 创建的 Todo List**:

```
1. [pending] 初始化 React 项目环境（使用 Vite）
2. [pending] 设计核心 UI 组件：文本输入、样式选择、图片预览区
3. [pending] 实现状态管理（React Context 或 Zustand）
4. [pending] 创建 API 服务模块，对接 gemini-2.5-flash-image
5. [pending] 实现异步逻辑：加载状态、成功/错误处理
6. [pending] 显示生成的 logo
7. [pending] 添加下载功能
8. [pending] 部署应用
```

**执行过程**:

```
Turn 1: write_todos → 创建上述列表
Turn 2: write_todos → 标记 #1 为 in_progress
        shell → npm create vite@latest
Turn 3: write_todos → 标记 #1 为 completed, #2 为 in_progress
        edit → 创建 UI 组件
Turn 4: write_todos → 标记 #2 为 completed, #3 为 in_progress
        ...以此类推
```

#### 何时使用 / 不使用

**使用场景**:
- 从零构建完整 Web 应用
- 复杂的多步骤重构
- 需要多个文件修改的功能开发

**不使用场景**:
- 简单的测试修复循环（运行测试 → 修改 → 运行测试）
- 单文件的简单修改
- 2 步以内可完成的任务

### 4.4 delegate_to_agent 工具 - 子代理委托

**文件位置**: `packages/core/src/agents/delegate-to-agent-tool.ts`

当任务涉及复杂的代码分析时，主 Agent 可以委托给专门的子代理。

#### 工作原理

```typescript
// 主 Agent 调用
delegate_to_agent({
  agent_name: 'codebase_investigator',
  objective: '分析登录模块的架构，找出 bug 的根本原因'
})

// 内部流程
class DelegateInvocation {
  async execute(signal, updateOutput) {
    // 1. 从注册表获取子代理定义
    const definition = this.registry.getDefinition(this.params.agent_name);
    
    // 2. 创建子代理调用实例
    const subagentInvocation = new SubagentInvocation(
      agentArgs,      // 传递给子代理的参数
      definition,     // 子代理定义
      this.config,
      this.messageBus,
    );
    
    // 3. 执行子代理
    return subagentInvocation.execute(signal, updateOutput);
  }
}
```

### 4.5 codebase_investigator 子代理 - 代码分析专家

**文件位置**: `packages/core/src/agents/codebase-investigator.ts`

这是一个专门用于深度代码分析的子代理。

#### 子代理配置

```typescript
export const CodebaseInvestigatorAgent: AgentDefinition = {
  name: 'codebase_investigator',
  displayName: 'Codebase Investigator Agent',
  description: '专门用于代码库分析、架构映射和系统依赖理解的工具',
  
  // 输入配置
  inputConfig: {
    inputs: {
      objective: {
        description: '用户目标的详细描述',
        type: 'string',
        required: true,
      },
    },
  },
  
  // 输出配置 - 结构化报告
  outputConfig: {
    outputName: 'report',
    schema: z.object({
      SummaryOfFindings: z.string(),      // 发现摘要
      ExplorationTrace: z.array(z.string()), // 探索轨迹
      RelevantLocations: z.array(z.object({  // 相关位置
        FilePath: z.string(),
        Reasoning: z.string(),
        KeySymbols: z.array(z.string()),
      })),
    }),
  },
  
  // 模型配置
  modelConfig: {
    model: 'gemini-pro',  // 使用 Pro 模型进行深度分析
    temp: 0.1,            // 低温度，更确定性的输出
  },
  
  // 运行限制
  runConfig: {
    max_time_minutes: 5,  // 最多 5 分钟
    max_turns: 15,        // 最多 15 轮
  },
  
  // 工具配置 - 只读工具
  toolConfig: {
    tools: ['ls', 'read_file', 'glob', 'grep'],  // 只能读取，不能修改
  },
};
```

#### 子代理工作流程

```
┌─────────────────────────────────────────────────────────────────┐
│              Codebase Investigator 工作流程                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. 初始化 Scratchpad（草稿本）                                  │
│     - 创建调查目标清单                                           │
│     - 记录待解决的问题                                           │
│                                                                 │
│  2. 系统性探索                                                   │
│     - 从高价值线索开始（错误堆栈、关键词）                        │
│     - 使用 grep 搜索关键函数                                     │
│     - 使用 read_file 深入分析代码                                │
│     - 使用 ls 了解目录结构                                       │
│                                                                 │
│  3. 持续更新 Scratchpad                                         │
│     - [x] 已完成的调查项                                         │
│     - [ ] 新发现的待调查项                                       │
│     - 关键发现记录                                               │
│     - 排除的无关路径                                             │
│                                                                 │
│  4. 完成条件                                                     │
│     - 所有"待解决问题"已清空                                     │
│     - 已识别所有相关文件和变更考虑                                │
│                                                                 │
│  5. 输出结构化报告                                               │
│     {                                                           │
│       "SummaryOfFindings": "核心问题是...",                      │
│       "ExplorationTrace": ["grep搜索...", "读取文件..."],        │
│       "RelevantLocations": [                                    │
│         { "FilePath": "src/auth.ts", "KeySymbols": [...] }      │
│       ]                                                         │
│     }                                                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 4.6 完整执行示例

**用户请求**: "修复用户登录时偶发的 session 丢失问题"

```
┌─────────────────────────────────────────────────────────────────┐
│ Turn 1: 理解任务复杂度                                           │
├─────────────────────────────────────────────────────────────────┤
│ Agent 思考: 这是一个复杂的 bug，涉及 session 管理，需要深入分析   │
│                                                                 │
│ 工具调用: delegate_to_agent                                      │
│ 参数: {                                                         │
│   agent_name: "codebase_investigator",                          │
│   objective: "分析 session 管理机制，找出导致偶发丢失的原因"      │
│ }                                                               │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 子代理执行 (codebase_investigator)                               │
├─────────────────────────────────────────────────────────────────┤
│ Sub-Turn 1: grep "session" → 找到 session.ts, auth.ts           │
│ Sub-Turn 2: read_file session.ts → 发现 race condition 风险     │
│ Sub-Turn 3: grep "updateSession" → 找到所有调用点                │
│ Sub-Turn 4: read_file auth.ts → 确认问题根因                     │
│ Sub-Turn 5: complete_task → 返回结构化报告                       │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Turn 2: 制定计划                                                 │
├─────────────────────────────────────────────────────────────────┤
│ Agent 收到报告: race condition 在 updateSession 函数             │
│                                                                 │
│ 工具调用: write_todos                                            │
│ 参数: {                                                         │
│   todos: [                                                      │
│     { description: "在 session.ts 添加锁机制", status: "pending" },│
│     { description: "更新 updateSession 使用原子操作", status: "pending" },│
│     { description: "添加 session 恢复逻辑", status: "pending" },  │
│     { description: "编写单元测试验证修复", status: "pending" },   │
│     { description: "运行完整测试套件", status: "pending" }        │
│   ]                                                             │
│ }                                                               │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Turn 3: 开始实现                                                 │
├─────────────────────────────────────────────────────────────────┤
│ 工具调用 1: write_todos (标记 #1 为 in_progress)                 │
│ 工具调用 2: edit (修改 session.ts，添加锁机制)                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Turn 4: 继续实现                                                 │
├─────────────────────────────────────────────────────────────────┤
│ 工具调用 1: write_todos (标记 #1 completed, #2 in_progress)      │
│ 工具调用 2: edit (修改 updateSession 函数)                       │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                           ... 
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Turn 7: 验证                                                     │
├─────────────────────────────────────────────────────────────────┤
│ 工具调用 1: write_todos (标记 #4 completed, #5 in_progress)      │
│ 工具调用 2: shell (npm test)                                     │
│ 结果: All tests passed ✓                                        │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Turn 8: 完成                                                     │
├─────────────────────────────────────────────────────────────────┤
│ 工具调用 1: write_todos (标记 #5 completed)                      │
│ 工具调用 2: complete_task                                        │
│ 参数: { result: "已修复 session 丢失问题，添加了锁机制..." }     │
└─────────────────────────────────────────────────────────────────┘
```

### 4.7 关键设计总结

| 机制 | 实现方式 | 作用 |
|------|----------|------|
| **任务理解** | 系统提示 + 搜索工具 | 建立对任务的完整理解 |
| **深度分析** | delegate_to_agent + 子代理 | 复杂任务的专业分析 |
| **任务分解** | write_todos 工具 | 将大任务拆分为可追踪的子任务 |
| **进度追踪** | todo 状态机 | pending → in_progress → completed |
| **执行循环** | executeTurn 主循环 | 一步一步执行并检查 |
| **验证机制** | shell 工具 | 运行测试、lint、build |
| **完成标记** | complete_task 工具 | 显式标记任务完成 |

### 4.8 对客服 Agent 的启示

| Gemini-CLI 机制 | 客服场景对应 |
|-----------------|--------------|
| codebase_investigator | 知识库深度检索 Agent |
| write_todos | 多步骤问题处理追踪 |
| delegate_to_agent | 专家系统委托（如退款专家、技术专家） |
| 系统提示工作流 | 客服 SOP 流程定义 |
| complete_task | 问题解决确认 |
| 子代理结构化输出 | 工单信息结构化 |

## 五、关键 Prompt 分析

Gemini-CLI 的 Prompt 设计是其 Agent 能力的核心，包含主系统提示、子代理提示、历史压缩提示、循环检测提示等多个层次。

### 5.1 主系统提示 (Core System Prompt)

**文件位置**: `packages/core/src/core/prompts.ts`

主系统提示定义了 Agent 的身份、行为规范和工作流程，是整个 Agent 行为的基础。

#### 5.1.1 Prompt 结构

```
┌─────────────────────────────────────────────────────────────────┐
│                    主系统提示结构                                 │
├─────────────────────────────────────────────────────────────────┤
│  1. Preamble (序言)                                              │
│     - 定义 Agent 身份和主要目标                                   │
│                                                                 │
│  2. Core Mandates (核心准则)                                     │
│     - 代码规范、库使用、风格、注释等强制要求                        │
│                                                                 │
│  3. Primary Workflows (主要工作流)                               │
│     - 软件工程任务工作流                                          │
│     - 新应用开发工作流                                            │
│                                                                 │
│  4. Operational Guidelines (操作指南)                            │
│     - 语气风格、安全规则、工具使用                                 │
│                                                                 │
│  5. Sandbox (沙箱说明)                                           │
│     - 运行环境限制说明                                            │
│                                                                 │
│  6. Git (Git 操作指南)                                           │
│     - Git 仓库操作规范                                            │
│                                                                 │
│  7. Final Reminder (最终提醒)                                    │
│     - 核心功能和注意事项总结                                       │
└─────────────────────────────────────────────────────────────────┘
```

#### 5.1.2 Preamble - 身份定义

```
You are an interactive CLI agent specializing in software engineering tasks. 
Your primary goal is to help users safely and efficiently, adhering strictly 
to the following instructions and utilizing your available tools.
```

**设计要点**：
- 明确身份：CLI agent + 软件工程专家
- 明确目标：安全、高效地帮助用户
- 明确约束：严格遵循指令、使用可用工具

**客服场景改造**：
```
You are a professional customer service agent specializing in [业务领域]. 
Your primary goal is to help customers resolve their issues efficiently 
and professionally, ensuring customer satisfaction while adhering to 
company policies.
```

#### 5.1.3 Core Mandates - 核心准则

```markdown
# Core Mandates

- **Conventions:** 严格遵循现有项目规范
- **Libraries/Frameworks:** 不要假设库可用，先验证
- **Style & Structure:** 模仿现有代码风格
- **Idiomatic Changes:** 确保修改自然融入
- **Comments:** 谨慎添加注释，只解释"为什么"
- **Proactiveness:** 彻底完成用户请求
- **Confirm Ambiguity:** 不确定时先确认
- **Explaining Changes:** 完成后不要主动总结
- **Do Not revert:** 不要主动撤销更改
```

**设计要点**：
- 使用 **粗体** 标记关键词
- 每条准则简洁明确
- 覆盖常见问题场景

**客服场景改造**：
```markdown
# Core Mandates

- **Politeness:** 始终保持礼貌、专业的语气
- **Accuracy:** 只提供准确的信息，不确定时明确告知
- **Empathy:** 理解客户情绪，适时安抚
- **Efficiency:** 快速定位问题，避免冗余对话
- **Escalation:** 无法解决时及时转人工
- **Privacy:** 严格保护客户隐私信息
- **Compliance:** 遵守公司政策和法规要求
```

#### 5.1.4 Primary Workflows - 工作流定义

**软件工程任务工作流**：

```markdown
## Software Engineering Tasks

1. **Understand:** 
   - 使用 grep/glob 工具搜索代码库
   - 使用 read_file 读取相关文件
   - 复杂任务：委托给 codebase_investigator 子代理

2. **Plan:** 
   - 基于理解阶段的信息制定计划
   - 复杂任务：使用 write_todos 工具记录子任务
   - 向用户展示简洁的计划摘要

3. **Implement:** 
   - 使用 edit/write_file/shell 工具执行
   - 严格遵循项目规范

4. **Verify (Tests):** 
   - 运行项目测试套件
   - 不要假设测试命令

5. **Verify (Standards):** 
   - 运行 lint、type-check、build
   - 确保代码质量

6. **Finalize:** 
   - 验证通过后完成任务
   - 等待用户下一步指令
```

**新应用开发工作流**：

```markdown
## New Applications

1. **Understand Requirements:** 分析核心功能、UX、技术栈

2. **Propose Plan:** 
   - 制定开发计划
   - 推荐技术栈：
     - 网站前端：React/Angular + Bootstrap + Material Design
     - 后端 API：Node.js + Express 或 Python + FastAPI
     - 全栈：Next.js 或 Django/Flask + React/Vue
     - CLI：Python 或 Go
     - 移动端：Compose Multiplatform 或 Flutter
     - 3D 游戏：Three.js
     - 2D 游戏：HTML/CSS/JavaScript

3. **User Approval:** 获取用户确认

4. **Implementation:** 
   - 使用脚手架工具初始化
   - 逐步实现功能

5. **Verify:** 检查需求、修复问题

6. **Solicit Feedback:** 提供启动说明，收集反馈
```

**客服场景工作流**：

```markdown
## Customer Service Workflow

1. **Greet & Identify:**
   - 礼貌问候
   - 识别客户身份（如有必要）

2. **Understand:**
   - 理解客户问题
   - 识别意图和情绪
   - 必要时追问澄清

3. **Search & Analyze:**
   - 搜索知识库
   - 查询客户信息/订单
   - 分析问题根因

4. **Respond:**
   - 提供解决方案
   - 清晰、准确地回答
   - 提供操作指引

5. **Confirm:**
   - 确认问题是否解决
   - 询问是否有其他问题

6. **Close:**
   - 礼貌结束对话
   - 必要时创建工单跟进
```

#### 5.1.5 Operational Guidelines - 操作指南

**语气和风格**：

```markdown
## Tone and Style (CLI Interaction)

- **Concise & Direct:** 专业、直接、简洁
- **Minimal Output:** 每次响应不超过 3 行（不含代码）
- **Clarity over Brevity:** 必要时优先清晰而非简洁
- **No Chitchat:** 避免对话填充语
- **Formatting:** 使用 GitHub-flavored Markdown
- **Tools vs. Text:** 工具用于操作，文本用于沟通
- **Handling Inability:** 无法完成时简短说明
```

**安全规则**：

```markdown
## Security and Safety Rules

- **Explain Critical Commands:** 执行修改命令前必须解释
- **Security First:** 永远不要暴露敏感信息
```

**工具使用**：

```markdown
## Tool Usage

- **Parallelism:** 独立工具调用并行执行
- **Background Processes:** 长期运行的命令使用后台进程
- **Interactive Commands:** 优先使用非交互命令
- **Remembering Facts:** 使用 memory 工具记住用户偏好
- **Respect User Confirmations:** 尊重用户的取消操作
```

### 5.2 子代理提示 - Codebase Investigator

**文件位置**: `packages/core/src/agents/codebase-investigator.ts`

这是专门用于代码分析的子代理的系统提示。

#### 5.2.1 身份定义

```
You are **Codebase Investigator**, a hyper-specialized AI agent and an 
expert in reverse-engineering complex software projects. You are a 
sub-agent within a larger development system.

Your **SOLE PURPOSE** is to build a complete mental model of the code 
relevant to a given investigation.
```

#### 5.2.2 核心指令 (Core Directives)

```markdown
<RULES>
1. **DEEP ANALYSIS, NOT JUST FILE FINDING:** 
   理解代码背后的"为什么"，不只是列出文件

2. **SYSTEMATIC & CURIOUS EXPLORATION:** 
   从高价值线索开始，像高级工程师做代码审查一样思考
   发现不理解的地方，必须优先调查清楚

3. **HOLISTIC & PRECISE:** 
   找到完整且最小的相关位置集合
   考虑修复的副作用

4. **Web Search:** 
   可以使用 web_fetch 研究不了解的库或概念
</RULES>
```

#### 5.2.3 Scratchpad 管理

```markdown
## Scratchpad Management

**这是最关键的功能。Scratchpad 是你的记忆和计划。**

1. **Initialization:** 
   第一轮必须创建 <scratchpad>
   分析任务，创建初始 Checklist 和 Questions to Resolve

2. **Constant Updates:** 
   每次 <OBSERVATION> 后必须更新：
   - 标记完成的项目：[x]
   - 添加新发现的待调查项
   - 记录 Key Findings
   - 更新 Irrelevant Paths to Ignore

3. **Thinking on Paper:** 
   Scratchpad 必须展示推理过程
```

#### 5.2.4 结构化输出

```json
{
  "SummaryOfFindings": "核心问题是 updateUser 函数中的竞态条件...",
  "ExplorationTrace": [
    "使用 grep 搜索 updateUser 定位主函数",
    "读取 src/controllers/userController.js 理解函数逻辑",
    "使用 ls -R 查找相关文件"
  ],
  "RelevantLocations": [
    {
      "FilePath": "src/controllers/userController.js",
      "Reasoning": "包含有竞态条件的 updateUser 函数",
      "KeySymbols": ["updateUser", "getUser", "saveUser"]
    }
  ]
}
```

### 5.3 历史压缩提示 (Compression Prompt)

**文件位置**: `packages/core/src/core/prompts.ts` - `getCompressionPrompt()`

当对话历史过长时，使用此提示压缩历史。

```markdown
You are the component that summarizes internal chat history into a given structure.

When the conversation history grows too large, you will be invoked to distill 
the entire history into a concise, structured XML snapshot. This snapshot is 
CRITICAL, as it will become the agent's *only* memory of the past.

First, think through the entire history in a private <scratchpad>.
After reasoning, generate the final <state_snapshot> XML object.
```

#### 压缩输出结构

```xml
<state_snapshot>
    <overall_goal>
        <!-- 用户的高层目标，一句话 -->
    </overall_goal>

    <key_knowledge>
        <!-- 关键事实、约定、约束 -->
        - Build Command: `npm run build`
        - Testing: Tests are run with `npm test`
    </key_knowledge>

    <file_system_state>
        <!-- 文件状态：创建、读取、修改、删除 -->
        - CWD: `/home/user/project/src`
        - MODIFIED: `services/auth.ts` - 替换了 JWT 库
    </file_system_state>

    <recent_actions>
        <!-- 最近的重要操作和结果 -->
        - Ran `npm run test`, failed due to snapshot mismatch
    </recent_actions>

    <current_plan>
        <!-- 当前计划，标记完成状态 -->
        1. [DONE] 识别使用废弃 API 的文件
        2. [IN PROGRESS] 重构 UserProfile.tsx
        3. [TODO] 更新测试
    </current_plan>
</state_snapshot>
```

### 5.4 循环检测提示 (Loop Detection Prompt)

**文件位置**: `packages/core/src/services/loopDetectionService.ts`

用于检测 Agent 是否陷入无效循环。

```markdown
You are a sophisticated AI diagnostic agent specializing in identifying 
when a conversational AI is stuck in an unproductive state.

An unproductive state is characterized by:

1. **Repetitive Actions:** 
   重复相同的工具调用或响应
   包括简单循环 (A, A, A) 和交替模式 (A, B, A, B)

2. **Cognitive Loop:** 
   无法确定下一步
   重复询问相同问题
   生成不合逻辑的响应

**关键区分：**
区分真正的无效状态和合法的渐进进展。
例如：对同一文件进行小的、不同的修改（如逐个添加文档注释）
是正常进展，不是循环。
```

#### 检测输出结构

```json
{
  "unproductive_state_analysis": "分析推理过程...",
  "unproductive_state_confidence": 0.95  // 0.0-1.0
}
```

### 5.5 代码纠错提示 (Code Correction Prompt)

**文件位置**: `packages/core/src/utils/editCorrector.ts`

用于修复失败的代码编辑。

```markdown
You are an expert code-editing assistant. Your task is to analyze a 
failed edit attempt and provide a corrected version of the text snippets.

The correction should be as minimal as possible, staying very close 
to the original.

Focus ONLY on fixing issues like:
- whitespace
- indentation  
- line endings
- incorrect escaping

Do NOT invent a completely new edit. Your job is to fix the provided 
parameters to make the edit succeed.

Return ONLY the corrected snippet in the specified JSON format.
```

### 5.6 Prompt 设计模式总结

| 模式 | 说明 | 示例 |
|------|------|------|
| **身份定义** | 开头明确 Agent 身份和目标 | "You are a CLI agent..." |
| **粗体强调** | 使用 `**关键词**` 突出重点 | `**Conventions:**` |
| **规则列表** | 使用 Markdown 列表组织规则 | `- Rule 1\n- Rule 2` |
| **工作流定义** | 编号步骤定义流程 | `1. Understand\n2. Plan` |
| **示例驱动** | 提供具体示例说明 | `<example>...</example>` |
| **XML 结构** | 使用 XML 标签组织输出 | `<scratchpad>...</scratchpad>` |
| **JSON Schema** | 定义结构化输出格式 | `{ "type": "object", ... }` |
| **负面指令** | 明确禁止的行为 | "Do NOT..." |
| **条件分支** | 根据场景选择不同行为 | "For simple tasks... For complex tasks..." |

### 5.7 对客服 Agent 的 Prompt 设计建议

#### 5.7.1 主系统提示模板

```markdown
# Identity
You are a professional customer service agent for [公司名称], 
specializing in [业务领域]. Your goal is to help customers 
resolve issues efficiently while ensuring satisfaction.

# Core Mandates
- **Politeness:** 始终保持礼貌专业
- **Accuracy:** 只提供准确信息
- **Empathy:** 理解并安抚客户情绪
- **Privacy:** 保护客户隐私
- **Compliance:** 遵守公司政策

# Workflow
1. **Greet:** 礼貌问候，确认身份
2. **Understand:** 理解问题，识别意图
3. **Search:** 查询知识库和客户信息
4. **Respond:** 提供解决方案
5. **Confirm:** 确认问题解决
6. **Close:** 礼貌结束，必要时创建工单

# Tone
- 简洁、清晰、专业
- 避免技术术语
- 适当使用表情符号（如果品牌允许）

# Escalation Rules
- 客户情绪激动时：安抚 → 转人工
- 无法解决时：创建工单 → 告知跟进时间
- 敏感问题：立即转人工
```

#### 5.7.2 知识库检索子代理提示

```markdown
You are **Knowledge Base Investigator**, a specialized agent for 
deep knowledge retrieval.

Your task is to find the most relevant information to answer 
customer questions.

## Rules
1. Search multiple knowledge bases in parallel
2. Rank results by relevance
3. Extract key points, not full documents
4. Cite sources for traceability

## Output Format
{
  "answer_summary": "简洁的答案摘要",
  "key_points": ["要点1", "要点2"],
  "sources": [{"title": "文档标题", "url": "链接"}],
  "confidence": 0.95
}
```

## 六、Agent 类型定义

**文件位置**: `packages/core/src/agents/types.ts`

```typescript
export interface AgentDefinition<TOutput> {
  name: string;
  description: string;
  promptConfig: PromptConfig;      // 提示配置
  modelConfig: ModelConfig;        // 模型配置
  runConfig: RunConfig;            // 运行配置
  toolConfig?: ToolConfig;         // 工具配置
  outputConfig?: OutputConfig<TOutput>;  // 输出配置
  inputConfig: InputConfig;        // 输入配置
}

export enum AgentTerminateMode {
  ERROR = 'ERROR',
  TIMEOUT = 'TIMEOUT',
  GOAL = 'GOAL',
  MAX_TURNS = 'MAX_TURNS',
  ABORTED = 'ABORTED',
  ERROR_NO_COMPLETE_TASK_CALL = 'ERROR_NO_COMPLETE_TASK_CALL',
}
```

## 七、数据流图

```
用户输入 
    ↓
AppContainer (CLI UI)
    ↓
GeminiClient.sendMessageStream()
    ↓
[BeforeAgent Hook] → Turn.run() → [AfterAgent Hook]
    ↓
GeminiChat.sendMessageStream()
    ↓
[BeforeModel Hook] → API Call → [AfterModel Hook]
    ↓
Tool Call Request
    ↓
CoreToolScheduler.schedule()
    ↓
[BeforeTool Hook] → Tool.execute() → [AfterTool Hook]
    ↓
Tool Response → 返回模型 → 循环
```

## 八、关键文件路径汇总

| 组件 | 文件路径 |
|------|----------|
| Agent 执行器 | `packages/core/src/agents/executor.ts` |
| Agent 类型定义 | `packages/core/src/agents/types.ts` |
| Turn 管理 | `packages/core/src/core/turn.ts` |
| Gemini 客户端 | `packages/core/src/core/client.ts` |
| Gemini Chat | `packages/core/src/core/geminiChat.ts` |
| 工具调度器 | `packages/core/src/core/coreToolScheduler.ts` |
| 循环检测 | `packages/core/src/services/loopDetectionService.ts` |
| Hooks 系统 | `packages/core/src/hooks/hookEventHandler.ts` |
| Hook 类型 | `packages/core/src/hooks/types.ts` |
| UI 容器 | `packages/cli/src/ui/AppContainer.tsx` |
| 系统提示 | `packages/core/src/core/prompts.ts` |
| 工具注册 | `packages/core/src/tools/tool-registry.ts` |

## 九、对 AI 客服 Agent 的参考价值

### 9.1 可借鉴的设计模式

#### 1. 主循环 + 状态机模式

```typescript
while (true) {
  // 检查终止条件
  // 执行一轮对话
  // 检查结果
  // 准备下一轮
}
```

**客服场景应用：** 用户问题 → 理解意图 → 查询知识库 → 生成回答 → 确认满意度

#### 2. Hooks 系统 - 高度可扩展

```typescript
BeforeAgent → AfterAgent
BeforeTool → AfterTool
BeforeModel → AfterModel
```

**客服场景应用：** 日志记录、敏感词过滤、满意度追踪、数据统计

#### 3. 循环检测机制

- 工具调用重复检测
- 内容重复检测
- LLM 辅助检测（30轮后启用）

**客服场景应用：** 防止 agent 重复回答相同问题或陷入无效循环

#### 4. 恢复机制

```typescript
executeFinalWarningTurn() // 给 agent 最后一次机会完成任务
```

**客服场景应用：** 无法解决问题时优雅转人工

#### 5. 工具调度器状态机

```
Validating → Scheduled → Executing → Success/Error/Cancelled
                ↓
             Waiting (需要用户确认)
```

**客服场景应用：** 管理知识库查询、工单创建等操作的生命周期

### 9.2 需要调整的部分

#### 1. 工具集替换

gemini-cli 面向代码开发，客服需要替换为：

| 原工具 | 客服工具 |
|--------|----------|
| shell | KnowledgeBaseSearch (知识库检索) |
| edit | TicketCreate (创建工单) |
| read-file | UserInfoQuery (用户信息查询) |
| grep/glob | TransferToHuman (转人工) |
| web-fetch | SentimentAnalysis (情绪分析) |

#### 2. 系统提示重写

需要重写为客服场景：

- 礼貌、专业的语气
- 问题分类能力
- 多轮对话追踪
- 情绪识别与安抚

#### 3. 终止条件调整

客服场景特有的终止条件：

| 条件 | 说明 |
|------|------|
| 用户满意度确认 | 用户确认问题已解决 |
| 问题解决标记 | agent 判断问题已解决 |
| 转人工触发 | 无法解决时转人工 |
| 用户主动结束 | 用户说"谢谢"等结束语 |

### 9.3 建议的客服 Agent 架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    CustomerServiceAgent                          │
├─────────────────────────────────────────────────────────────────┤
│  1. UNDERSTAND: 意图识别 + 情绪分析                              │
│  2. PLAN: 选择处理策略（自助/知识库/转人工）                      │
│  3. ACTION: 执行工具调用（查询/回答/创建工单）                    │
│  4. CHECK: 验证回答质量 + 用户满意度                             │
│  5. RECOVERY: 无法解决时转人工                                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  工具集:                                                         │
│  - KnowledgeBaseSearch (知识库检索)                              │
│  - UserInfoQuery (用户信息查询)                                  │
│  - TicketCreate (创建工单)                                       │
│  - TransferToHuman (转人工)                                      │
│  - SentimentAnalysis (情绪分析)                                  │
│  - FAQMatch (FAQ 匹配)                                           │
│  - OrderQuery (订单查询)                                         │
└─────────────────────────────────────────────────────────────────┘
```

### 9.4 参考价值评估

| 方面 | 参考价值 | 说明 |
|------|----------|------|
| 主循环设计 | ⭐⭐⭐⭐⭐ | 直接可用，设计清晰 |
| Hooks 系统 | ⭐⭐⭐⭐⭐ | 非常适合扩展，可用于日志、过滤等 |
| 工具调度器 | ⭐⭐⭐⭐ | 需要简化，但状态机设计可借鉴 |
| 循环检测 | ⭐⭐⭐⭐ | 客服场景也需要，可直接复用 |
| 恢复机制 | ⭐⭐⭐⭐⭐ | 转人工的基础，非常重要 |
| 系统提示 | ⭐⭐ | 需要完全重写为客服场景 |
| 工具集 | ⭐ | 需要完全替换为客服工具 |

## 十、实施建议

1. **Fork 项目**：保留核心架构，替换业务逻辑

2. **保留的核心组件**：
   - `AgentExecutor` - 主循环
   - `Turn` - 对话管理
   - `Hooks` - 扩展系统
   - `LoopDetectionService` - 循环检测

3. **需要重写的组件**：
   - 工具集 - 替换为客服工具
   - 系统提示 - 重写为客服场景
   - 终止条件 - 添加客服特有条件

4. **新增组件**：
   - 意图识别模块
   - 情绪分析模块
   - 满意度追踪模块
   - 转人工调度模块

## 十一、总结

Gemini-CLI 的架构设计体现了清晰的关注点分离，通过 hooks 系统提供了高度的可扩展性，同时通过循环检测和恢复机制确保了系统的健壮性。

对于构建 AI 客服 agent，其**核心架构（主循环、Hooks、工具调度器）具有很高的参考价值**，可以直接复用。但需要完全替换工具集和重写系统提示以适应客服场景。

建议采用渐进式迁移策略：先复用核心架构，再逐步替换和扩展业务组件。

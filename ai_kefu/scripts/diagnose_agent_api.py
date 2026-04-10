#!/usr/bin/env python3
"""
Agent API 端到端诊断脚本

逐层测试 Agent API 调用链，精确定位 "Agent API Error" 的根因。

测试层级:
  1. 基础设施检查 — Agent API 服务是否存活
  2. /chat/ 端点直接调用 — 模拟 http_client.py 的请求
  3. AgentExecutor.run() 直接调用 — 跳过 HTTP 层
  4. execute_turn() 单轮调用 — 跳过 executor 循环
  5. Qwen LLM 直接调用 — 跳过整个 Agent 框架

用法:
  cd ai_kefu && python scripts/diagnose_agent_api.py
"""

import sys
import time
import traceback
from pathlib import Path

# 添加项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# ============================================================
# 颜色输出
# ============================================================
class C:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    END = "\033[0m"

def ok(msg):
    print(f"  {C.GREEN}✅ {msg}{C.END}")

def fail(msg):
    print(f"  {C.RED}❌ {msg}{C.END}")

def warn(msg):
    print(f"  {C.YELLOW}⚠️  {msg}{C.END}")

def info(msg):
    print(f"  {C.BLUE}ℹ️  {msg}{C.END}")

def header(msg):
    print(f"\n{C.BOLD}{'='*60}{C.END}")
    print(f"{C.BOLD} {msg}{C.END}")
    print(f"{C.BOLD}{'='*60}{C.END}")


# ============================================================
# 测试查询（模拟真实用户消息）
# ============================================================
TEST_QUERY = "你好，我想租一个相机"
TEST_SESSION_ID = "diag-test-session-001"
TEST_USER_ID = "diag-user-001"
AGENT_SERVICE_URL = "http://localhost:8000"


def test_1_health_check():
    """测试 1: Agent API 健康检查"""
    header("测试 1: Agent API 服务健康检查")
    
    import httpx
    
    # 1a. /health 端点
    try:
        resp = httpx.get(f"{AGENT_SERVICE_URL}/health", timeout=5)
        if resp.status_code == 200:
            ok(f"/health → {resp.status_code}: {resp.json()}")
        else:
            fail(f"/health → HTTP {resp.status_code}: {resp.text[:200]}")
            return False
    except httpx.ConnectError as e:
        fail(f"无法连接到 {AGENT_SERVICE_URL}: {e}")
        info("请确认 Agent API 已启动: make run-api 或 uvicorn ai_kefu.api.main:app")
        return False
    except Exception as e:
        fail(f"/health 请求失败: {e}")
        return False
    
    # 1b. / 根端点
    try:
        resp = httpx.get(f"{AGENT_SERVICE_URL}/", timeout=5)
        ok(f"/ → {resp.status_code}: {resp.json()}")
    except Exception as e:
        warn(f"/ 端点异常: {e}")
    
    return True


def test_2_chat_http():
    """测试 2: 通过 HTTP 直接调用 /chat/ 端点"""
    header("测试 2: HTTP 直接调用 /chat/ 端点")
    
    import httpx
    
    payload = {
        "query": TEST_QUERY,
        "session_id": TEST_SESSION_ID,
        "user_id": TEST_USER_ID,
        "context": {}
    }
    
    info(f"请求: POST /chat/ with query='{TEST_QUERY}'")
    
    try:
        start = time.time()
        resp = httpx.post(
            f"{AGENT_SERVICE_URL}/chat/",
            json=payload,
            timeout=120
        )
        elapsed = time.time() - start
        
        if resp.status_code == 200:
            data = resp.json()
            response_text = data.get("response", "")[:100]
            status = data.get("status", "")
            metadata = data.get("metadata", {})
            error = metadata.get("error", "")
            
            if error:
                warn(f"HTTP 200 但 Agent 内部错误: {error}")
                info(f"response={response_text}")
            else:
                ok(f"HTTP 200, status={status}, 耗时={elapsed:.1f}s")
                ok(f"response: {response_text}...")
            return True
        else:
            fail(f"HTTP {resp.status_code}: {resp.text[:500]}")
            info(f"耗时: {elapsed:.1f}s")
            
            # 分析常见错误
            if resp.status_code == 500:
                info("500 错误通常意味着 Agent 内部异常（LLM 调用失败、Redis 连接问题等）")
                info("请查看 Agent API 的控制台日志获取详细堆栈信息")
            elif resp.status_code == 422:
                info("422 表示请求参数校验失败")
            
            return False
            
    except httpx.ReadTimeout:
        fail(f"请求超时 (>120s)")
        info("Agent 执行时间过长，可能是 LLM 响应慢或死循环")
        return False
    except httpx.ConnectError as e:
        fail(f"连接失败: {e}")
        return False
    except Exception as e:
        fail(f"请求异常: {e}")
        traceback.print_exc()
        return False


def test_3_executor_direct():
    """测试 3: 直接调用 AgentExecutor.run()（跳过 HTTP 层）"""
    header("测试 3: 直接调用 AgentExecutor.run()")
    
    try:
        from ai_kefu.storage.session_store import SessionStore
        from ai_kefu.config.settings import settings
        info(f"Redis URL: {settings.redis_url}")
    except Exception as e:
        fail(f"导入配置失败: {e}")
        traceback.print_exc()
        return False
    
    # 3a. Redis 连接
    try:
        session_store = SessionStore(
            redis_url=settings.redis_url,
            ttl=settings.redis_session_ttl
        )
        ok("SessionStore (Redis) 初始化成功")
    except Exception as e:
        fail(f"Redis 连接失败: {e}")
        info(f"Redis URL: {settings.redis_url}")
        info("请确认 Redis 已启动: redis-server 或 brew services start redis")
        return False
    
    # 3b. ConversationStore
    conversation_store = None
    try:
        from ai_kefu.xianyu_interceptor.conversation_store import ConversationStore
        conversation_store = ConversationStore(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_database
        )
        ok("ConversationStore (MySQL) 初始化成功")
    except Exception as e:
        warn(f"MySQL 连接失败（非致命）: {e}")
    
    # 3c. AgentExecutor
    try:
        from ai_kefu.agent.executor import AgentExecutor
        executor = AgentExecutor(
            session_store=session_store,
            conversation_store=conversation_store
        )
        ok(f"AgentExecutor 初始化成功, tools={len(executor.tools_registry.get_all_tools())}")
    except Exception as e:
        fail(f"AgentExecutor 初始化失败: {e}")
        traceback.print_exc()
        return False
    
    # 3d. 执行 run()
    info(f"执行 executor.run(query='{TEST_QUERY}') ...")
    try:
        start = time.time()
        result = executor.run(
            query=TEST_QUERY,
            session_id=f"diag-{int(time.time())}",
            user_id=TEST_USER_ID,
            context={}
        )
        elapsed = time.time() - start
        
        if "error" in result:
            fail(f"Agent 返回错误: {result['error']}")
            info(f"status={result.get('status')}, session_id={result.get('session_id')}")
            info(f"response={result.get('response', '')[:200]}")
            info(f"耗时: {elapsed:.1f}s")
            return False
        else:
            response_text = result.get("response", "")[:150]
            ok(f"Agent 执行成功! 耗时={elapsed:.1f}s, turns={result.get('turn_counter', 0)}")
            ok(f"response: {response_text}...")
            return True
            
    except Exception as e:
        fail(f"executor.run() 异常: {type(e).__name__}: {e}")
        traceback.print_exc()
        return False


def test_4_single_turn():
    """测试 4: 单轮 execute_turn()（跳过 Executor 循环）"""
    header("测试 4: 单轮 execute_turn()")
    
    try:
        from ai_kefu.agent.turn import execute_turn
        from ai_kefu.models.session import Session
        from ai_kefu.tools.tool_registry import ToolRegistry
        from ai_kefu.tools import knowledge_search, complete_task
        
        # 创建最小化 session
        session = Session(
            session_id=f"diag-turn-{int(time.time())}",
            user_id=TEST_USER_ID,
            messages=[]
        )
        
        # 注册工具
        registry = ToolRegistry()
        registry.register_tool(
            "knowledge_search",
            knowledge_search.knowledge_search,
            knowledge_search.get_tool_definition()
        )
        registry.register_tool(
            "complete_task",
            complete_task.complete_task,
            complete_task.get_tool_definition()
        )
        
        info(f"执行 execute_turn(query='{TEST_QUERY}') ...")
        start = time.time()
        
        result = execute_turn(
            session=session,
            user_message=TEST_QUERY,
            tools_registry=registry,
            is_tool_continue=False
        )
        elapsed = time.time() - start
        
        if result.success:
            ok(f"execute_turn 成功! 耗时={elapsed:.1f}s")
            ok(f"response: {(result.response_text or '')[:150]}...")
            if result.tool_calls:
                info(f"tool_calls: {[tc.get('name') for tc in result.tool_calls]}")
        else:
            fail(f"execute_turn 失败: {result.error_message}")
            info(f"耗时: {elapsed:.1f}s")
        
        return result.success
        
    except Exception as e:
        fail(f"execute_turn 异常: {type(e).__name__}: {e}")
        traceback.print_exc()
        return False


def test_5_llm_direct():
    """测试 5: 直接调用 Qwen LLM（跳过整个 Agent 框架）"""
    header("测试 5: 直接调用 Qwen LLM")
    
    try:
        from ai_kefu.config.settings import settings
        info(f"Model: {settings.model_name}")
        info(f"Base URL: {settings.model_base_url}")
        info(f"API Key: {settings.api_key[:8]}...{settings.api_key[-4:]}")
    except Exception as e:
        fail(f"加载配置失败: {e}")
        return False
    
    try:
        from openai import OpenAI
        
        client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.model_base_url,
        )
        
        info("发送测试请求到 Qwen API ...")
        start = time.time()
        
        response = client.chat.completions.create(
            model=settings.model_name,
            messages=[
                {"role": "system", "content": "你是一个客服助手。请简短回复。"},
                {"role": "user", "content": TEST_QUERY}
            ],
            max_tokens=100,
            timeout=30
        )
        elapsed = time.time() - start
        
        content = response.choices[0].message.content
        ok(f"Qwen API 调用成功! 耗时={elapsed:.1f}s")
        ok(f"response: {content[:150]}")
        info(f"model={response.model}, tokens={response.usage.total_tokens if response.usage else 'N/A'}")
        return True
        
    except Exception as e:
        fail(f"Qwen API 调用失败: {type(e).__name__}: {e}")
        traceback.print_exc()
        return False


def test_6_redis_check():
    """测试 6: Redis 连接检查"""
    header("测试 6: Redis 连接检查")
    
    try:
        from ai_kefu.config.settings import settings
        info(f"Redis URL: {settings.redis_url}")
    except Exception as e:
        fail(f"加载配置失败: {e}")
        return False
    
    try:
        import redis
        r = redis.from_url(settings.redis_url)
        pong = r.ping()
        if pong:
            ok("Redis PING → PONG")
            info(f"Redis info: {r.info('server').get('redis_version', 'N/A')}")
            return True
        else:
            fail("Redis PING 失败")
            return False
    except Exception as e:
        fail(f"Redis 连接失败: {e}")
        info("请确认 Redis 已启动: redis-server 或 brew services start redis")
        return False


def test_7_knowledge_store():
    """测试 7: 知识库检查"""
    header("测试 7: 知识库 (Chroma) 检查")
    
    try:
        from ai_kefu.storage.knowledge_store import KnowledgeStore
        from ai_kefu.config.settings import settings
        
        store = KnowledgeStore(persist_path=settings.chroma_persist_path)
        ok(f"KnowledgeStore 初始化成功")
        
        # 尝试搜索
        results = store.search("租赁相机", top_k=3)
        if results:
            ok(f"知识库搜索成功, 返回 {len(results)} 条结果")
            for r in results[:2]:
                content = r.get("content", r.get("text", ""))[:80]
                info(f"  - {content}...")
        else:
            warn("知识库为空或搜索无结果")
        
        return True
        
    except Exception as e:
        fail(f"知识库检查失败: {e}")
        traceback.print_exc()
        return False


# ============================================================
# 主程序
# ============================================================
def main():
    print(f"\n{C.BOLD}🔍 Agent API 端到端诊断{C.END}")
    print(f"测试查询: '{TEST_QUERY}'")
    print(f"Agent URL: {AGENT_SERVICE_URL}")
    
    results = {}
    
    # 从底层到顶层依次测试
    # 先测底层依赖（LLM、Redis、知识库），再测上层（Executor、HTTP）
    
    # 底层依赖
    results["5_llm"] = test_5_llm_direct()
    results["6_redis"] = test_6_redis_check()
    results["7_knowledge"] = test_7_knowledge_store()
    
    # 中间层
    results["4_single_turn"] = test_4_single_turn()
    results["3_executor"] = test_3_executor_direct()
    
    # 上层
    results["1_health"] = test_1_health_check()
    if results["1_health"]:
        results["2_chat_http"] = test_2_chat_http()
    else:
        results["2_chat_http"] = None
        warn("跳过 HTTP 调用测试（API 服务未运行）")
    
    # ============================================================
    # 诊断总结
    # ============================================================
    header("📊 诊断总结")
    
    all_passed = True
    for name, passed in results.items():
        label = name.replace("_", " ").upper()
        if passed is True:
            print(f"  {C.GREEN}✅ {label}{C.END}")
        elif passed is False:
            print(f"  {C.RED}❌ {label}{C.END}")
            all_passed = False
        else:
            print(f"  {C.YELLOW}⏭️  {label} (跳过){C.END}")
    
    # 故障分析
    if all_passed:
        print(f"\n  {C.GREEN}{C.BOLD}所有测试通过！Agent API 工作正常。{C.END}")
        print(f"  如果生产环境仍有错误，可能是间歇性问题（网络抖动、LLM 限流等）。")
    else:
        print(f"\n  {C.RED}{C.BOLD}发现问题！故障分析:{C.END}")
        
        if not results.get("5_llm"):
            print(f"  {C.RED}→ Qwen LLM 调用失败：检查 API_KEY 和网络连接{C.END}")
        
        if not results.get("6_redis"):
            print(f"  {C.RED}→ Redis 连接失败：Session 无法存储，Agent 无法工作{C.END}")
            print(f"    修复：brew services start redis 或 docker run -d -p 6379:6379 redis{C.END}")
        
        if results.get("5_llm") and results.get("6_redis") and not results.get("4_single_turn"):
            print(f"  {C.RED}→ execute_turn 失败但 LLM 正常：可能是 prompt 构建或工具注册问题{C.END}")
        
        if results.get("4_single_turn") and not results.get("3_executor"):
            print(f"  {C.RED}→ Executor 失败但单轮正常：可能是多轮循环、超时或 session 问题{C.END}")
        
        if results.get("3_executor") and not results.get("2_chat_http"):
            print(f"  {C.RED}→ HTTP 调用失败但 Executor 正常：检查 FastAPI 路由或中间件{C.END}")
        
        if not results.get("1_health"):
            print(f"  {C.YELLOW}→ Agent API 服务未运行：interceptor 调用时会得到连接错误{C.END}")
            print(f"    这会导致 'Agent API call failed:' 后面为空（ConnectError）{C.END}")


if __name__ == "__main__":
    main()

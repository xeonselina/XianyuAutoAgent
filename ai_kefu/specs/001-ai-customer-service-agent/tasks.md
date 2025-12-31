# Tasks: AI 客服 Agent (内网 HTTP 服务)

**Input**: Design documents from `/specs/001-ai-customer-service-agent/`
**Prerequisites**: plan.md, data-model.md, contracts/openapi.yaml, quickstart.md, research.md

**Tests**: Tasks include comprehensive unit and integration tests as specified in the宪法 (testing requirements)

**Organization**: Tasks are grouped by functional capability to enable incremental delivery

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story/capability this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

Based on plan.md project structure:
- **Application code**: `ai_kefu/`
- **Tests**: `tests/`
- **Root files**: `Dockerfile`, `Makefile`, `requirements.txt`, etc.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and Docker/build automation setup

- [X] T001 Create root project structure (Dockerfile, Makefile, docker-compose.yml, .dockerignore, requirements.txt, .env.example)
- [X] T002 [P] Create ai_kefu/ package structure (agent/, tools/, hooks/, services/, api/, prompts/, config/)
- [X] T003 [P] Create tests/ structure (unit/, integration/, fixtures/)
- [X] T004 Implement Dockerfile with multi-stage build for Python 3.11-slim
- [X] T005 Implement Makefile with targets (install, dev, test, lint, docker-build, docker-run, clean, help)
- [X] T006 Create docker-compose.yml for local development (Redis + ai-kefu service)
- [X] T007 Create requirements.txt with dependencies (dashscope, fastapi, uvicorn, pydantic, chromadb, redis, tenacity, pytest, httpx)
- [X] T008 Create .env.example with configuration template (QWEN_API_KEY, REDIS_URL, CHROMA_PERSIST_PATH, etc.)
- [X] T009 Create .dockerignore to exclude tests, docs, .git, etc.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T010 Implement configuration management in ai_kefu/config/settings.py using pydantic-settings
- [X] T010 [P] Implement constants in ai_kefu/config/constants.py (MAX_TURNS, TIMEOUT, LOOP_THRESHOLD, etc.)
- [X] T010 [P] Implement data models in ai_kefu/models/session.py (Session, Message, ToolCall, HumanRequest, AgentState)
- [X] T010 [P] Implement knowledge model in ai_kefu/models/knowledge.py (KnowledgeEntry)
- [X] T010 [P] Implement API request/response models in ai_kefu/api/models.py (ChatRequest, ChatResponse, etc.)
- [X] T010 Implement Redis session store in ai_kefu/storage/session_store.py (SessionStore class with get/set/delete/ttl)
- [X] T010 [P] Implement Chroma knowledge store in ai_kefu/storage/knowledge_store.py (KnowledgeStore class with add/search/update/delete)
- [X] T010 [P] Implement Qwen API client wrapper in ai_kefu/llm/qwen_client.py (call_qwen, stream_qwen, with retry logic)
- [X] T010 [P] Implement embedding service in ai_kefu/llm/embeddings.py (generate_embedding using Qwen text-embedding-v3)
- [X] T010 Implement logging infrastructure in ai_kefu/utils/logging.py (JSONFormatter, structured logging setup)
- [X] T020 [P] Implement error handling in ai_kefu/utils/errors.py (custom exceptions: SessionNotFound, QwenAPIError, etc.)
- [X] T020 [P] Implement system prompts in ai_kefu/prompts/system_prompt.py (CUSTOMER_SERVICE_SYSTEM_PROMPT in Chinese)
- [X] T020 [P] Implement workflow prompts in ai_kefu/prompts/workflow_prompts.py (if needed for specific flows)
- [X] T020 Implement FastAPI application setup in ai_kefu/api/main.py (app instance, CORS, middleware, lifespan events)
- [X] T020 [P] Implement FastAPI dependencies in ai_kefu/api/dependencies.py (get_session_store, get_knowledge_store, get_qwen_client)
- [X] T020 Implement health check endpoint in ai_kefu/api/routes/system.py (GET /health with Redis, Chroma, Qwen API checks)

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Core Agent with Knowledge Search (Priority: P1) 🎯 MVP

**Goal**: Implement basic AI customer service agent that can chat with users, search knowledge base, and complete tasks

**Independent Test**: User can send a query via POST /chat, agent searches knowledge and returns helpful response

**Capabilities**:
- Basic chat (sync and stream)
- knowledge_search tool
- complete_task tool  
- Session management
- Plan-Action-Check loop

### Unit Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T026 [P] [US1] Unit test for ToolRegistry in tests/unit/test_tools/test_tool_registry.py
- [X] T027 [P] [US1] Unit test for knowledge_search tool in tests/unit/test_tools/test_knowledge_search.py
- [X] T028 [P] [US1] Unit test for complete_task tool in tests/unit/test_tools/test_complete_task.py
- [X] T029 [P] [US1] Unit test for Turn management in tests/unit/test_agent/test_turn.py
- [X] T030 [P] [US1] Unit test for loop detection in tests/unit/test_services/test_loop_detection.py
- [REMOVED] T031 [P] [US1] Unit test for intent service (removed - LLM handles intent implicitly)

### Integration Tests for User Story 1

- [X] T032 [P] [US1] Integration test for /chat endpoint in tests/integration/test_api/test_chat_sync.py
- [X] T033 [P] [US1] Integration test for /chat/stream endpoint in tests/integration/test_api/test_chat_stream.py
- [X] T034 [US1] End-to-end workflow test for complete conversation in tests/integration/test_workflow/test_basic_conversation.py

### Implementation for User Story 1

#### Tools Implementation

- [X] T035 [P] [US1] Implement tool registry in ai_kefu/tools/tool_registry.py (ToolRegistry class, register_tool, get_tool, to_qwen_format)
- [X] T036 [P] [US1] Implement knowledge_search tool in ai_kefu/tools/knowledge_search.py (function definition + execution logic)
- [X] T037 [P] [US1] Implement complete_task tool in ai_kefu/tools/complete_task.py (function definition + execution logic)

#### Services Implementation

- [REMOVED] T038 [P] [US1] Intent recognition service (removed - LLM with Function Calling handles intent implicitly, following Gemini CLI architecture)
- [X] T039 [P] [US1] Implement sentiment analysis service in ai_kefu/services/sentiment_service.py (analyze_sentiment from user message)
- [X] T040 [P] [US1] Implement loop detection service in ai_kefu/services/loop_detection.py (check_tool_loop function using AgentState)

#### Agent Core Implementation

- [X] T041 [P] [US1] Implement agent types in ai_kefu/agent/types.py (TurnResult, AgentConfig)
- [X] T042 [US1] Implement single turn logic in ai_kefu/agent/turn.py (execute_turn function: call Qwen, parse tool_calls, execute tools, return result)
- [X] T043 [US1] Implement agent executor in ai_kefu/agent/executor.py (AgentExecutor class with run() and stream() methods, Plan-Action-Check loop)

#### Hooks Implementation

- [X] T044 [P] [US1] Implement event handler base in ai_kefu/hooks/event_handler.py (EventHandler base class, HookRegistry)
- [X] T045 [P] [US1] Implement logging hook in ai_kefu/hooks/logging_hook.py (log all agent events: turn start/end, tool calls, completion)
- [X] T046 [P] [US1] Implement sensitive filter hook in ai_kefu/hooks/sensitive_filter.py (filter sensitive data from logs - stub for now)

#### API Implementation

- [X] T047 [P] [US1] Implement chat routes in ai_kefu/api/routes/chat.py (POST /chat, POST /chat/stream)
- [X] T048 [P] [US1] Implement session routes in ai_kefu/api/routes/session.py (GET /sessions/{id}, DELETE /sessions/{id})
- [X] T049 [US1] Register all routes in ai_kefu/api/main.py (include chat, session, system routers)

#### Documentation and Scripts

- [X] T050 [P] [US1] Create knowledge initialization script in ai_kefu/scripts/init_knowledge.py (add sample knowledge entries to Chroma)
- [X] T051 [US1] Update quickstart.md with actual commands for running User Story 1 (init knowledge, start server, test endpoints)

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently - basic chat with knowledge search works

---

## Phase 4: User Story 2 - Human-in-the-Loop (Priority: P2)

**Goal**: Implement ask_human_agent tool and Human-in-the-Loop workflow where agent can pause and request human assistance

**Independent Test**: Agent calls ask_human_agent, session goes to waiting_for_human state, human replies via API, agent continues execution

**Capabilities**:
- ask_human_agent tool
- Pending requests API for humans
- Human response submission
- Agent resume after human reply

### Unit Tests for User Story 2

- [X] T052 [P] [US2] Unit test for ask_human_agent tool in tests/unit/test_tools/test_ask_human_agent.py
- [X] T053 [P] [US2] Unit test for HumanRequest model validation in tests/unit/test_models/test_human_request.py

### Integration Tests for User Story 2

- [X] T054 [P] [US2] Integration test for Human-in-the-Loop flow in tests/integration/test_workflow/test_human_in_the_loop.py
- [X] T055 [P] [US2] Integration test for /human-agent/pending-requests endpoint in tests/integration/test_api/test_human_agent.py
- [X] T056 [US2] Integration test for /sessions/{id}/human-response endpoint in tests/integration/test_api/test_human_response.py

### Implementation for User Story 2

- [X] T057 [P] [US2] Implement ask_human_agent tool in ai_kefu/tools/ask_human_agent.py (create HumanRequest, pause agent, update session status)
- [X] T058 [P] [US2] Implement human agent routes in ai_kefu/api/routes/human_agent.py (GET /human-agent/pending-requests, GET /sessions/{id}/pending-request, POST /sessions/{id}/human-response)
- [X] T059 [US2] Update AgentExecutor in ai_kefu/agent/executor.py to handle waiting_for_human state and resume logic
- [X] T060 [US2] Update Session model persistence to properly save/load HumanRequest state
- [X] T061 [US2] Register human_agent routes in ai_kefu/api/main.py

**Checkpoint**: At this point, User Stories 1 AND 2 should both work - agent can request human help and continue after reply

---

## Phase 5: User Story 3 - Knowledge Management (Priority: P3)

**Goal**: Implement knowledge base CRUD API for administrators to manage knowledge entries

**Independent Test**: Admin can add, list, update, delete knowledge entries via /knowledge endpoints

**Capabilities**:
- Add knowledge entry
- List knowledge entries
- Search knowledge (admin test endpoint)
- Update knowledge entry
- Delete knowledge entry

### Unit Tests for User Story 3

- [X] T062 [P] [US3] Unit test for KnowledgeStore CRUD operations in tests/unit/test_storage/test_knowledge_store.py
- [X] T063 [P] [US3] Unit test for embedding generation in tests/unit/test_llm/test_embeddings.py

### Integration Tests for User Story 3

- [X] T064 [P] [US3] Integration test for POST /knowledge in tests/integration/test_api/test_knowledge_crud.py
- [X] T065 [P] [US3] Integration test for GET /knowledge in tests/integration/test_api/test_knowledge_list.py
- [X] T066 [P] [US3] Integration test for PUT /knowledge/{id} in tests/integration/test_api/test_knowledge_update.py
- [X] T067 [P] [US3] Integration test for DELETE /knowledge/{id} in tests/integration/test_api/test_knowledge_delete.py
- [X] T068 [US3] Integration test for POST /knowledge/search in tests/integration/test_api/test_knowledge_search.py

### Implementation for User Story 3

- [X] T069 [P] [US3] Implement knowledge routes in ai_kefu/api/routes/knowledge.py (POST /knowledge, GET /knowledge, POST /knowledge/search, PUT /knowledge/{id}, DELETE /knowledge/{id})
- [X] T070 [US3] Register knowledge routes in ai_kefu/api/main.py
- [X] T071 [US3] Update quickstart.md with knowledge management examples

**Checkpoint**: All user stories should now be independently functional - complete AI customer service system

---

## Phase 6: Docker and Deployment

**Purpose**: Ensure cross-platform deployment readiness (ARM Mac dev → Linux production)

- [X] T072 [P] Test Dockerfile build on ARM Mac (docker build -t ai-kefu-agent .)
- [X] T073 [P] Test docker-compose up on ARM Mac with Redis integration
- [X] T074 [P] Validate Makefile targets work correctly (make install, make dev, make test, make docker-build, make docker-run)
- [X] T075 Test container startup with health check (verify /health endpoint responds)
- [X] T076 [P] Create deployment documentation in docs/deployment.md (Docker commands, environment variables, production recommendations)
- [X] T077 Test Chroma persistence across container restarts (verify data survives)

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [X] T078 [P] Add comprehensive logging to all agent turns and tool executions
- [X] T079 [P] Implement rate limiting for Qwen API calls (respect 10 QPS free tier limit)
- [X] T080 [P] Add performance metrics collection (duration_ms for tool calls, turn latency)
- [X] T081 [P] Improve error messages and user-facing error handling
- [X] T082 Add comprehensive docstrings to all public functions and classes
- [X] T083 [P] Run linting (ruff or flake8) and fix all issues
- [X] T084 [P] Run type checking (mypy) and fix all type issues
- [X] T085 Verify quickstart.md instructions work end-to-end on fresh environment
- [X] T086 [P] Add README.md at repository root with project overview and quick start link
- [X] T087 Performance optimization: tune Qwen temperature/top_p based on testing
- [X] T088 Security: validate no API keys logged, implement request size limits
- [X] T089 [P] Create sample .env file with placeholder values
- [X] T090 Final integration test: run complete customer service conversation with all features

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-5)**: All depend on Foundational phase completion
  - User Story 1 (Core Agent) can start after Phase 2
  - User Story 2 (Human-in-the-Loop) can start after Phase 2 (but may integrate with US1)
  - User Story 3 (Knowledge Management) can start after Phase 2 (independent of US1/US2)
- **Docker & Deployment (Phase 6)**: Can start after US1 complete (MVP deployable)
- **Polish (Phase 7)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) - No dependencies on other stories
- **User Story 2 (P2)**: Can start after Foundational (Phase 2) - Uses AgentExecutor from US1 but can be implemented independently
- **User Story 3 (P3)**: Can start after Foundational (Phase 2) - Completely independent (just CRUD for knowledge base)

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Tools before agent executor
- Services can be parallel with tools
- Agent executor depends on tools and services
- API routes depend on agent executor
- Integration tests run after all implementation complete

### Parallel Opportunities

- **Phase 1**: T002, T003 can run in parallel (different directories)
- **Phase 2**: Most tasks marked [P] can run in parallel (different files: models, storage, llm, prompts, utils)
- **Phase 3**: All unit tests (T026-T031) can run in parallel, integration tests (T032-T033) can run in parallel
- **Within US1 Implementation**: T035-T037 (tools), T038-T040 (services), T041 (types), T044-T046 (hooks) can all run in parallel
- **User Stories 1-3**: Once Phase 2 complete, all three stories can be developed in parallel by different team members
- **Phase 6**: T072-T074, T076 can run in parallel
- **Phase 7**: Most tasks marked [P] can run in parallel

---

## Parallel Example: User Story 1 Tools

```bash
# Launch all tool implementations for User Story 1 together:
Task T035: "Implement tool registry in ai_kefu/tools/tool_registry.py"
Task T036: "Implement knowledge_search tool in ai_kefu/tools/knowledge_search.py"
Task T037: "Implement complete_task tool in ai_kefu/tools/complete_task.py"
```

## Parallel Example: User Story 1 Services

```bash
# Launch all service implementations for User Story 1 together:
Task T039: "Implement sentiment analysis service in ai_kefu/services/sentiment_service.py"
Task T040: "Implement loop detection service in ai_kefu/services/loop_detection.py"
# Note: T038 (intent service) was removed - LLM handles intent implicitly
```

## Parallel Example: Cross-Story Development

```bash
# After Phase 2 complete, launch all user stories in parallel:
Task: "User Story 1 - Core Agent Implementation" (Developer A)
Task: "User Story 2 - Human-in-the-Loop" (Developer B)  
Task: "User Story 3 - Knowledge Management" (Developer C)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001-T009)
2. Complete Phase 2: Foundational (T010-T025) - CRITICAL - blocks all stories
3. Complete Phase 3: User Story 1 (T026-T051)
4. **STOP and VALIDATE**: Test User Story 1 independently
   - Can agent chat with users?
   - Does knowledge_search work?
   - Can agent call complete_task?
   - Do logs show all events?
5. Complete Phase 6: Docker & Deployment (T072-T077)
6. Deploy/demo MVP

**MVP Scope**: ~51 tasks (T001-T051) + ~6 deployment tasks = 57 tasks total

### Incremental Delivery

1. **Foundation** (T001-T025): Setup + Foundational → Infrastructure ready
2. **MVP** (T026-T051): Add US1 → Test independently → Deploy (Basic AI customer service!)
3. **Human Loop** (T052-T061): Add US2 → Test independently → Deploy (Human assistance feature!)
4. **Knowledge Admin** (T062-T071): Add US3 → Test independently → Deploy (Full admin capabilities!)
5. **Production Ready** (T072-T090): Docker + Polish → Production deployment

Each increment adds value without breaking previous capabilities.

### Parallel Team Strategy

With 3 developers:

1. **Together**: Complete Setup (Phase 1) + Foundational (Phase 2)
2. **Once Phase 2 done**:
   - **Developer A**: User Story 1 (T026-T051) - Core agent
   - **Developer B**: User Story 2 (T052-T061) - Human-in-the-Loop  
   - **Developer C**: User Story 3 (T062-T071) - Knowledge management
3. **Integration**: Developers test their stories independently, then integrate
4. **Together**: Docker & deployment (Phase 6), Polish (Phase 7)

Stories complete and integrate independently while maximizing parallelism.

---

## Notes

- **[P] tasks**: Different files, no dependencies, safe to parallelize
- **[Story] label**: Maps task to specific user story for traceability
- **Test-first**: Verify tests fail before implementing (TDD approach per宪法)
- **Qwen not Gemini**: All references should use Alibaba Qwen (dashscope SDK), not Google Gemini
- **Docker required**: Production deployment must use Docker per plan.md
- **Makefile targets**: Simplify common operations (install, dev, test, docker-build, etc.)
- **Chinese optimized**: System prompts should be in Chinese for optimal Qwen performance
- **Cross-platform**: Develop on ARM Mac, deploy to Linux via Docker
- **Commit frequently**: After each task or logical group
- **Independent validation**: Stop at any checkpoint to validate story works standalone
- **API-first**: All functionality exposed via RESTful API per宪法

---

## Task Count Summary

- **Phase 1 (Setup)**: 9 tasks
- **Phase 2 (Foundational)**: 16 tasks (CRITICAL PATH)
- **Phase 3 (US1 - Core Agent)**: 26 tasks (6 unit tests + 3 integration tests + 17 implementation)
- **Phase 4 (US2 - Human Loop)**: 10 tasks (2 unit tests + 3 integration tests + 5 implementation)
- **Phase 5 (US3 - Knowledge CRUD)**: 10 tasks (2 unit tests + 5 integration tests + 3 implementation)
- **Phase 6 (Docker & Deployment)**: 6 tasks
- **Phase 7 (Polish)**: 13 tasks

**Total**: 90 tasks

**MVP Scope (US1 + Infrastructure)**: 51 tasks (Phases 1-3)
**Production Ready**: All 90 tasks

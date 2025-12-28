# Tasks: 闲鱼消息拦截器与 AI Agent HTTP 集成

**Input**: Design documents from `/specs/002-xianyu-agent-http-integration/`
**Prerequisites**: spec.md, plan.md, data-model.md, research.md, quickstart.md

**Organization**: Tasks are grouped by user story to enable independent implementation and testing

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

Based on plan.md project structure:
- **Interceptor code**: `ai_kefu/xianyu_interceptor/`
- **Main entry**: `ai_kefu/main.py`
- **Legacy code**: `ai_kefu/legacy/`
- **Tests**: `tests/interceptor/`

---

## Phase 1: Setup (Project Restructuring)

**Purpose**: Reorganize codebase to separate concerns and prepare for HTTP integration

- [X] T001 Create `ai_kefu/xianyu_interceptor/` directory structure with __init__.py
- [X] T002 [P] Create `ai_kefu/legacy/` directory for archived code
- [X] T003 [P] Move `browser_controller.py` to `ai_kefu/xianyu_interceptor/browser_controller.py`
- [X] T004 [P] Move `cdp_interceptor.py` to `ai_kefu/xianyu_interceptor/cdp_interceptor.py`
- [X] T005 [P] Move `messaging_core.py` to `ai_kefu/xianyu_interceptor/messaging_core.py`
- [X] T006 [P] Archive `XianyuAgent.py` to `ai_kefu/legacy/XianyuAgent.py`
- [X] T007 [P] Archive `XianyuApis.py` to `ai_kefu/legacy/XianyuApis.py` (if exists)
- [X] T008 [P] Archive old `context_manager.py` to `ai_kefu/legacy/context_manager.py` (if not needed)
- [X] T009 Update `requirements.txt` to add `httpx>=0.25.0` for HTTP client
- [X] T010 Create `.env.example` with AGENT_SERVICE_URL and other config variables
- [X] T011 Update `.gitignore` to include `ai_kefu/legacy/` and other patterns

---

## Phase 2: Foundational (Core Infrastructure)

**Purpose**: Implement core modules that ALL user stories depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T012 Implement configuration management in `ai_kefu/xianyu_interceptor/config.py` using pydantic-settings
- [X] T013 [P] Implement data models in `ai_kefu/xianyu_interceptor/models.py` (SessionMapping, XianyuMessage, AgentChatRequest, AgentChatResponse)
- [X] T014 [P] Implement message converter in `ai_kefu/xianyu_interceptor/message_converter.py` (convert_xianyu_to_agent, convert_agent_to_xianyu)
- [X] T015 Implement session mapper base class in `ai_kefu/xianyu_interceptor/session_mapper.py` (SessionMapper abstract class)
- [X] T016 [P] Implement memory session mapper in `ai_kefu/xianyu_interceptor/session_mapper.py` (MemorySessionMapper class)
- [X] T017 [P] Implement Redis session mapper in `ai_kefu/xianyu_interceptor/session_mapper.py` (RedisSessionMapper class)
- [X] T018 Implement HTTP client in `ai_kefu/xianyu_interceptor/http_client.py` (AgentClient class with send_message, stream_message, health_check)
- [X] T019 [P] Implement retry logic with tenacity in `ai_kefu/xianyu_interceptor/http_client.py`
- [X] T020 [P] Implement metrics tracking in `ai_kefu/xianyu_interceptor/http_client.py` (HTTPClientMetrics integration)
- [X] T021 [P] Implement manual mode manager in `ai_kefu/xianyu_interceptor/manual_mode.py` (ManualModeManager class)
- [X] T022 [P] Implement custom exceptions in `ai_kefu/xianyu_interceptor/exceptions.py` (AgentAPIError, SessionMapperError, etc.)

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - 消息拦截与转发（核心功能）🎯 MVP

**Goal**: Intercept Xianyu messages and forward to AI Agent service for processing

**Independent Test**: Send a message in Xianyu, verify AI Agent responds through HTTP API

**Capabilities**:
- Xianyu WebSocket message interception
- Message parsing and conversion
- HTTP communication with AI Agent
- Session mapping management
- Response handling and reply

### Implementation for User Story 1

#### Message Interception Integration

- [X] T023 [P] [US1] Refactor `cdp_interceptor.py` to remove old Agent logic and add HTTP client integration
- [X] T024 [P] [US1] Refactor `messaging_core.py` to integrate session mapper and message converter
- [X] T025 [US1] Update message handler in `messaging_core.py` to call AgentClient.send_message()
- [X] T026 [P] [US1] Implement error handling for Agent API failures with logging
- [X] T027 [P] [US1] Implement fallback strategy (skip reply on Agent failure)

#### Main Entry Point

- [X] T028 [US1] Refactor `ai_kefu/main.py` to use new xianyu_interceptor module structure
- [X] T029 [P] [US1] Add configuration loading from .env in main.py
- [X] T030 [P] [US1] Initialize AgentClient, SessionMapper, and ManualModeManager in main.py
- [X] T031 [P] [US1] Add health check for Agent service on startup

#### Response Processing

- [X] T032 [P] [US1] Implement response conversion logic in message_converter.py
- [X] T033 [P] [US1] Implement reply sending through existing transport in messaging_core.py
- [X] T034 [US1] Add comprehensive logging for message flow (receive → convert → Agent → reply)

**Checkpoint**: User Story 1 should be fully functional - Xianyu messages correctly forwarded to Agent and replies sent back

---

## Phase 4: User Story 2 - 手动模式支持

**Goal**: Allow manual intervention in conversations

**Independent Test**: Send toggle keyword, verify auto-reply stops; send again, verify auto-reply resumes

**Capabilities**:
- Manual mode toggle via keyword
- Manual mode timeout handling
- State persistence

### Implementation for User Story 2

- [X] T035 [P] [US2] Implement manual mode toggle handler in messaging_core.py
- [X] T036 [P] [US2] Integrate ManualModeManager into message processing flow
- [X] T037 [US2] Add manual mode check before calling Agent API
- [X] T038 [P] [US2] Implement manual mode timeout check and auto-recovery
- [X] T039 [P] [US2] Add manual mode status reply messages (进入手动模式 / 退出手动模式)
- [ ] T040 [US2] Update session mapper to persist manual mode state

**Checkpoint**: User Story 2 complete - manual mode toggle works correctly with timeout

---

## Phase 5: User Story 3 - 配置与监控

**Goal**: Provide configuration options and monitoring capabilities

**Independent Test**: Change config via .env, restart, verify behavior changes; check metrics and logs

**Capabilities**:
- Environment-based configuration
- Logging and metrics
- Health monitoring

### Implementation for User Story 3

- [ ] T041 [P] [US3] Add all configuration variables to config.py (AGENT_SERVICE_URL, timeouts, retries, etc.)
- [ ] T042 [P] [US3] Implement structured logging setup in `ai_kefu/xianyu_interceptor/logging_setup.py`
- [ ] T043 [US3] Integrate logging throughout all modules (use loguru)
- [ ] T044 [P] [US3] Implement metrics collection in HTTPClientMetrics (success rate, response time, error counts)
- [ ] T045 [P] [US3] Add metrics reporting endpoint or periodic logging
- [ ] T046 [P] [US3] Implement health check endpoint for monitoring (optional HTTP server)
- [ ] T047 [US3] Add configuration validation on startup

**Checkpoint**: All user stories complete - fully configured and monitored system

---

## Phase 6: Testing & Validation

**Purpose**: Comprehensive testing to ensure system reliability

- [ ] T048 [P] Create unit test for AgentClient in `tests/interceptor/test_http_client.py`
- [ ] T049 [P] Create unit test for SessionMapper in `tests/interceptor/test_session_mapper.py`
- [ ] T050 [P] Create unit test for MessageConverter in `tests/interceptor/test_message_converter.py`
- [ ] T051 [P] Create unit test for ManualModeManager in `tests/interceptor/test_manual_mode.py`
- [ ] T052 Create integration test for full message flow in `tests/interceptor/test_integration.py`
- [ ] T053 [P] Create test for manual mode toggle in `tests/interceptor/test_manual_mode_integration.py`
- [ ] T054 [P] Create test for Agent service failure scenarios in `tests/interceptor/test_fallback.py`
- [ ] T055 Test with real Xianyu environment (manual testing)
- [ ] T056 [P] Performance test: verify message processing latency < 500ms
- [ ] T057 [P] Load test: verify handling of 10 concurrent conversations

---

## Phase 7: Documentation & Deployment

**Purpose**: Finalize documentation and prepare for production deployment

- [ ] T058 [P] Update main README.md with new architecture diagram
- [ ] T059 [P] Document migration steps from old to new code in `docs/migration.md`
- [ ] T060 [P] Update quickstart.md with final configuration and testing steps
- [ ] T061 [P] Create deployment guide in `docs/deployment.md`
- [ ] T062 [P] Add inline code documentation (docstrings) to all public functions
- [ ] T063 Create Docker configuration updates if needed (Dockerfile, docker-compose.yml)
- [ ] T064 [P] Create systemd service file example in `docs/systemd-service.md`
- [ ] T065 Final code review and cleanup (remove commented code, optimize imports)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-5)**: All depend on Foundational phase completion
  - User Story 1 (核心功能) can start after Phase 2 - REQUIRED for MVP
  - User Story 2 (手动模式) can start after Phase 2 - depends on US1 message flow
  - User Story 3 (配置监控) can start after Phase 2 - enhances all stories
- **Testing (Phase 6)**: Depends on all desired user stories being complete
- **Documentation (Phase 7)**: Can start in parallel with testing

### User Story Dependencies

- **User Story 1 (核心功能)**: No dependencies on other stories - MVP foundation
- **User Story 2 (手动模式)**: Depends on US1 message processing flow
- **User Story 3 (配置监控)**: Independent, but enhances all stories

### Within Each User Story

- Models and converters before HTTP client usage
- Session mapper before message processing integration
- Error handling after basic flow works
- Logging and metrics throughout

### Parallel Opportunities

- **Phase 1**: T002-T008 can run in parallel (moving/archiving different files)
- **Phase 2**: T013-T014, T016-T017, T019-T022 can run in parallel (independent modules)
- **Phase 3**: T023-T024, T026-T027, T029-T031, T032-T033 can run in parallel
- **Phase 4**: T035-T036, T038-T039 can run in parallel
- **Phase 5**: T041-T042, T044-T046 can run in parallel
- **Phase 6**: All unit tests (T048-T051) can run in parallel, integration tests (T053-T054, T056-T057) can run in parallel
- **Phase 7**: Most documentation tasks (T058-T062, T064) can run in parallel

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001-T011)
2. Complete Phase 2: Foundational (T012-T022) - CRITICAL - blocks all stories
3. Complete Phase 3: User Story 1 (T023-T034)
4. **STOP and VALIDATE**: Test User Story 1 independently
   - Can Xianyu messages reach Agent?
   - Does Agent respond correctly?
   - Are replies sent back to Xianyu?
   - Do logs show all events?
5. Complete Phase 6: Basic Testing (T048-T052, T055)
6. Deploy/demo MVP

**MVP Scope**: ~42 tasks (T001-T034 + T048-T052 + T055) = Core message forwarding works

### Incremental Delivery

1. **Foundation** (T001-T022): Setup + Foundational → Infrastructure ready
2. **MVP** (T023-T034): Add US1 → Test independently → Deploy (Basic HTTP integration!)
3. **Manual Mode** (T035-T040): Add US2 → Test independently → Deploy (Manual control feature!)
4. **Configuration** (T041-T047): Add US3 → Test independently → Deploy (Full monitoring!)
5. **Production Ready** (T048-T065): Testing + Documentation → Production deployment

Each increment adds value without breaking previous capabilities.

---

## Notes

- **[P] tasks**: Different files, no dependencies, safe to parallelize
- **[Story] label**: Maps task to specific user story for traceability
- **Preserve existing functionality**: Browser automation and message parsing logic must remain intact
- **HTTP client**: Use httpx for async operations
- **Session mapper**: Default to memory, support Redis for production
- **Fallback strategy**: Skip reply on Agent failure, log error
- **Manual mode**: Preserve existing toggle keyword logic
- **Configuration**: All via environment variables
- **Logging**: Use loguru for structured logging
- **Testing**: Unit tests for all new modules, integration test for end-to-end flow
- **Commit frequently**: After each task or logical group
- **Independent validation**: Stop at any checkpoint to validate story works standalone

---

## Task Count Summary

- **Phase 1 (Setup)**: 11 tasks
- **Phase 2 (Foundational)**: 11 tasks (CRITICAL PATH)
- **Phase 3 (US1 - 核心功能)**: 12 tasks (MVP)
- **Phase 4 (US2 - 手动模式)**: 6 tasks
- **Phase 5 (US3 - 配置监控)**: 7 tasks
- **Phase 6 (Testing)**: 10 tasks
- **Phase 7 (Documentation)**: 8 tasks

**Total**: 65 tasks

**MVP Scope (US1 + Infrastructure)**: 34 tasks (Phases 1-3)
**Full Feature Set**: 54 tasks (Phases 1-5)
**Production Ready**: All 65 tasks

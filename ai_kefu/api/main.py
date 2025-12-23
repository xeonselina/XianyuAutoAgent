"""
FastAPI application main entry point.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from ai_kefu.config.settings import settings
from ai_kefu.utils.logging import setup_logging, logger
from typing import AsyncGenerator


# Setup logging
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """
    Application lifespan context manager.
    Handles startup and shutdown events.
    """
    # Startup
    logger.info("Starting AI Customer Service Agent...")
    logger.info(f"Configuration: Model={settings.qwen_model}, Port={settings.api_port}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down AI Customer Service Agent...")


# Create FastAPI app
app = FastAPI(
    title="AI Customer Service Agent",
    description="AI-powered customer service agent with knowledge search and human-in-the-loop capabilities",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint (will be replaced by routes)
@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "AI Customer Service Agent API",
        "version": "1.0.0",
        "status": "running"
    }


# Register routes
from ai_kefu.api.routes import system
app.include_router(system.router, tags=["system"])

# Note: Additional routes will be registered in later tasks
# from ai_kefu.api.routes import chat, session, human_agent, knowledge
# app.include_router(chat.router, prefix="/chat", tags=["chat"])
# app.include_router(session.router, prefix="/sessions", tags=["sessions"])
# app.include_router(human_agent.router, prefix="/human-agent", tags=["human-agent"])
# app.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])

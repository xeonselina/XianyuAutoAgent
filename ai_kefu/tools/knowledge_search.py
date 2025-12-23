"""
Knowledge search tool implementation.
T036 - knowledge_search tool.
"""

from typing import Dict, Any, List
from ai_kefu.llm.embeddings import generate_embedding
from ai_kefu.api.dependencies import get_knowledge_store
from ai_kefu.config.constants import DEFAULT_TOP_K
from ai_kefu.utils.logging import logger


def knowledge_search(query: str, top_k: int = DEFAULT_TOP_K) -> Dict[str, Any]:
    """
    Search knowledge base for relevant information.
    
    Args:
        query: Search query
        top_k: Number of results to return (default: 5)
        
    Returns:
        Dict with search results:
        {
            "success": bool,
            "results": [{"id": str, "title": str, "content": str, "score": float}],
            "message": str,
            "error": str (if failed)
        }
    """
    try:
        logger.info(f"Knowledge search: query='{query}', top_k={top_k}")
        
        # Generate embedding for query
        query_embedding = generate_embedding(query, task_type="retrieval_query")
        
        # Search knowledge store
        knowledge_store = get_knowledge_store()
        search_results = knowledge_store.search(
            query_embedding=query_embedding,
            top_k=top_k,
            active_only=True
        )
        
        # Format results
        results = []
        if search_results["ids"] and len(search_results["ids"][0]) > 0:
            for i, doc_id in enumerate(search_results["ids"][0]):
                metadata = search_results["metadatas"][0][i]
                distance = search_results["distances"][0][i]
                
                results.append({
                    "id": doc_id,
                    "title": metadata.get("title", ""),
                    "content": search_results["documents"][0][i],
                    "category": metadata.get("category", ""),
                    "score": 1.0 - distance  # Convert distance to similarity score
                })
        
        message = f"找到 {len(results)} 条相关信息" if results else "未找到相关信息"
        
        logger.info(f"Knowledge search completed: {len(results)} results")
        
        return {
            "success": True,
            "results": results,
            "total": len(results),
            "message": message
        }
        
    except Exception as e:
        error_msg = f"Knowledge search failed: {str(e)}"
        logger.error(error_msg)
        return {
            "success": False,
            "results": [],
            "total": 0,
            "error": error_msg
        }


def get_tool_definition() -> Dict[str, Any]:
    """
    Get knowledge_search tool definition for Qwen Function Calling.
    
    Returns:
        Tool definition dict
    """
    return {
        "name": "knowledge_search",
        "description": """搜索知识库获取相关信息。

使用场景：
- 用户询问产品信息、政策、流程等问题时
- 需要查找具体的业务规则或说明时
- 回答用户问题前，优先检索知识库

注意：使用准确的关键词进行搜索，参考检索结果用自己的语言回答用户。
""",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或问题（使用简洁的关键词效果更好）"
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回结果数量（默认 5 条）",
                    "default": DEFAULT_TOP_K
                }
            },
            "required": ["query"]
        }
    }

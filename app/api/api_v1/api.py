from fastapi import APIRouter, Depends, WebSocket
from app.api.auth import get_current_user, issue_socket_ticket
from app.api.api_v1.endpoints import graph, query, annotation_sharing
from app.api.api_v1.endpoints import search
from app.api.api_v1.endpoints import neighbourhood
api_router = APIRouter()

api_router.include_router(graph.router, tags=["graph"])
api_router.include_router(query.router, tags=["query"])
api_router.include_router(annotation_sharing.router, tags=["annotation_sharing"])
api_router.include_router(neighbourhood.router, tags=["neighbourhood"])
api_router.include_router(
    search.router,
    prefix="/search",
    tags=["search"],
)
 

@api_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Message text was: {data}")
    except Exception as e:
        print(f"WebSocket error: {e}")


@api_router.get("/health")
def health():
    return {"status": "ok"}


@api_router.post("/socket-ticket")
def socket_ticket(user_id: str = Depends(get_current_user)):
    return {"ticket": issue_socket_ticket(user_id)}

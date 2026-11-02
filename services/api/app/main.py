from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.demonstrations import router as demonstrations_router
from app.api.executions import router as executions_router
from app.api.interaction import router as interaction_router
from app.api.navigation import router as navigation_router
from app.api.physical_robot import router as physical_robot_router
from app.api.vision import router as vision_router
from app.api.workflows import router as workflows_router
from app.api.websocket import manager, router as websocket_router
from app.api.visitor_safety import router as visitor_safety_router
from app.api.visitor_welcome import router as visitor_welcome_router
from app.api.visitor_guidance import (
    router as visitor_guidance_router,
    guidance_service,
)

from app.db.database import close_database
from app.robot.hybrid_g1 import HybridG1
from app.services.demonstration_service import DemonstrationService
from app.services.execution_service import execution_service
from app.services.visitor_camera_service import (
    visitor_camera_service,
)
from app.services.visitor_speech_service import (
    visitor_speech_service,
)
from app.tasks.engine import TaskEngine


async def handle_task_event(event: dict) -> None:
    try:
        await execution_service.record_event(event)
    except Exception as error:
        print(f"[EXECUTION HISTORY ERROR] {error}")

    await manager.broadcast(event)


@asynccontextmanager
async def lifespan(app: FastAPI):
    robot = HybridG1()
    await robot.connect()

    task_engine = TaskEngine(
        robot,
        event_handler=handle_task_event,
    )

    demonstration_service = DemonstrationService(
        task_engine
    )

    app.state.robot = robot
    app.state.task_engine = task_engine
    app.state.demonstration_service = demonstration_service
    app.state.execution_service = execution_service
    app.state.visitor_camera_service = visitor_camera_service
    app.state.visitor_speech_service = visitor_speech_service
    app.state.visitor_guidance_service = guidance_service

    await visitor_camera_service.start()
    await visitor_speech_service.start()

    print("[G1 Platform] Backend started")
    print("[G1 Platform] Visitor camera worker started")
    print("[G1 Platform] Visitor speech dispatcher started")
    print("[G1 Platform] Hybrid workflow adapter ready")
    print("[G1 Platform] Physical speech enabled")
    print("[G1 Platform] Navigation remains simulated")

    try:
        yield
    finally:
        await guidance_service.shutdown()
        await visitor_speech_service.stop()
        await visitor_camera_service.stop()
        await robot.disconnect()
        await close_database()
        print("[G1 Platform] Backend stopped")


app = FastAPI(
    title="G1 Thesis Platform API",
    description=(
        "Backend API for the Unitree G1 humanoid "
        "robot guidance and demonstration platform."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(demonstrations_router)
app.include_router(navigation_router)
app.include_router(websocket_router)
app.include_router(workflows_router)
app.include_router(executions_router)
app.include_router(interaction_router)
app.include_router(physical_robot_router)
app.include_router(visitor_safety_router)
app.include_router(vision_router)
app.include_router(visitor_welcome_router)
app.include_router(visitor_guidance_router)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "platform": "G1 Thesis Platform",
        "mode": "simulation",
        "speech_mode": "physical",
        "navigation_mode": "simulation",
    }


@app.get("/api/robot/status")
async def robot_status():
    return await app.state.robot.get_status()


@app.get("/api/visitor-camera/status")
async def visitor_camera_status():
    return visitor_camera_service.status()


@app.get("/api/visitor-speech/status")
async def visitor_speech_status():
    return visitor_speech_service.status()
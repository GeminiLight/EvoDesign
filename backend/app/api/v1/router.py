from fastapi import APIRouter
from app.api.v1.endpoints import auth, diagram, dna, health, project, schema, users

api_router = APIRouter()

v1_router = APIRouter()
v1_router.include_router(health.router)
v1_router.include_router(auth.router)
v1_router.include_router(users.router)
v1_router.include_router(diagram.router)
v1_router.include_router(schema.router)
v1_router.include_router(project.router)
v1_router.include_router(dna.router)

api_router.include_router(v1_router, prefix="/v1")

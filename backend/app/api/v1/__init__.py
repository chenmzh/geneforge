"""API v1 router aggregation."""
from fastapi import APIRouter

from . import auth, external, jobs, projects, sequences, system, tools, users

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(projects.router)
api_router.include_router(sequences.router)
api_router.include_router(tools.router)
api_router.include_router(jobs.router)
api_router.include_router(external.router)

__all__ = ["api_router"]

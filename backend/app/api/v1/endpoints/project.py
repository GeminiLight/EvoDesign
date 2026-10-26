from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated

from app.api.deps import get_current_user_id
from app.db.session import get_db
from app.schemas.project import (
    ProjectCreateRequest,
    ProjectCreateResponse,
    ProjectDetailResponse,
    ProjectListItem,
    ProjectListResponse,
    ProjectSnapshotItem,
    ProjectSnapshotListResponse,
    ProjectUpdateRequest,
    ProjectUpdateResponse,
)
from app.services.project_service import ProjectService


router = APIRouter(prefix="/projects", tags=["Project"])


@router.get("", response_model=ProjectListResponse, status_code=status.HTTP_200_OK)
async def list_projects(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """List current user's projects"""
    service = ProjectService(db)
    projects, total = await service.list_projects(user_id, limit=limit, offset=offset)

    return ProjectListResponse(
        projects=[ProjectListItem.model_validate(project) for project in projects],
        total=total,
    )


@router.post("", response_model=ProjectCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    data: ProjectCreateRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a blank project"""
    service = ProjectService(db)
    project = await service.create_project(user_id, data)
    return ProjectCreateResponse(project_id=project.project_id, created_at=project.created_at)


# Snapshots route BEFORE /{project_id} to avoid route conflicts
@router.get("/{project_id}/snapshots", response_model=ProjectSnapshotListResponse, status_code=status.HTTP_200_OK)
async def get_project_snapshots(
    project_id: str,
    with_trace: bool = Query(False, description="Whether to return thought_trace"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get project snapshots list"""
    service = ProjectService(db)

    snapshots, total, project_version = await service.get_snapshots(
        user_id=user_id,
        project_id=project_id,
        with_trace=with_trace,
        page=page,
        page_size=page_size,
    )

    response_items: list[ProjectSnapshotItem] = []
    for snapshot in snapshots:
        item = ProjectSnapshotItem.model_validate(snapshot)
        if not with_trace:
            item = item.model_copy(update={"thought_trace": None})
        response_items.append(item)

    return ProjectSnapshotListResponse(
        snapshots=response_items,
        page=page,
        page_size=page_size,
        total=total,
        project_version=project_version,
    )


@router.get("/{project_id}", response_model=ProjectDetailResponse, status_code=status.HTTP_200_OK)
async def get_project(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get single project details"""
    service = ProjectService(db)
    project = await service.get_project(user_id, project_id)
    return ProjectDetailResponse.model_validate(project)


@router.put("/{project_id}", response_model=ProjectUpdateResponse, status_code=status.HTTP_200_OK)
async def update_project(
    project_id: str,
    data: ProjectUpdateRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Update project metadata"""
    service = ProjectService(db)
    project = await service.update_project(user_id, project_id, data)
    return ProjectUpdateResponse.model_validate(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Delete project and all its snapshots"""
    service = ProjectService(db)
    await service.delete_project(user_id, project_id)
    return Response(status_code=204)

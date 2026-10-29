"""文件职责：管理正式选品分页、验证材料、状态门禁和时间线。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from merchpilot.api.dependencies import get_current_identity, require_planner
from merchpilot.api.schemas import (
    AuditEventPage,
    AuditEventRead,
    SelectedProductPage,
    SelectedProductPageSummary,
    SelectedProductRead,
    SelectedProductUpdate,
)
from merchpilot.infrastructure.database import get_db_session
from merchpilot.infrastructure.models import AuditEvent, SelectedProduct
from merchpilot.ports.identity import Identity
from merchpilot.services.audit import record_audit_event

router = APIRouter(prefix="/selected-products", tags=["selected-products"])

allowed_statuses = {
    "selected",
    "validating",
    "ready",
    "initiated",
    "launched",
    "paused",
    "cancelled",
}

page_statuses = allowed_statuses | {"initiated_or_launched"}


def _selected_product_conditions(
    tenant_id: str,
    *,
    product_status: str | None = None,
    project_id: str | None = None,
    category: str | None = None,
    validation_status: str | None = None,
    keyword: str | None = None,
    selected_product_id: str | None = None,
) -> list[ColumnElement[bool]]:
    """内部辅助函数`_selected_product_conditions`；拆分主流程并集中处理当前模块的边界条件。"""
    conditions: list[ColumnElement[bool]] = [SelectedProduct.tenant_id == tenant_id]
    if product_status is not None:
        if product_status not in page_statuses:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid selected product status",
            )
        if product_status == "initiated_or_launched":
            conditions.append(SelectedProduct.status.in_(("initiated", "launched")))
        else:
            conditions.append(SelectedProduct.status == product_status)
    if project_id is not None:
        conditions.append(SelectedProduct.project_id == project_id)
    if category is not None:
        conditions.append(SelectedProduct.category == category)
    if validation_status is not None:
        if validation_status == "pending":
            conditions.append(
                (SelectedProduct.validation_status != "ready")
                | SelectedProduct.validation_status.is_(None)
            )
        elif validation_status in {"ready", "blocked"}:
            conditions.append(SelectedProduct.validation_status == validation_status)
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid selected product validation status",
            )
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        conditions.append(
            or_(
                SelectedProduct.name.ilike(pattern),
                SelectedProduct.id.ilike(pattern),
                SelectedProduct.candidate_id.ilike(pattern),
                SelectedProduct.project_name.ilike(pattern),
                SelectedProduct.category.ilike(pattern),
                SelectedProduct.target_market.ilike(pattern),
                SelectedProduct.positioning.ilike(pattern),
                SelectedProduct.supplier_name.ilike(pattern),
                SelectedProduct.owner_id.ilike(pattern),
            )
        )
    if selected_product_id is not None:
        conditions.append(SelectedProduct.id == selected_product_id)
    return conditions


@router.get("", response_model=list[SelectedProductRead])
async def list_selected_products(
    product_status: str | None = Query(default=None, alias="status"),
    project_id: str | None = None,
    category: str | None = None,
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[SelectedProduct]:
    """处理`GET `接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    query = select(SelectedProduct).where(SelectedProduct.tenant_id == identity.tenant_id)
    if product_status is not None:
        if product_status not in allowed_statuses:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid selected product status",
            )
        query = query.where(SelectedProduct.status == product_status)
    if project_id is not None:
        query = query.where(SelectedProduct.project_id == project_id)
    if category is not None:
        query = query.where(SelectedProduct.category == category)
    result = await session.scalars(
        query.order_by(SelectedProduct.selected_at.desc(), SelectedProduct.id.desc())
    )
    return list(result)


@router.get("/page", response_model=SelectedProductPage)
async def page_selected_products(
    response: Response,
    product_status: str | None = Query(default=None, alias="status"),
    project_id: str | None = None,
    category: str | None = None,
    validation_status: str | None = Query(default=None, alias="validation_status"),
    keyword: str | None = Query(default=None, min_length=1, max_length=255),
    selected_product_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=6, ge=1, le=100),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """处理`GET /page`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    filtered_conditions = _selected_product_conditions(
        identity.tenant_id,
        product_status=product_status,
        project_id=project_id,
        category=category,
        validation_status=validation_status,
        keyword=keyword,
        selected_product_id=selected_product_id,
    )
    summary_conditions = _selected_product_conditions(
        identity.tenant_id,
        project_id=project_id,
    )
    total = int(
        await session.scalar(
            select(func.count(SelectedProduct.id)).where(*filtered_conditions)
        )
        or 0
    )
    summary_counts = await session.execute(
        select(
            SelectedProduct.status,
            SelectedProduct.validation_status,
            func.count(SelectedProduct.id),
        )
        .where(*summary_conditions)
        .group_by(SelectedProduct.status, SelectedProduct.validation_status)
    )
    counts: dict[str, int] = {}
    validating = 0
    for product_status, validation_status, count in summary_counts:
        normalized_status = str(product_status)
        normalized_count = int(count)
        counts[normalized_status] = counts.get(normalized_status, 0) + normalized_count
        if normalized_status in {"selected", "validating"} and validation_status != "ready":
            validating += normalized_count
    categories = list(
        await session.scalars(
            select(SelectedProduct.category)
            .where(*summary_conditions)
            .distinct()
            .order_by(SelectedProduct.category.asc())
        )
    )
    result = await session.scalars(
        select(SelectedProduct)
        .where(*filtered_conditions)
        .order_by(SelectedProduct.selected_at.desc(), SelectedProduct.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    response.headers["X-Total-Count"] = str(total)
    return {
        "items": list(result),
        "total": total,
        "page": page,
        "page_size": page_size,
        "categories": categories,
        "summary": SelectedProductPageSummary(
            total=sum(counts.values()),
            validating=validating,
            ready=counts.get("ready", 0),
            initiated=counts.get("initiated", 0) + counts.get("launched", 0),
            paused=counts.get("paused", 0),
        ).model_dump(),
    }


@router.get("/{selected_product_id}", response_model=SelectedProductRead)
async def get_selected_product(
    selected_product_id: str,
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> SelectedProduct:
    """处理`GET /{selected_product_id}`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    selected_product = await session.scalar(
        select(SelectedProduct).where(
            SelectedProduct.id == selected_product_id,
            SelectedProduct.tenant_id == identity.tenant_id,
        )
    )
    if selected_product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="selected product not found")
    return selected_product


@router.get("/{selected_product_id}/timeline/page", response_model=AuditEventPage)
async def page_selected_product_timeline(
    response: Response,
    selected_product_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=8, ge=1, le=100),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """处理该接口。

    执行身份、租户、参数和业务状态校验后返回类型化响应。
    """
    selected_product = await session.scalar(
        select(SelectedProduct).where(
            SelectedProduct.id == selected_product_id,
            SelectedProduct.tenant_id == identity.tenant_id,
        )
    )
    if selected_product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="selected product not found")
    conditions = [
        AuditEvent.tenant_id == identity.tenant_id,
        AuditEvent.entity_type == "selected_product",
        AuditEvent.entity_id == selected_product.id,
    ]
    total = int(await session.scalar(select(func.count(AuditEvent.id)).where(*conditions)) or 0)
    events = await session.scalars(
        select(AuditEvent)
        .where(*conditions)
        .order_by(AuditEvent.sequence_no.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    response.headers["X-Total-Count"] = str(total)
    return {
        "items": list(events),
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{selected_product_id}/timeline", response_model=list[AuditEventRead])
async def get_selected_product_timeline(
    selected_product_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    identity: Identity = Depends(get_current_identity),
    session: AsyncSession = Depends(get_db_session),
) -> list[AuditEvent]:
    """处理`GET /{selected_product_id}/timeline`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    selected_product = await session.scalar(
        select(SelectedProduct).where(
            SelectedProduct.id == selected_product_id,
            SelectedProduct.tenant_id == identity.tenant_id,
        )
    )
    if selected_product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="selected product not found")
    result = await session.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.tenant_id == identity.tenant_id,
            AuditEvent.entity_type == "selected_product",
            AuditEvent.entity_id == selected_product.id,
        )
        .order_by(AuditEvent.sequence_no.desc())
        .limit(limit)
    )
    return list(result)


@router.patch("/{selected_product_id}", response_model=SelectedProductRead)
async def update_selected_product(
    selected_product_id: str,
    payload: SelectedProductUpdate,
    identity: Identity = Depends(require_planner),
    session: AsyncSession = Depends(get_db_session),
) -> SelectedProduct:
    """处理`PATCH /{selected_product_id}`接口；执行身份、租户、参数和业务状态校验后返回类型化响应。"""
    selected_product = await session.scalar(
        select(SelectedProduct)
        .where(
            SelectedProduct.id == selected_product_id,
            SelectedProduct.tenant_id == identity.tenant_id,
        )
        .with_for_update()
    )
    if selected_product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="selected product not found")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return selected_product
    previous = {
        "status": selected_product.status,
        "owner_id": selected_product.owner_id,
        "notes": selected_product.notes,
    }
    if "status" in changes and changes["status"] is not None:
        next_status = str(changes["status"])
        if (
            selected_product.status in {"initiated", "paused", "launched"}
            and next_status != selected_product.status
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="进入立项后的商品状态只能由商品立项流程更新",
            )
        if selected_product.status == "cancelled" and next_status != "cancelled":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="已取消正式选品不能恢复或继续推进",
            )
        if next_status in {"initiated", "launched"} and next_status != selected_product.status:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="立项和上市状态只能由商品立项流程更新",
            )
        if next_status == "ready" and selected_product.validation_status != "ready":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="落地验证尚未完成，不能标记为可进入立项",
            )
        if (
            next_status in {"selected", "validating"}
            and selected_product.validation_status == "ready"
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="验证已通过；如需重新验证，请先更新验证清单",
            )
        selected_product.status = next_status
    if "owner_id" in changes:
        selected_product.owner_id = str(changes["owner_id"] or "").strip() or None
    if "notes" in changes:
        selected_product.notes = str(changes["notes"] or "").strip() or None
    record_audit_event(
        session,
        action="selected_product.updated",
        entity_type="selected_product",
        entity_id=selected_product.id,
        project_id=selected_product.project_id,
        tenant_id=identity.tenant_id,
        actor_id=identity.user_id,
        detail={
            "changed_fields": sorted(changes),
            "previous": previous,
            "current": {
                "status": selected_product.status,
                "owner_id": selected_product.owner_id,
                "notes": selected_product.notes,
            },
        },
    )
    await session.commit()
    await session.refresh(selected_product)
    return selected_product

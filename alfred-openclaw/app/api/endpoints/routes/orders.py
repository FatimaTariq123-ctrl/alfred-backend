from fastapi import APIRouter, Depends, HTTPException

from app.schemas.orders_schema import ConditionalOrderCreate
from app.services.orders_service import OrdersService
from app.backend_services.jwt_auth.security import get_current_user

orders_router = APIRouter()


def get_orders_service() -> OrdersService:
    return OrdersService()


# ==========================================
# POST /conditional_orders — create
# ==========================================
@orders_router.post("/conditional_orders")
def create_conditional_order(
    order: ConditionalOrderCreate,
    user_id: str = Depends(get_current_user),
    service: OrdersService = Depends(get_orders_service),
):
    try:
        return service.create(user_id, order)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


# ==========================================
# GET /conditional_orders — list active
# ==========================================
@orders_router.get("/conditional_orders")
def list_conditional_orders(
    user_id: str = Depends(get_current_user),
    service: OrdersService = Depends(get_orders_service),
):
    try:
        return service.list_active(user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


# ==========================================
# DELETE /conditional_orders/{order_id}
# ==========================================
@orders_router.delete("/conditional_orders/{order_id}")
def delete_conditional_order(
    order_id: str,
    user_id: str = Depends(get_current_user),
    service: OrdersService = Depends(get_orders_service),
):
    try:
        result = service.delete(user_id, order_id)
        if not result:
            raise HTTPException(status_code=404, detail="Order not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")

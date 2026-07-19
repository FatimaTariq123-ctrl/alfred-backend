from typing import List, Optional
import logging
from app.schemas.conditional_orders import ConditionalOrderResponse, TriggerType, OrderAction, TriggerStatus
from app.services.events import ExecutionEventDispatcher

logger = logging.getLogger(__name__)

class MarketDataServiceMock:
    """Mock service to represent live market data feeds."""
    @staticmethod
    def get_current_price(asset: str) -> float:
        # Mock prices for demonstration purposes
        prices = {"AAPL": 150.00, "BTC": 60000.00, "ETH": 3000.00}
        return prices.get(asset.upper(), 100.00)

class TriggerEvaluatorService:
    def __init__(self, order_service):
        """
        Takes the ConditionalOrderService as a dependency to fetch active orders
        and update their statuses independent of chat history.
        """
        self.order_service = order_service
        self.market_data = MarketDataServiceMock()

    def validate_trigger(self, order: ConditionalOrderResponse, current_price: float) -> bool:
        """
        Validates trigger conditions BEFORE activation to ensure the deterministic logic is sound.
        Only validated triggers proceed.
        """
        if order.trigger_type == TriggerType.STOP_LOSS:
            if order.action == OrderAction.SELL and order.trigger_value >= current_price:
                logger.warning(f"Invalid STOP_LOSS SELL: trigger {order.trigger_value} >= current {current_price}")
                return False
        elif order.trigger_type == TriggerType.TAKE_PROFIT:
            if order.action == OrderAction.SELL and order.trigger_value <= current_price:
                logger.warning(f"Invalid TAKE_PROFIT SELL: trigger {order.trigger_value} <= current {current_price}")
                return False
        elif order.trigger_type == TriggerType.LIMIT_ORDER:
            if order.action == OrderAction.BUY and order.trigger_value >= current_price:
                 logger.warning(f"Invalid LIMIT_ORDER BUY: trigger {order.trigger_value} >= current {current_price}")
                 return False
                 
        return True

    def activate_pending_orders(self, pending_orders: List[ConditionalOrderResponse]):
        """
        Checks pending orders and validates them against current market data before marking ACTIVE.
        """
        for order in pending_orders:
            current_price = self.market_data.get_current_price(order.asset)
            if self.validate_trigger(order, current_price):
                self.order_service.update_order_status(order.id, TriggerStatus.ACTIVE)
                logger.info(f"Order {order.id} validated and marked ACTIVE.")
            else:
                self.order_service.update_order_status(order.id, TriggerStatus.CANCELLED)
                logger.error(f"Order {order.id} failed validation and was CANCELLED.")

    def evaluate_active_triggers(self):
        """
        Continuously evaluate active triggers against live market data.
        Converts instructions into deterministic execution rules.
        """
        active_orders = self.order_service.get_active_orders()
        
        for order in active_orders:
            current_price = self.market_data.get_current_price(order.asset)
            condition_met = False
            
            # Deterministic Evaluation Logic
            if order.trigger_type == TriggerType.STOP_LOSS and order.action == OrderAction.SELL:
                condition_met = current_price <= order.trigger_value
                
            elif order.trigger_type == TriggerType.TAKE_PROFIT and order.action == OrderAction.SELL:
                condition_met = current_price >= order.trigger_value
                
            elif order.trigger_type == TriggerType.LIMIT_ORDER and order.action == OrderAction.BUY:
                condition_met = current_price <= order.trigger_value
                
            # Emit event and update state if condition satisfied
            if condition_met:
                logger.info(f"Condition met for order {order.id}! {order.asset} @ {current_price}")
                
                # 1. Generate execution event to the pipeline
                ExecutionEventDispatcher.emit_execution_event(
                    order_id=order.id,
                    asset=order.asset,
                    action=order.action,
                    current_price=current_price,
                    trigger_value=order.trigger_value
                )
                
                # 2. Update status so it doesn't trigger twice
                self.order_service.update_order_status(order.id, TriggerStatus.TRIGGERED)

"""
Global Order Monitoring Service

This service provides order monitoring capabilities that continue running
even when the initiating widget is unmounted. It's designed to solve the
issue where automatic price improvement stops when switching screens.
"""

import asyncio
from typing import Dict, Optional, Callable, Any
from datetime import datetime


class OrderMonitoringService:
    """A global service for monitoring orders independently of widget lifecycles."""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(OrderMonitoringService, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        # Prevent re-initialization
        if self._initialized:
            return
            
        self._monitoring_tasks: Dict[str, asyncio.Task] = {}  # order_id -> task
        self._app_reference = None
        self._status_callbacks: Dict[str, Callable] = {}  # order_id -> callback
        self._cleanup_callbacks: Dict[str, Callable] = {}  # order_id -> callback
        self._initialized = True
    
    def set_app_reference(self, app):
        """Set the app reference for accessing StatusLog from any screen."""
        self._app_reference = app
    
    def add_status_callback(self, order_id: str, callback: Callable):
        """Add a callback for status updates for a specific order."""
        self._status_callbacks[order_id] = callback
    
    def remove_status_callback(self, order_id: str):
        """Remove a status callback for a specific order."""
        self._status_callbacks.pop(order_id, None)
    
    def add_cleanup_callback(self, order_id: str, callback: Callable):
        """Add a cleanup callback that will be called when monitoring stops."""
        self._cleanup_callbacks[order_id] = callback
    
    def remove_cleanup_callback(self, order_id: str):
        """Remove a cleanup callback for a specific order."""
        self._cleanup_callbacks.pop(order_id, None)
    
    def log_message(self, message: str):
        """Log a message to the StatusLog if app reference is available."""
        try:
            if self._app_reference:
                from ui.widgets.status_log import StatusLog
                self._app_reference.query_one(StatusLog).add_message(message)
        except Exception:
            # If we can't log to StatusLog, print to console as fallback
            print(f"[Order Monitoring Service] {message}")
    
    async def check_order_status(self, api, order_id: str) -> Dict[str, Any]:
        """Check the status of an order."""
        try:
            # Use the existing logic from the application
            from ui import logic as ui_logic
            return await ui_logic.check_order(api, order_id)
        except Exception as e:
            self.log_message(f"Error checking order status for {order_id}: {e}")
            return {"filled": False, "status": "ERROR", "rejection_reason": str(e)}
    
    async def cancel_order(self, api, order_id: str):
        """Cancel an order."""
        try:
            from ui import logic as ui_logic
            await ui_logic.cancel_order(api, order_id)
        except Exception as e:
            self.log_message(f"Error cancelling order {order_id}: {e}")
    
    def start_monitoring(self, order_id: str, api, initial_price: float, 
                        price_improvement_callback: Optional[Callable] = None,
                        completion_callback: Optional[Callable] = None,
                        timeout: int = 60):
        """Start monitoring an order with automatic price improvements."""
        if order_id in self._monitoring_tasks:
            self.log_message(f"Order {order_id} is already being monitored")
            return
        
        # Create and start the monitoring task
        task = asyncio.create_task(
            self._monitor_order_task(
                order_id, api, initial_price, 
                price_improvement_callback, 
                completion_callback,
                timeout
            )
        )
        self._monitoring_tasks[order_id] = task
        self.log_message(f"Started monitoring order {order_id}")
    
    def stop_monitoring(self, order_id: str):
        """Stop monitoring a specific order."""
        task = self._monitoring_tasks.get(order_id)
        if task and not task.done():
            task.cancel()
        
        # Clean up callbacks
        self._status_callbacks.pop(order_id, None)
        cleanup_cb = self._cleanup_callbacks.pop(order_id, None)
        if cleanup_cb:
            try:
                cleanup_cb()
            except Exception:
                pass
        
        # Remove from tasks
        self._monitoring_tasks.pop(order_id, None)
        self.log_message(f"Stopped monitoring order {order_id}")
    
    def stop_all_monitoring(self):
        """Stop monitoring all orders."""
        order_ids = list(self._monitoring_tasks.keys())
        for order_id in order_ids:
            self.stop_monitoring(order_id)
    
    async def _monitor_order_task(self, order_id: str, api, initial_price: float,
                                 price_improvement_callback: Optional[Callable],
                                 completion_callback: Optional[Callable],
                                 timeout: int):
        """The actual monitoring task that runs asynchronously."""
        try:
            start_time = asyncio.get_event_loop().time()
            last_status_check = 0
            last_print_time = 0
            print_interval = 5  # Print status every 5 seconds
            
            attempt = 0
            
            while asyncio.get_event_loop().time() - start_time < timeout:
                current_time = asyncio.get_event_loop().time()
                elapsed_time = int(current_time - start_time)
                
                try:
                    if current_time - last_status_check >= 1:  # Check every second
                        order_status = await self.check_order_status(api, order_id)
                        last_status_check = current_time
                        
                        if current_time - last_print_time >= print_interval:
                            remaining = int(timeout - elapsed_time)
                            status_str = order_status.get('status', 'UNKNOWN')
                            rejection_reason = order_status.get('rejection_reason', '')
                            status_msg = f"Status: {status_str} {rejection_reason} | Time remaining: {remaining}s | Price: {order_status.get('price', 'N/A')} | Filled: {order_status.get('filledQuantity', '0')}"
                            
                            # Use callback if available, otherwise log directly
                            status_cb = self._status_callbacks.get(order_id)
                            if status_cb:
                                try:
                                    status_cb(status_msg)
                                except Exception:
                                    self.log_message(status_msg)
                            else:
                                self.log_message(status_msg)
                            
                            last_print_time = current_time
                        
                        # Check if order is filled
                        if order_status.get("filled", False):
                            self.log_message(f"Order {order_id} filled successfully!")
                            
                            # Call completion callback if provided
                            if completion_callback:
                                try:
                                    completion_callback(True)  # True = success
                                except Exception as e:
                                    self.log_message(f"Error in completion callback: {e}")
                            
                            # Stop monitoring this order
                            self.stop_monitoring(order_id)
                            return True
                        
                        # Check if order is rejected
                        if order_status.get("status") == "REJECTED":
                            rejection_msg = f"Order rejected: {order_status.get('rejection_reason', 'No reason provided')}"
                            self.log_message(rejection_msg)
                            
                            # Call completion callback if provided
                            if completion_callback:
                                try:
                                    completion_callback("rejected")
                                except Exception as e:
                                    self.log_message(f"Error in completion callback: {e}")
                            
                            # Try price improvement if callback is provided
                            if price_improvement_callback:
                                try:
                                    should_continue = price_improvement_callback("rejected", order_id, attempt)
                                    if not should_continue:
                                        self.stop_monitoring(order_id)
                                        return "rejected"
                                except Exception as e:
                                    self.log_message(f"Error in price improvement callback: {e}")
                                    self.stop_monitoring(order_id)
                                    return "rejected"
                            else:
                                self.stop_monitoring(order_id)
                                return "rejected"
                        
                        # Check if order is cancelled
                        if order_status.get("status") == "CANCELED":
                            self.log_message(f"Order {order_id} cancelled.")
                            
                            # Call completion callback if provided
                            if completion_callback:
                                try:
                                    completion_callback("cancelled")
                                except Exception as e:
                                    self.log_message(f"Error in completion callback: {e}")
                            
                            self.stop_monitoring(order_id)
                            return "cancelled"
                    
                    # Small sleep to prevent CPU thrashing
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    self.log_message(f"Error checking order status: {e}")
                    # Continue monitoring despite errors
                    
            # If we reach here, order timed out
            self.log_message(f"Order {order_id} timed out.")
            
            # Try price improvement if callback is provided
            if price_improvement_callback:
                try:
                    should_continue = price_improvement_callback("timeout", order_id, attempt)
                    if not should_continue:
                        self.stop_monitoring(order_id)
                        return "timeout"
                except Exception as e:
                    self.log_message(f"Error in price improvement callback: {e}")
                    self.stop_monitoring(order_id)
                    return "timeout"
            else:
                # Cancel the timed-out order
                try:
                    await self.cancel_order(api, order_id)
                    self.log_message(f"Cancelled timed-out order {order_id}")
                except Exception as e:
                    self.log_message(f"Error cancelling timed-out order {order_id}: {e}")
                
                self.stop_monitoring(order_id)
                return "timeout"
                
        except asyncio.CancelledError:
            self.log_message(f"Monitoring of order {order_id} was cancelled")
            return "cancelled"
        except Exception as e:
            self.log_message(f"Error in monitoring task for order {order_id}: {e}")
            return False
        finally:
            # Ensure cleanup callback is called
            cleanup_cb = self._cleanup_callbacks.pop(order_id, None)
            if cleanup_cb:
                try:
                    cleanup_cb()
                except Exception:
                    pass


# Global instance
order_monitoring_service = OrderMonitoringService()
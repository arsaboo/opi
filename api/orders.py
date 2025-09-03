import time
from datetime import datetime, time as time_module
from tzlocal import get_localzone
from status import notify, notify_exception

# Global flag for order cancellation
cancel_order = False

def handle_cancel(e):
    global cancel_order
    if e.name == 'c':
        cancel_order = True
        notify("Cancelling order...")

def reset_cancel_flag():
    """Reset the global cancel flag"""
    global cancel_order
    cancel_order = False

def monitor_order(api, order_id, timeout=60):
    """Monitor order status and handle cancellation with dynamic display"""
    global cancel_order

    start_time = time.time()
    last_status_check = 0
    next_log_time = 0  # throttle UI log updates

    while time.time() - start_time < timeout:
        current_time = time.time()
        elapsed_time = int(current_time - start_time)

        if cancel_order:
            try:
                api.cancelOrder(order_id)
                notify("Order cancelled by user.")
                return "cancelled"
            except Exception as e:
                notify_exception(e, prefix="Error cancelling order")
                return False

        try:
            if current_time - last_status_check >= 1:  # Check every second
                order_status = api.checkOrder(order_id)
                last_status_check = current_time

                if current_time >= next_log_time:
                    remaining = int(timeout - elapsed_time)
                    status_str = order_status.get('status', 'N/A')
                    rejection_reason = order_status.get('rejection_reason', '')
                    price = order_status.get('price', 'N/A')
                    filled = order_status.get('filledQuantity', '0')
                    msg = f"Status: {status_str} {rejection_reason} | Remaining: {remaining}s | Price: {price} | Filled: {filled}"
                    notify(msg)
                    next_log_time = current_time + 5  # log every 5s

                if order_status["filled"]:
                    notify("Order filled successfully!")
                    return True
                elif order_status["status"] == "REJECTED":
                    notify("Order rejected: " + order_status.get('rejection_reason', 'No reason provided'))
                    return "rejected"
                elif order_status["status"] == "CANCELED":
                    notify("Order cancelled.")
                    return False

            time.sleep(0.1)  # Small sleep to prevent CPU thrashing

        except Exception as e:
            notify_exception(e, prefix="Error checking order status")
            return False

    # If we reach here, order timed out
    notify("Order timed out, moving to price improvement...")
    try:
        api.cancelOrder(order_id)
    except:
        pass
    return "timeout"

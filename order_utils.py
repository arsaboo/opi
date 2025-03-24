import time
from datetime import datetime, time as time_module
from tzlocal import get_localzone

# Global flag for order cancellation
cancel_order = False

def handle_cancel(e):
    global cancel_order
    if e.name == 'c':
        cancel_order = True
        print("\nCancelling order...")

def reset_cancel_flag():
    """Reset the global cancel flag"""
    global cancel_order
    cancel_order = False

def monitor_order(api, order_id, timeout=60):
    """Monitor order status and handle cancellation with dynamic display"""
    global cancel_order

    start_time = time.time()
    last_status_check = 0
    last_print_time = 0
    print_interval = 1

    while time.time() - start_time < timeout:
        current_time = time.time()
        elapsed_time = int(current_time - start_time)

        if cancel_order:
            try:
                api.cancelOrder(order_id)
                print("\nOrder cancelled by user.")
                return "cancelled"
            except Exception as e:
                print(f"\nError cancelling order: {e}")
                return False

        try:
            if current_time - last_status_check >= 1:  # Check every second
                order_status = api.checkOrder(order_id)
                last_status_check = current_time

                if current_time - last_print_time >= print_interval:
                    remaining = int(timeout - elapsed_time)
                    status_str = order_status['status']
                    rejection_reason = order_status.get('rejection_reason', '')

                    print(f"\rStatus: {status_str} {rejection_reason} | "
                          f"Time remaining: {remaining}s | "
                          f"Price: {order_status.get('price', 'N/A')} | "
                          f"Filled: {order_status.get('filledQuantity', '0')}  ", end="", flush=True)
                    last_print_time = current_time

                if order_status["filled"]:
                    print(f"\nOrder filled successfully!")
                    return True
                elif order_status["status"] == "REJECTED":
                    print(f"\nOrder rejected: {order_status.get('rejection_reason', 'No reason provided')}")
                    return "rejected"
                elif order_status["status"] == "CANCELED":
                    print("\nOrder cancelled.")
                    return False

            time.sleep(0.1)  # Small sleep to prevent CPU thrashing

        except Exception as e:
            print(f"\nError checking order status: {e}")
            return False

    # If we reach here, order timed out
    print("\nOrder timed out, moving to price improvement...")
    try:
        api.cancelOrder(order_id)
    except:
        pass
    return "timeout"

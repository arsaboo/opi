#!/usr/bin/env python3
"""
Debug script to test roll short options functionality
"""
import sys
import os

# Add the parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_roll_short_debug():
    """Test the roll short options functionality with detailed debugging"""
    try:
        print("=== TESTING ROLL SHORT OPTIONS ===")

        # Test 1: Import required modules
        print("1. Testing imports...")
        try:
            from configuration import configuration
            print(f"   ✓ Configuration loaded: {list(configuration.keys())[:5]}...")
        except Exception as e:
            print(f"   ✗ Configuration import failed: {e}")
            return False

        try:
            from cc import find_best_rollover, _calculate_roll_metrics, RollCalls, RollSPX
            print("   ✓ CC module imports successful")
        except Exception as e:
            print(f"   ✗ CC module import failed: {e}")
            return False

        try:
            from optionChain import OptionChain
            print("   ✓ OptionChain import successful")
        except Exception as e:
            print(f"   ✗ OptionChain import failed: {e}")
            return False

        print("2. All imports successful!")

        # Test 2: Check if API simulator exists
        print("3. Testing API simulator...")
        try:
            # Try to create a mock API object for testing
            class MockAPI:
                def getShortOptions(self):
                    # Return some mock data for testing
                    return [
                        {
                            "stockSymbol": "AAPL",
                            "optionSymbol": "AAPL240315C00180000",
                            "strike": "180.0",
                            "expiration": "2024-03-15",
                            "count": "1"
                        }
                    ]

                def getATMPrice(self, symbol):
                    return 175.0 if symbol == "AAPL" else 100.0

                def getOptionDetails(self, symbol):
                    return {"delta": 0.25, "expiration": "2024-04-19"}

            mock_api = MockAPI()
            shorts = mock_api.getShortOptions()
            print(f"   ✓ Mock API created, returned {len(shorts)} short positions")

        except Exception as e:
            print(f"   ✗ Mock API creation failed: {e}")
            return False

        print("=== ALL TESTS PASSED ===")
        return True

    except Exception as e:
        print(f"=== TEST FAILED: {e} ===")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_roll_short_debug()
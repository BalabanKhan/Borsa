import sys
import logging

logging.basicConfig(level=logging.INFO)

from strategies_v5 import scan_all_markets

def test_scan():
    print("Testing scan_all_markets with minimal assets...")
    try:
        # Use minimal parameters to speed up test
        signals, metrics = scan_all_markets()
        print("Success! Generated {} signals.".format(len(signals)))
        for sig in signals[:3]:
            print(sig)
    except Exception as e:
        print("Error during scan:")
        logging.exception(e)

if __name__ == "__main__":
    test_scan()

import sys
import logging

logging.basicConfig(level=logging.INFO)

from strategies import scan_all_markets

def test_scan():
    print("Testing scan_all_markets with minimal assets...")
    try:
        # Use minimal parameters to speed up test
        signals, metrics = scan_all_markets()
        print("Success! Generated {} signals.".format(len(signals)))
        for sig in signals[:3]:
            try:
                print(sig)
            except UnicodeEncodeError:
                import sys
                sys.stdout.buffer.write((str(sig) + "\n").encode('utf-8'))
    except Exception as e:
        print("Error during scan:")
        logging.exception(e)

if __name__ == "__main__":
    test_scan()

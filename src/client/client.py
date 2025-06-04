# Importing the Required Libraries
import requests, random, time, os, argparse, logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Global Environement Variables
FRONTEND_SERVICE_URL = os.environ.get("FRONTEND_SERVICE_URL", "http://frontend-service:9001")
NUM_ITERATIONS = 50
STOCKS = ["APPL", "GOOG", "MSFT", "AMZN", "TSLA", "META", "NFLX", "NVDA", "AMD", "IBM", "INTC"]

successful_order_details = []

# Helper Functions used in the clientSession function to lookup stocks, buy stocks, and query order successful order details
def lookupStock(session, stock_name):
    try:
        response = session.get(f"{FRONTEND_SERVICE_URL}/stocks/{stock_name}")
        if response.status_code == 200:
            data = response.json().get("data", {})
            print(f"Lookup successful: {data}")
            return data
        else:
            error = response.json().get("error", {})
            print(f"Lookup failed: {error}")
            return None
    except requests.RequestException as e:
        print(f"Error during stock lookup: {e}")
        return None

def buyStock(session, stock_name, trade_type, quantity):
    try:
        order_data = {
            "stock_name": stock_name,
            "type": trade_type,
            "quantity": quantity
        }
        response = session.post(f"{FRONTEND_SERVICE_URL}/orders", json=order_data)
        if response.status_code == 200:
            data = response.json().get("data", {})
            transaction_number = data.get("transaction_number")
            print(f"Order successful: Transaction Number = {transaction_number}")
            return transaction_number, order_data
        else:
            error = response.json().get("error", {})
            print(f"Order failed: {error}")
            return None, None
    except requests.RequestException as e:
        print(f"Error during order placement: {e}")
        return None, None

def queryOrderDetails(session, transaction_number):
    try:
        response = session.get(f"{FRONTEND_SERVICE_URL}/orders/{transaction_number}")
        if response.status_code == 200:
            data = response.json().get("data", {})
            print(f"Order Query Successful: {data}")
            return data
        else:
            error = response.json().get("error", {})
            print(f"Order Query Failed: {error}")
            return None
    except requests.RequestException as e:
        print(f"Error during order query: {e}")
        return None

# Helper Function to measure the latency of each request which is sent to Catalog and Order services
def clientSession(probability_p, num_iterations):
    with requests.Session() as session:
        for _ in range(num_iterations):
            stock_name = random.choice(STOCKS)
            stock_data = lookupStock(session, stock_name)

            if stock_data and stock_data.get("quantity", 0) > 0:
                if random.random() < probability_p:
                    trade_type = random.choice(["buy", "sell"])
                    quantity = random.randint(1, stock_data["quantity"])
                    print(f"Placing {trade_type} order for {quantity} of {stock_name}")
                    transaction_number, order_data = buyStock(session, stock_name, trade_type, quantity)
                    if transaction_number:
                        successful_order_details.append({"transaction_number": transaction_number, "order_data": order_data})

            time.sleep(random.uniform(1, 3))

        print("\nVerifying all successful order queries.")
        for order in successful_order_details:
            transaction_number = order["transaction_number"]
            local_order_data = order["order_data"]
            server_order_data = queryOrderDetails(session, transaction_number)

            if server_order_data:
                normalized_server_data = {
                    "stock_name": server_order_data.get("name"),
                    "type": server_order_data.get("type"),
                    "quantity": server_order_data.get("quantity")
                }

                if normalized_server_data == local_order_data:
                    print(f"Order {transaction_number} is verified successfully.")
                else:
                    print(f"Order {transaction_number} is verification failed.")
            else:
                print(f"Order {transaction_number} is verification failed.")

# Reference: LAB 2 - Client File
if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument('-p', '--probability', type=float, default=0.5, help="Probability for placing a trade (default: 0.5)")
        args = parser.parse_args()

        if not (0 <= args.probability <= 1):
            raise ValueError("Probability must be between 0 and 1.")

        print(f"Client with probability p={args.probability} and iterations={NUM_ITERATIONS}")

        try:
            clientSession(args.probability, NUM_ITERATIONS)
        except Exception as e:
            logger.error(f"Unexpected error during client session: {e}")
            print(f"An error occurred during the client session: {e}")

    except ValueError as ve:
        logger.error(f"Invalid argument: {ve}")
        print(f"Invalid argument: {ve}")
    except Exception as e:
        logger.error(f"Unexpected error in main: {e}")
        print(f"An unexpected error occurred: {e}")
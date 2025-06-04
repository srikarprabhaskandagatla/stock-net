# Importing the Required Libraries
import requests, random, time, os, concurrent.futures, logging
import matplotlib.pyplot as plt
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Global Environement Variables
FRONTEND_SERVICE_URL = os.environ.get("FRONTEND_SERVICE_URL", "http://frontend-service:9001")
NUM_ITERATIONS = 50 # Number of iterations for each client session
NUM_CLIENTS = 5 # Number of clients to simulate
CACHE_ENABLED = int(os.environ.get("CACHE_ENABLED","1"))
STOCKS = ["APPL", "GOOG", "MSFT", "AMZN", "TSLA", "META", "NFLX", "NVDA", "AMD", "IBM", "INTC"]

successful_order_details = []

# Helper Functions used in the clientSession function to lookup stocks, buy stocks, and query order successful order details
def lookupStock(session, stock_name):
    try:
        response = session.get(f"{FRONTEND_SERVICE_URL}/stocks/{stock_name}")
        if response.status_code == 200:
            data = response.json().get("data", {})
            logger.info(f"Lookup successful: {data}")
            return data
        else:
            error = response.json().get("error", {})
            logger.info(f"Lookup failed for {stock_name}: {error}")
            logger.info(f"Lookup failed: {error}")
            return None
    except requests.RequestException as e:
        logger.info(f"Error during stock lookup: {e}")
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
            logger.info(f"Order successful: Transaction Number = {transaction_number}")
            return transaction_number, order_data
        else:
            error = response.json().get("error", {})
            logger.info(f"Order failed: {error}")
            return None, None
    except requests.RequestException as e:
        logger.info(f"Error during order placement: {e}")
        return None, None

def queryOrderDetails(session, transaction_number):
    try:
        response = session.get(f"{FRONTEND_SERVICE_URL}/orders/{transaction_number}")
        if response.status_code == 200:
            data = response.json().get("data", {})
            logger.info(f"Order query successful: {data}")
            return data
        else:
            error = response.json().get("error", {})
            logger.info(f"Order query failed: {error}")
            return None
    except requests.RequestException as e:
        logger.info(f"Error during order query: {e}")
        return None

def measureLatency(func, *args, **kwargs):
    start = time.time()
    result = func(*args, **kwargs)
    end = time.time()
    return end - start, result

# Helper Function to measure the latency of each request which is sent to Catalog and Order services
def clientSession(probability_p, num_iterations):
    latencies = {"lookup": [], "order": [], "query": []}
    successful_order_details = []
    
    with requests.Session() as session:
        for _ in range(num_iterations):
            stock_name = random.choice(STOCKS)
            
            lookup_latency, stock_data = measureLatency(lookupStock, session, stock_name)
            latencies["lookup"].append(lookup_latency)
            
            if stock_data:
                if random.random() < probability_p:
                    trade_type = random.choice(["buy", "sell"])
                    quantity = random.randint(1, 20)
                    
                    order_latency, (trans_num, order_data) = measureLatency(
                        buyStock, session, stock_name, trade_type, quantity
                    )
                    latencies["order"].append(order_latency)
                    
                    if trans_num:
                        successful_order_details.append({"transaction_number": trans_num, "order_data": order_data})
            
            time.sleep(random.uniform(0.1, 0.3)) 
        for order in successful_order_details:
            query_latency, _ = measureLatency(
                queryOrderDetails, session, order["transaction_number"]
            )
            latencies["query"].append(query_latency)
    
    return latencies

# 5 Clients Sessions are simulated using the clientSession function with different probability 'p' values [0%, 20%, 40%, 60%, 80%]
def multipleClientSessions(probability_p, num_iterations, num_clients=5):
    all_latencies = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_clients) as executor:
        futures = [executor.submit(clientSession, probability_p, num_iterations)
                  for _ in range(num_clients)]
        for future in concurrent.futures.as_completed(futures):
            all_latencies.append(future.result())
    return all_latencies

# Reference: LAB 2 - Client Load Test File
if __name__ == "__main__":
    try:
        probability_values = [0.0, 0.2, 0.4, 0.6, 0.8]
        results = {}

        for p in probability_values:
            try:
                logger.info(f"Testing 'p' = {p}")
                results[p] = multipleClientSessions(p, NUM_ITERATIONS, NUM_CLIENTS)
            except Exception as e:
                logger.error(f"Error during multiple client sessions for 'p' = {p}: Error - {e}")
                results[p] = {"lookup": [], "order": [], "query": []}

        average_latencies = {"Lookup Latency": [], "Order Latency": [], "Order Query Latency": []}
        for p in probability_values:
            try:
                lookups = [lat for client in results[p] for lat in client["lookup"]]
                orders = [lat for client in results[p] for lat in client["order"]]
                queries = [lat for client in results[p] for lat in client["query"]]

                average_latencies["Lookup Latency"].append(np.mean(lookups) * 1000 if lookups else 0)
                average_latencies["Order Latency"].append(np.mean(orders) * 1000 if orders else 0)
                average_latencies["Order Query Latency"].append(np.mean(queries) * 1000 if queries else 0)
            except Exception as e:
                logger.error(f"Error while calculating average latencies for 'p' = {p}: Error - {e}")
                average_latencies["Lookup Latency"].append(0)
                average_latencies["Order Latency"].append(0)
                average_latencies["Order Query Latency"].append(0)

        percentage_labels = [f"{int(p * 100)}%" for p in probability_values]

        try:
            plt.figure(figsize=(10, 6))

            for req_type in average_latencies:
                y_vals = average_latencies[req_type]
                if any(y > 0 for y in y_vals):
                    plt.plot(percentage_labels, y_vals, marker='o', label=req_type)

            # To print plots - please change the value of CACHE_ENABLED to 1 or 0 in ClientDockerFile
            if CACHE_ENABLED == 1:
                plt.xlabel("Trade Probability (p)")
                plt.ylabel("Average Latency (Milliseconds)")
                plt.title(f"Request Latency vs Trade Probability - Number of Clients: {NUM_CLIENTS} - Requests per Client: {NUM_ITERATIONS} - Cache Enabled - Paxos")
                plt.legend()
                plt.grid(True)
                plt.tight_layout()
                plt.savefig("Load_test_paxos.png")
                plt.show()
            else:
                plt.xlabel("Trade Probability (p)")
                plt.ylabel("Average Latency (Milliseconds)")
                plt.title(f"Request Latency vs Trade Probability - Number of Clients: {NUM_CLIENTS} - Requests per Client: {NUM_ITERATIONS} - Cache Disabled - Paxos")
                plt.legend()
                plt.grid(True)
                plt.tight_layout()
                plt.savefig("Load_test_paxos.png")
                plt.show()
        except Exception as e:
            logger.error(f"Error while generating or saving the plot: {e}")

    except Exception as e:
        logger.critical(f"Unexpected error in the main block: {e}")
        print(f"An unexpected error occurred: {e}")
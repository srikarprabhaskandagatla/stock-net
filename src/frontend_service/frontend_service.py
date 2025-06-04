# Importing the Required Libraries
from flask import Flask, request
import requests, os, logging, threading
from collections import deque

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# LRU Cache Implementation to cache most used stocks, where the stocks are invalidated when catalog is updated using server-push technique
# Reference: https://www.geeksforgeeks.org/lru-cache-implementation/
class LRUCache:
    def __init__(self, capacity):
        self.cache = {}  
        self.access_order = deque()  
        self.capacity = capacity
        self.lock = threading.Lock() 

    def get(self, key):
        with self.lock: 
            if key in self.cache:
                self.access_order.remove(key)
                self.access_order.append(key)
                logger.info(f"Cache hit for key: {key}") 
                return self.cache[key]
            logger.info(f"Cache miss for key: {key}") 
            return None

    def put(self, key, value):
        with self.lock:
            if key in self.cache:
                self.cache[key] = value
                self.access_order.remove(key)
                self.access_order.append(key)
            else:
                if len(self.cache) >= self.capacity:
                    lru_key = self.access_order.popleft()
                    del self.cache[lru_key]
                    logger.info(f"Evicted {lru_key} from cache due to capacity limit.")
                self.cache[key] = value
                self.access_order.append(key)

    def invalidate(self, key):
        with self.lock: 
            if key in self.cache:
                del self.cache[key]
                self.access_order.remove(key)
                logger.info(f"Invalidated {key} from cache.")

# Reference: https://flask.palletsprojects.com/en/stable/quickstart/ 
app = Flask(__name__)

# Global Environment variables from Docker Compose file
CATALOG_SERVICE_URL = os.environ.get("CATALOG_SERVICE_URL", "http://catalog-service:8997")
ORDER_SERVICE_URLS = os.environ.get("ORDER_SERVICE_URLS", "http://order-service-3:9000").split(",")
FRONT_END_PORT = int(os.environ.get("FRONTEND_PORT", "9001"))
FRONTEND_HOST = os.environ.get("FRONTEND_HOST", "0.0.0.0")
CACHE_ENABLED = int(os.environ.get("CACHE_ENABLED","1"))
LEADER_URL = None
CACHE_SIZE = int(os.environ.get("CACHE_SIZE","5"))

logger.info(f"Initialized cache with size: {CACHE_SIZE}")

if CACHE_ENABLED == 1:
    cache = LRUCache(CACHE_SIZE)
else:
    logger.info("Set to No Cache")
    cache = None

# Helper functions - 3 Order Service Replicas are created and one of them is Elected as Leader, and the Leader is notified to all other replicas
def findLeader():
    global LEADER_URL
    logger.info("Selecting Leader")
    for url in sorted(ORDER_SERVICE_URLS, reverse=True):
        logger.info(f"Pinging Order Service Replica at {url}")
        try:
            response = requests.get(f"{url}/ping", timeout=5)
            if response.status_code == 200:
                LEADER_URL = url
                logger.info(f"Leader selected: {LEADER_URL}")
                notifyOrderServiceReplicas(LEADER_URL)
                return
        except requests.RequestException as e:
            logger.info(f"Order Service Replica at {url} is unresponsive. Skipped. Error: {e}")
    logger.error("No responsive replicas found. Cannot select a leader.")
    raise Exception("No responsive replicas found. Cannot select a leader.")

def notifyOrderServiceReplicas(leader_url):
    for url in ORDER_SERVICE_URLS:
        try:
            response = requests.post(f"{url}/set_leader", json={"leader_id": leader_url}, timeout=5)
            if response.status_code == 200:
                logger.info(f"Replica at {url} notified about the leader chosen: {leader_url}")
            else:
                logger.info(f"Failed to notify replica at {url}. Response: {response.status_code}")
        except requests.RequestException as e:
            logger.info(f"Skipping replica at {url} due to error: {e}")

def orderHandler(order_data, max_retries=3):
    global LEADER_URL
    if not LEADER_URL:
        findLeader()
    for attempt in range(max_retries):
        try:
            logger.info(f"Order happening on leader: {LEADER_URL}")
            response = requests.get(f"{LEADER_URL}/ping", timeout=5)
            if response.status_code != 200:
                raise requests.RequestException("Leader unresponsive")
            else:
                logger.info(f"Making the post call on {LEADER_URL}")
                response = requests.post(f"{LEADER_URL}/orders", json=order_data, timeout=5)
            return response.json(), response.status_code
        except requests.RequestException as e:
            logger.info(f"Re-Selecting the Leader as, Leader at {LEADER_URL} is unresponsive - {e}. Attempt Number: {attempt+1}")
            findLeader()
    logger.error(f"Leader unreachable after {max_retries} retries. Order could not be processed.")
    return {"error": {"code": 503, "message": "Leader unavailable after retries"}}, 503

def queryOrderHandler(order_number, max_retries=3): # Helper function to Query the successful orders
    global LEADER_URL
    if not LEADER_URL:
        findLeader()
    for attempt in range(max_retries):
        try:
            response = requests.get(f"{LEADER_URL}/ping", timeout=5)
            if response.status_code != 200:
                raise requests.RequestException("Leader unresponsive")
            response = requests.get(f"{LEADER_URL}/orders/{order_number}", timeout=5)
            return response.json(), response.status_code
        except requests.RequestException as e:
            logger.info(f"Leader {LEADER_URL} is unresponsive. Re-selecting leader... Attempt {attempt+1}")
            findLeader()
    logger.error(f"Leader reachable after {max_retries} retries. Query could not be processed.")
    return {"error": {"code": 503, "message": f"Leader unavailable after {max_retries} retries"}}, 503

# API Endpoints - Lookup, Order and Query Orders use the helper functions to connect to Catalog and Order Services to process the order requests
@app.route('/stocks/<stock_name>', methods=['GET'])
def lookup(stock_name):
    if CACHE_ENABLED == 1:
        logger.info("Cache enabled lookup")
        cached_data = cache.get(stock_name)
    else:
        logger.info("No Cache enabled lookup")
        cached_data = None
    if cached_data:
        logger.info(f"Cache hit: {stock_name}")
        return {
            "message": "Lookup successful",
            "data": cached_data
        }, 200

    try:
        response = requests.get(f"{CATALOG_SERVICE_URL}/stocks/{stock_name}")
        if response.status_code == 200:
            data = response.json()
            if CACHE_ENABLED == 1:
                cache.put(stock_name, data)
                logger.info(f"Cache miss: {stock_name}. Adding to cache.")
            return {
                "message": "Lookup successful",
                "data": data
            }, 200
        else:
            return response.json(), response.status_code
    except requests.RequestException as e:
        return {"error": str(e)}, 500

@app.route('/invalidate/<stock_name>', methods=['POST'])
def invalidate(stock_name):
    cache.invalidate(stock_name)
    logger.info(f"Cache invalidated: {stock_name}")
    return {"message": f"Cache invalidated: {stock_name}"}, 200

@app.route('/orders', methods=['POST'])
def order():
    order_data = request.get_json()
    response, status_code = orderHandler(order_data)
    if status_code == 200:
        data = response.get("data", {})
        transaction_number = data.get("transaction_number")
        if transaction_number is not None:
            return {"data": {"transaction_number": transaction_number}}, 200
        else:
            return {"error": {"code": 500, "message": "Transaction number missing in response"}}, 500
    else:
        return {"error": {"code": status_code, "message": response.get("error", "An error occurred")}}, status_code

@app.route('/orders/<int:order_number>', methods=['GET'])
def getOrder(order_number):
    response, status_code = queryOrderHandler(order_number)
    if status_code == 200:
        data = response.get("data", {})
        return {
            "data": {
                "number": data.get("transaction_number"),
                "name": data.get("stock_name"),
                "type": data.get("type"),
                "quantity": data.get("quantity")
            }
        }, 200
    else:
        return {"error": {"code": status_code, "message": response.get("error", "An error occurred")}}, status_code

# Reference: https://stackoverflow.com/questions/38876721/handle-flask-requests-concurrently-with-threaded-true
if __name__ == "__main__":
    try:
        findLeader()
    except Exception as e:
        logger.error(f"Error during leader selection: {e}")
        exit(1)

    try:
        app.run(host=FRONTEND_HOST, port=FRONT_END_PORT, threaded=True)
    except Exception as e:
        logger.error(f"Error while starting the Flask server: {e}")
        exit(1)
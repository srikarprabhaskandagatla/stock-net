# Importing the Required Libraries
from flask import Flask, request, jsonify
import requests, csv, os, threading, logging
from threading import Thread

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Reference: https://www.geeksforgeeks.org/lru-cache-implementation/
app = Flask(__name__)

# Global Environment variables from Docker Compose file
REPLICA_ID = int(os.environ.get("REPLICA_ID", 1))
ORDER_PORT = int(os.environ.get("ORDER_PORT", 8997 + REPLICA_ID))
ORDER_HOST = os.environ.get("ORDER_HOST", "0.0.0.0")
CATALOG_SERVICE_URL = os.environ.get("CATALOG_SERVICE_URL", "http://catalog-service:8997")
TOTAL_REPLICAS = int(os.environ.get("TOTAL_REPLICAS", 3))

# Global Environment variables for the Order Service
transactionNumber = 0
ordersList = []
leaderRecoveryCompleted = False
transaction_lock = threading.Lock()
orders_list_lock = threading.Lock()
order_log_lock = threading.Lock()
leader_recovery_lock = threading.Lock()
ORDER_LOG_FILE = f"order_log_{REPLICA_ID}.csv"
SELF_URL = f"http://order-service-{REPLICA_ID}:{ORDER_PORT}"
LEADER_ID = None

# Helper Functions to manage the order log and synchronization which is used in the API endpoints to process the order requests from frontend service
# This includes the order log initialization, loading orders to memory and disk, and appending missing orders from other replicas
def getAllReplicas():
    return [f"http://order-service-{i}:{8997 + i}" for i in range(1, TOTAL_REPLICAS + 1)]

# Reference: https://docs.python.org/3/library/csv.html
def loadOrderToDisk(orderData):
    with order_log_lock:
        try:
            if not all(k in orderData for k in ["transaction_number", "stock_name", "type", "quantity"]):
                logger.error(f"Replica {REPLICA_ID}: Invalid order data provided for disk write: {orderData}")
                return
            with open(ORDER_LOG_FILE, mode="a", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=["transaction_number", "stock_name", "type", "quantity"])
                if not os.path.exists(ORDER_LOG_FILE) or os.path.getsize(ORDER_LOG_FILE) == 0:
                    writer.writeheader()
                    logger.info(f"Replica {REPLICA_ID}: Wrote header to new/empty log file {ORDER_LOG_FILE}")
                writer.writerow({
                    "transaction_number": orderData["transaction_number"],
                    "stock_name": orderData["stock_name"],
                    "type": orderData["type"],
                    "quantity": orderData["quantity"]
                })
        except IOError as e:
            logger.error(f"Replica {REPLICA_ID}: Failed to persist order {orderData.get('transaction_number')} to log: {e}")
        except Exception as e:
            logger.error(f"Replica {REPLICA_ID}: Unexpected error persisting order {orderData.get('transaction_number')}: {e}")

def loadOrderToMemory(orderData):
    if not all(k in orderData for k in ["transaction_number", "stock_name", "type", "quantity"]):
        logger.warning(f"Replica {REPLICA_ID}: Attempted to add invalid order data to memory: {orderData}")
        return False
    if any(order["transaction_number"] == orderData["transaction_number"] for order in ordersList):
        logger.info(f"Replica {REPLICA_ID}: Order {orderData['transaction_number']} already in memory. Skipping add.")
        return False
    ordersList.append(orderData)
    return True

def appendMissingOrders(maxtransactionNum):
    ordersFetched = []
    for url in getAllReplicas():
        if url == SELF_URL:
            continue
        try:
            response = requests.get(f"{url}/get_missing_orders/{maxtransactionNum}", timeout = 5)
            if response.status_code == 200:
                orders = response.json().get("data", [])
                logger.info(f"Replica {REPLICA_ID}: Received {len(orders)} orders from {url}")
                validOrders = [
                    order for order in orders if
                    isinstance(order.get("transaction_number"), int) and
                    isinstance(order.get("stock_name"), str) and
                    order.get("type") in ["buy", "sell"] and
                    isinstance(order.get("quantity"), int) and
                    order.get("quantity") > 0
                ]
                # Append the fetched missing orders
                ordersFetched.extend(validOrders)
                if len(validOrders) != len(orders):
                    logger.info(f"Replica {REPLICA_ID}: Filtered out {len(orders) - len(validOrders)} invalid orders from {url}")
            else:
                logger.warning(f"Replica {REPLICA_ID}: Failed to get missing orders from {url}, status: {response.status_code}, Response: {response.text[:200]}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Replica {REPLICA_ID}: Could not connect to {url} for missing orders: {e}")
        except Exception as e:
            logger.error(f"Replica {REPLICA_ID}: Error processing response from {url} for missing orders: {e}")
    count = 0
    if ordersFetched:
        ordersWithTxnNum = {order['transaction_number']: order for order in ordersFetched}.values()
        sortedOrders = sorted(list(ordersWithTxnNum), key=lambda x: x['transaction_number'])
        logger.info(f"Replica {REPLICA_ID} fetched {sortedOrders} orders.")
        with orders_list_lock:
            existingTransactionNums = {order["transaction_number"] for order in ordersList}
            ordersAdded = set()
            for order in sortedOrders:
                transaction = order["transaction_number"]
                if transaction > maxtransactionNum and transaction not in existingTransactionNums and transaction not in ordersAdded:
                    loadOrderToDisk(order)
                    if loadOrderToMemory(order):
                        ordersAdded.add(transaction)
                        count += 1
                elif transaction <= maxtransactionNum:
                    logger.info(f"Replica {REPLICA_ID}: Skipping fetched order {transaction} as it's not > own_max {maxtransactionNum}")
                elif transaction in existingTransactionNums or transaction in ordersAdded:
                    logger.info(f"Replica {REPLICA_ID}: Skipping fetched order {transaction} as it already exists.")
    logger.info(f"Replica {REPLICA_ID}: Finished applying fetched orders. Added {count} new orders.")
    return count

def orderLogInit():
    global ordersList
    logger.info(f"Replica {REPLICA_ID}: Initializing order log from {ORDER_LOG_FILE}.")
    maxTransactionNum = -1
    tempOrdersList = []
    try:
        if not os.path.exists(ORDER_LOG_FILE):
            loadOrderToDisk({})
    except Exception as e:
        logger.error(f"Replica {REPLICA_ID}: Could not ensure order log file {ORDER_LOG_FILE} exists: {e}")
    try:
        if os.path.exists(ORDER_LOG_FILE):
            with open(ORDER_LOG_FILE, mode="r", newline="") as file:
                reader = csv.DictReader(file)
                if "transaction_number" not in reader.fieldnames:
                    logger.error(f"Replica {REPLICA_ID}: Log file {ORDER_LOG_FILE} missing 'transaction_number' header.")
                    reader = []
                rowsProcessed = 0
                for row in reader:
                    rowsProcessed += 1
                    try:
                        transactionNum = int(row.get("transaction_number"))
                        stockName = row.get("stock_name")
                        tradeType = row.get("type")
                        quantity = row.get("quantity") if row.get("quantity") is not None else 0
                        if stockName and tradeType in ["buy", "sell"] and quantity > 0:
                            maxTransactionNum = max(maxTransactionNum, transactionNum)
                            tempOrdersList.append({
                                "transaction_number": transactionNum,
                                "stock_name": stockName,
                                "type": tradeType,
                                "quantity": quantity
                            })
                        else:
                            logger.warning(f"Replica {REPLICA_ID}: Skipping row with invalid data in log: {row}")
                    except (ValueError, TypeError, KeyError) as e:
                        logger.warning(f"Replica {REPLICA_ID}: Skipping row with parsing error (txn='{row.get('transaction_number')}', qty='{row.get('quantity')}'): {row} - Error: {e}")
                        continue
                logger.info(f"Replica {REPLICA_ID}: Read {rowsProcessed} rows from log. Max local transaction found: {maxTransactionNum}")
        else:
            logger.warning(f"Replica {REPLICA_ID}: Order log file {ORDER_LOG_FILE} not found. Starting with empty state.")
            maxTransactionNum = -1
    except Exception as e:
        logger.error(f"Replica {REPLICA_ID}: Failed to read order log file {ORDER_LOG_FILE}: {e}")
        maxTransactionNum = -1
    with orders_list_lock:
        ordersList = sorted(tempOrdersList, key=lambda x: x['transaction_number'])
    logger.info(f"Replica {REPLICA_ID}: Initialization complete. {len(ordersList)} orders loaded into memory.")
    return maxTransactionNum

def syncOnInit(maxTransactionNum):
    appendMissingOrders(maxTransactionNum)
    logger.info(f"Synchronization finished on {REPLICA_ID}")

def recoverStateForLeader():
    global transactionNumber
    logger.info(f"Replica {REPLICA_ID}: Starting state recovery as new leader.")
    maxTransactionNum = -1
    with orders_list_lock:
        if ordersList:
            maxTransactionNum = max((order.get("transaction_number", -1) for order in ordersList), default=-1)
    logger.info(f"Replica {REPLICA_ID}: Own max transaction number (from memory) is {maxTransactionNum}.")
    otherMaxTransaction = -1
    allReplicas = getAllReplicas()
    for url in allReplicas:
        if url == SELF_URL:
            continue
        try:
            logger.info(f"Replica {REPLICA_ID}: Querying max transaction from {url}...")
            resp = requests.get(f"{url}/max_transaction", timeout = 2)
            if resp.status_code == 200:
                replicaMaxTransaction = resp.json().get("max_transaction", -1)
                if isinstance(replicaMaxTransaction, int):
                    logger.info(f"Replica {REPLICA_ID}: Received max_transaction {replicaMaxTransaction} from {url}")
                    otherMaxTransaction = max(otherMaxTransaction, replicaMaxTransaction)
                else:
                    logger.warning(f"Replica {REPLICA_ID}: Invalid max_transaction format received from {url}: {resp.json()}")
            else:
                logger.warning(f"Replica {REPLICA_ID}: Failed to get max_transaction from {url}, status: {resp.status_code}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"Replica {REPLICA_ID}: Could not connect to {url} for max_transaction: {e}")
        except Exception as e:
            logger.error(f"Replica {REPLICA_ID}: Error processing response from {url} for max_transaction: {e}")
    seenMaxTransaction = max(maxTransactionNum, otherMaxTransaction)
    with transaction_lock:
        transactionNumber = max(transactionNumber, seenMaxTransaction + 1)
        logger.info(f"Replica {REPLICA_ID}: Global max seen: {seenMaxTransaction}. Original local counter: {transactionNumber}. Updated transaction_number counter to: {transactionNumber}")
    appendMissingOrders(maxTransactionNum)
    logger.info(f"Replica {REPLICA_ID}: State recovery finished.")

def sendToFollowers(orderData):
    followers = [url for url in getAllReplicas() if url != SELF_URL]
    if not followers:
        logger.info(f"Replica {REPLICA_ID} (Leader): No followers to send order {orderData.get('transaction_number')} to.")
        return
    transactionNum = orderData.get('transaction_number')
    logger.info(f"Replica {REPLICA_ID} (Leader): Propagating order {transactionNum} to followers: {followers}")
    for follower in followers:
        try:
            response = requests.post(f"{follower}/replicate_order", json=orderData)
            if response.status_code == 200:
                logger.info(f"Replica {REPLICA_ID} (Leader): Order {transactionNum} successfully sent to {follower}")
            elif response.status_code == 409:
                logger.info(f"Replica {REPLICA_ID} (Leader): Follower {follower} rejected replication (Status 409), possibly thinks it's leader.")
            else:
                logger.warning(f"Replica {REPLICA_ID} (Leader): Failed to send order {transactionNum} to {follower}. Status: {response.status_code}, Response: {response.text[:200]}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Replica {REPLICA_ID} (Leader): Error sending order {transactionNum} to {follower}: {e}")

# API Endpoints - Using the helper functions to process the order requests from frontend service
@app.route("/ping", methods=["GET"]) # '/ping' from frontend service which is used when electing leader and check the server running condition
def checkHealth():
    return jsonify({"status": "healthy", "replica_id": REPLICA_ID, "leader_id": LEADER_ID}), 200

@app.route("/set_leader", methods=["POST"])
def setLeader():
    global LEADER_ID, leaderRecoveryCompleted
    leaderId = request.get_json().get("leader_id")
    if not leaderId:
        return jsonify({"error": "Missing leader id."}), 400
    logger.info(f"Replica {REPLICA_ID}: Received leader notification. New leader: {leaderId}")
    previousLeader = LEADER_ID
    LEADER_ID = leaderId
    if LEADER_ID == SELF_URL and previousLeader != SELF_URL:
        logger.info(f"Replica {REPLICA_ID}: Set as leader.")
        
        with leader_recovery_lock: # Acquire lock to recover the state if leader
            leaderRecoveryCompleted = False
            logger.info(f"Replica {REPLICA_ID}: Leader recovery process started.")
            try:
                recoverStateForLeader()
                leaderRecoveryCompleted = True
                logger.info(f"Replica {REPLICA_ID}: Leader recovery process completed successfully.")
            except Exception as e:
                logger.info(f"Replica {REPLICA_ID}: ERROR during leader recovery: {e}")
                leaderRecoveryCompleted = False
    elif LEADER_ID != SELF_URL and previousLeader == SELF_URL:
        logger.info(f"Replica {REPLICA_ID}: Set as follower. Leader is {LEADER_ID}")
        with leader_recovery_lock:
            leaderRecoveryCompleted = False
    elif LEADER_ID == SELF_URL and previousLeader == SELF_URL:
        logger.info(f"Replica {REPLICA_ID}: Received redundant leader notification for self.")
        pass
    else:
        logger.info(f"Replica {REPLICA_ID}: Set as follower. Leader is {LEADER_ID}")
        with leader_recovery_lock:
            leaderRecoveryCompleted = False
    return jsonify({"message": f"Replica {REPLICA_ID}: Leader set to {LEADER_ID}"}), 200

@app.route("/orders", methods=["POST"])
def processOrder(): # Place Order API endpoint
    global transactionNumber
    
    if LEADER_ID != SELF_URL:
        return jsonify({"error": {"code": 403, "message": "This replica is not the leader"}}), 403
    with leader_recovery_lock:
        if not leaderRecoveryCompleted:
            return jsonify({"error": {"code": 503, "message": "Service Unavailable: Leader initializing"}}), 503
    orderData = request.get_json()
    stockName = orderData.get("stock_name")
    tradeType = orderData.get("type")
    quantity = orderData.get("quantity")
    if not stockName or tradeType not in ["buy", "sell"] or not isinstance(quantity, int):
        logger.info(f"Replica {REPLICA_ID}: Invalid order request data: {orderData}")
        return jsonify({"error": {"code": 400, "message": "Invalid request data (stockName, tradeType=buy/sell, quantity not int)"}}), 400
    try:
        # Get call to catalog to retrieve the stock
        getResponse = requests.get(f"{CATALOG_SERVICE_URL}/stocks/{stockName}", timeout = 5)
        getResponse.raise_for_status()
        currentQuantity = getResponse.json().get("quantity")
        if tradeType == "buy" and quantity > currentQuantity:
            return jsonify({"error": {"code": 400, "message": f"Insufficient stock for {stockName}. Available: {currentQuantity}, Requested: {quantity}"}}), 400
        # Post call to catalog to update the stock
        postResponse = requests.post(f"{CATALOG_SERVICE_URL}/stocks/{stockName}", json={"type": tradeType, "quantity": quantity}, timeout = 5)
        postResponse.raise_for_status()
        with transaction_lock:
            currentTransactionNum = transactionNumber
            transactionNumber += 1
        orderToBeSaved = {
            "transaction_number": currentTransactionNum,
            "stock_name": stockName,
            "type": tradeType,
            "quantity": quantity
        }
        loadOrderToDisk(orderToBeSaved)
        with orders_list_lock:
            loadOrderToMemory(orderToBeSaved)
        Thread(target=sendToFollowers, args=(orderToBeSaved,)).start()
        return jsonify({"data": {"transaction_number": currentTransactionNum}}), 200
    except requests.exceptions.RequestException as e:
        error_payload = {"code": 500, "message": f"Catalog service error: {str(e)}"}
        try:
            if e.response is not None:
                error_payload = e.response.json().get("error", error_payload)
        except:
            pass
        status_code = e.response.status_code if hasattr(e, 'response') and e.response else 500
        return jsonify({"error": error_payload}), status_code
    except Exception as e:
        return jsonify({"error": {"code": 500, "message": f"Internal server error during order processing"}}), 500

@app.route("/replicate_order", methods=["POST"]) # After Leader processes the order, it replicates to all the followers Order Services
def replicateOrderToFollowers():
    if LEADER_ID == SELF_URL:
        logger.warning(f"Replica {REPLICA_ID}: Received replicate_order for leader. Sending 409 error.")
        return jsonify({"message": "Ignoring replication request as current leader"}), 409
    orderData = request.get_json()
    transactionNum = orderData.get("transaction_number")
    stockName = orderData.get("stock_name")
    tradeType = orderData.get("type")
    quantity = orderData.get("quantity")
    if not (isinstance(transactionNum, int) and transactionNum >= 0 and isinstance(stockName, str) and stockName and
            tradeType in ["buy", "sell"] and isinstance(quantity, int) and quantity > 0):
        logger.info(f"Replica {REPLICA_ID} (Follower): Received invalid replication request data: {orderData}")
        return jsonify({"error": "Invalid replication data"}), 400
    logger.info(f"Replica {REPLICA_ID} (Follower): Received replication request for order {transactionNum}.")
    with orders_list_lock:
        if any(order["transaction_number"] == transactionNum for order in ordersList):
            logger.info(f"Replica {REPLICA_ID} (Follower): Order {transactionNum} already exists. Ignoring duplicate replication.")
            return jsonify({"message": "Order already replicated"}), 200
        # Pass on to store the order details in the log for all the replicas
        loadOrderToDisk(orderData)
        loadOrderToMemory(orderData)
    logger.info(f"Replica {REPLICA_ID} (Follower): Successfully replicated order {transactionNum}.")
    return jsonify({"message": "Order replicated successfully"}), 200

# Query Order API endpoint which is used to query the order details using the transaction number,
# when client wants to check the server reply matches the locally stored order information
@app.route("/orders/<int:transactionNumToQuery>", methods=["GET"])
def getOrder(transactionNumToQuery): 
    foundOrder = None
    try:
        with order_log_lock:
            
            with open(ORDER_LOG_FILE, mode="r", newline="") as file: # Read from the order log file
                reader = csv.DictReader(file)
                for row in reader:
                    try:
                        transactionNum = int(row.get("transaction_number", -1))
                        if transactionNum == transactionNumToQuery:
                            foundOrder = {
                                "transaction_number": transactionNum,
                                "stock_name": row.get("stock_name"),
                                "type": row.get("type"),
                                "quantity": int(row.get("quantity", 0))
                            }
                            break
                    except (ValueError, KeyError) as e:
                        logger.info(f"Replica {REPLICA_ID}: Error parsing row in CSV: {e}")
                        continue
    except FileNotFoundError:
        logger.error(f"Replica {REPLICA_ID}: Order log file not found.")
        return jsonify({"error": {"code": 404, "message": "Order log not available"}}), 404
    except Exception as e:
        logger.error(f"Replica {REPLICA_ID}: Error accessing order log: {e}")
        return jsonify({"error": {"code": 500, "message": "Internal server error"}}), 500
    if foundOrder:
        return jsonify({"data": foundOrder}), 200
    else:
        logger.error(f"Replica {REPLICA_ID}: Order {transactionNumToQuery} not found in log.")
        return jsonify({"error": {"code": 404, "message": "Order not found"}}), 404

@app.route("/get_missing_orders/<int:lastOrderNum>", methods=["GET"])
def getMissingOrders(lastOrderNum):
    logger.info(f"Replica {REPLICA_ID}: Received request for orders after {lastOrderNum}.")
    with orders_list_lock:
        missingOrders = [
            order for order in ordersList
            if order.get("transaction_number", -1) > lastOrderNum
        ]
    missingOrders.sort(key=lambda x: x['transaction_number'])
    logger.info(f"Replica {REPLICA_ID}: Found {len(missingOrders)} orders after {lastOrderNum}.")
    return jsonify({"data": missingOrders}), 200

@app.route("/max_transaction", methods=["GET"])
def getMaximumTransaction():
    maxTransactionInMemory = -1
    with orders_list_lock:
        if ordersList:
            maxTransactionInMemory = max((order.get("transaction_number", -1) for order in ordersList), default=-1)
    return jsonify({"max_transaction": maxTransactionInMemory}), 200

# Reference: LAB 2 - Basic Order Service Implementation
if __name__ == "__main__":
    try:
        max_transaction_num = orderLogInit()
        syncOnInit(max_transaction_num)
        logger.info(f"Replica {REPLICA_ID}: Order log initialized and synchronization completed.")
    except Exception as e:
        logger.error(f"Replica {REPLICA_ID}: Error during initialization or synchronization: {e}")
        exit(1)

    try:
        logger.info(f"Replica {REPLICA_ID}: Server starting on {ORDER_HOST}:{ORDER_PORT}.")
        app.run(host=ORDER_HOST, port=ORDER_PORT, threaded=True)
    except Exception as e:
        logger.error(f"Replica {REPLICA_ID}: Error while starting the Flask server: {e}")
        exit(1)
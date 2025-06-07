# Importint the Required libraries
from flask import Flask, request, jsonify
import requests, logging, csv, os, threading, time
from threading import Thread

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Reference: https://www.geeksforgeeks.org/lru-cache-implementation/
app = Flask(__name__)

# Global Environment variables from Docker Compose file
REPLICA_ID = int(os.environ.get("REPLICA_ID", 1))
ORDER_PORT = int(os.environ.get("ORDER_PORT", 8998 + REPLICA_ID))
ORDER_HOST = os.environ.get("ORDER_HOST", "0.0.0.0")
CATALOG_SERVICE_URL = os.environ.get("CATALOG_SERVICE_URL", "http://catalog-service:8997")
TOTAL_REPLICAS = int(os.environ.get("TOTAL_REPLICAS", 3))

# Global Environment variables for the Order Service
leaderRecoveryCompleted = False
transaction_lock = threading.Lock()
orders_list_lock = threading.Lock()
order_log_lock = threading.Lock()
proposal_lock = threading.Lock()
ordersList = []
transactionNumber = 0
promisedId = 0
acceptedId = 0
acceptedValue = None
ORDER_LOG_FILE = f"order_log_{REPLICA_ID}.csv"
SELF_URL = f"http://order-service-paxos-{REPLICA_ID}:{ORDER_PORT}"
LEADER_ID = None

# Helper Functions to manage the order log and synchronization which is used in the API endpoints to process the order requests from frontend service
# This includes the order log initialization, loading orders to memory and disk, and appending missing orders from other replicas
def getAllReplicas():
    return [f"http://order-service-paxos-{i}:{8997 + i}" for i in range(1, TOTAL_REPLICAS + 1)]

def loadOrderToDisk(order):
    with order_log_lock:
        try:
            if not all(k in order for k in ["transaction_number", "stock_name", "type", "quantity"]):
                logger.error(f"Replica {REPLICA_ID}: Invalid order data provided for disk write: {order}")
                return
            with open(ORDER_LOG_FILE, "a", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["transaction_number","stock_name","type","quantity"])
                if not os.path.exists(ORDER_LOG_FILE) or os.path.getsize(ORDER_LOG_FILE) == 0:
                    w.writeheader()
                w.writerow(order)
        except Exception as e:
            logger.error(f"Log write failed: {e}")

# Reference: https://docs.python.org/3/library/csv.html
def loadOrderToMemory(order):
    with orders_list_lock:
        if any(orderData["transaction_number"] == order["transaction_number"] for orderData in ordersList):
            return False
        ordersList.append(order)
    return True

def appendMissingOrders(maxTransaction):
    fetchedOrders = []
    for url in getAllReplicas():
        if url == SELF_URL: continue
        try:
            response = requests.get(f"{url}/get_missing_orders/{maxTransaction}", timeout = 5)
            if response.status_code == 200:
                # Appending missing orders
                fetchedOrders.extend(response.json().get("data", []))
        except Exception:
            logger.warning(f"Couldn’t fetch missing from {url}")
    for transaction in sorted({order["transaction_number"] for order in fetchedOrders}):
        order = next(order for order in fetchedOrders if order["transaction_number"] == transaction)
        if transaction > maxTransaction:
            loadOrderToDisk(order)
            loadOrderToMemory(order)

def orderLogInit():
    global ordersList
    tempTransaction, maxTransactionNum = [], -1
    if os.path.exists(ORDER_LOG_FILE):
        with open(ORDER_LOG_FILE, newline="") as f:
            for row in csv.DictReader(f):
                try:
                    transactionNum = int(row["transaction_number"])
                    tempTransaction.append({
                        "transaction_number": transactionNum,
                        "stock_name": row["stock_name"],
                        "type": row["type"],
                        "quantity": int(row["quantity"])
                    })
                    maxTransactionNum = max(maxTransactionNum, transactionNum)
                except:
                    pass
    with orders_list_lock:
        ordersList = sorted(tempTransaction, key=lambda x: x["transaction_number"])
    logger.info(f"Startup loaded {len(ordersList)} orders (max transaction number={maxTransactionNum})")
    return maxTransactionNum

def syncOnInit(localTransactionNum):
    logger.info(f"Replica {REPLICA_ID}: Syncing missing orders after transaction {localTransactionNum}")
    try:
        appendMissingOrders(localTransactionNum)
    except Exception as e:
        logger.error(f"Replica {REPLICA_ID}: Error during synchronization: {e}")

def recover():
    try:
        global transactionNumber, leaderRecoveryCompleted
        with orders_list_lock:
            maxTransactionNum = max((order["transaction_number"] for order in ordersList), default=-1)
        currentMaxTransaction = maxTransactionNum
        for url in getAllReplicas():
            if url == SELF_URL: continue
            try:
                response = requests.get(f"{url}/max_transaction", timeout = 2)
                if response.status_code==200:
                    currentMaxTransaction = max(currentMaxTransaction, response.json().get("max_transaction", -1))
            except:
                logger.warning(f"Couldn't get max transaction from {url}")
        with transaction_lock:
            transactionNumber = max(transactionNumber, currentMaxTransaction+1)
        appendMissingOrders(maxTransactionNum)
        logger.info(f"Background recovery complete. Next transaction={transactionNumber}")
    except Exception as e:
        logger.error(f"Recovery thread failed: {e}")
    finally:
        leaderRecoveryCompleted = True

# API Endpoints - Using the helper functions to process the order requests from frontend service
# and to manage the Paxos consensus algorithm for leader election and order replication
# Reference: https://flask.palletsprojects.com/en/2.0.x/quickstart/#routing

# Paxos Consensus algorithm Understanding - Reference: https://www.the-paper-trail.org/post/2009-02-09-consensus-protocols-a-paxos-implementation/
# Implementation Reference: https://github.com/pyeventsourcing/example-paxos
@app.route("/paxos/prepare", methods=["POST"])
def paxosPrepare():
    global promisedId
    pid = request.json.get("proposal_number")
    if not isinstance(pid, int):
            logger.warning(f"Replica {REPLICA_ID}: Invalid proposal number received: {pid}")
            return jsonify(error={"code": 400, "message": "Invalid proposal number"}), 400
    with proposal_lock:
        if pid > promisedId:
            promisedId = pid
            return jsonify(promise=True, acceptedId=acceptedId, acceptedValue=acceptedValue)
        return jsonify(promise=False, promisedId=promisedId)

@app.route("/paxos/accept", methods=["POST"])
def paxosAccept():
    global promisedId, acceptedId, acceptedValue
    pid = request.json.get("proposal_number")
    with proposal_lock:
        if pid >= promisedId:
            promisedId = pid
            acceptedId = pid
            acceptedValue = request.json.get("value")
            return jsonify(accepted=True)
        return jsonify(accepted=False, promisedId=promisedId)

@app.route("/ping", methods=["GET"])
def healthCheck():
    return jsonify(
        status="healthy",
        replica_id=REPLICA_ID,
        leader_id=LEADER_ID,
        recovery_done=leaderRecoveryCompleted
    )

@app.route("/set_leader", methods=["POST"])
def setLeader():
    global LEADER_ID, leaderRecoveryCompleted
    data = request.get_json()
    leader_id = data.get("leader_id") if data else None
    if not leader_id:
        return jsonify(error={"code": 400, "message": "Missing leader_id"}), 400
    prevLeader = LEADER_ID
    LEADER_ID = leader_id
    logger.info(f"Leader changed from {prevLeader} ➔ {LEADER_ID}")
    leaderRecoveryCompleted = False
    if LEADER_ID == SELF_URL and prevLeader != SELF_URL:
        Thread(target=recover, daemon=True).start()
    else:
        leaderRecoveryCompleted = True
    return jsonify(message=f"Leader set to {LEADER_ID}")

@app.route("/orders", methods=["POST"])
def processOrder():
    global transactionNumber
    if LEADER_ID != SELF_URL:
        return jsonify(error={"code":403,"message":"Not leader"}), 403
    orderData = request.json or {}
    stockName, tradeType, quantity = orderData.get("stock_name"), orderData.get("type"), orderData.get("quantity")
    if not stockName or tradeType not in ("buy","sell") or not isinstance(quantity,int) or quantity <= 0:
        return jsonify(error={"code":400,"message":"Invalid data"}),400
    try:
        getResponse = requests.get(f"{CATALOG_SERVICE_URL}/stocks/{stockName}", timeout = 5)
        getResponse.raise_for_status()
        if tradeType=="buy" and quantity > getResponse.json().get("quantity",0):
            return jsonify(error={"code":400,"message":"Insufficient stock"}),400
        postResponse = requests.post(
            f"{CATALOG_SERVICE_URL}/stocks/{stockName}",
            json={"type":tradeType,"quantity":quantity},
            timeout = 5
        )
        postResponse.raise_for_status()
    except Exception as e:
        logger.error(f"Catalog error: {e}")
        return jsonify(error={"code":500,"message":str(e)}),500
    pid = (int(time.time()*1000)<<16)|REPLICA_ID
    majorityAcceptors = TOTAL_REPLICAS//2+1
    # Preparing to send paxos consensus request to replicas
    promises = 1
    for url in getAllReplicas():
        if url==SELF_URL: continue
        try:
            response = requests.post(f"{url}/paxos/prepare",json={"proposal_number":pid}, timeout = 2)
            if response.ok and response.json().get("promise"):
                promises+=1
        except: pass
    if promises < majorityAcceptors:
        return jsonify(error={"code":500,"message":"Failed promises"}),500
    # Checking if the majority acceptors are replying
    accepts = 1
    for url in getAllReplicas():
        if url==SELF_URL: continue
        try:
            response = requests.post(f"{url}/paxos/accept", json={"proposal_number":pid,"value":orderData}, timeout = 2)
            if response.ok and response.json().get("accepted"):
                accepts+=1
        except: pass
    if accepts < majorityAcceptors:
        return jsonify(error={"code":500,"message":"Failed accepts"}),500
    with transaction_lock:
        transactionNum = transactionNumber
        transactionNumber += 1
    order = {
        "transaction_number": transactionNum,
        "stock_name": stockName,
        "type": tradeType,
        "quantity": quantity
    }
    # Load the data to log file and memory
    loadOrderToDisk(order)
    loadOrderToMemory(order)

    def replicate(orderToBeReplicated):
        for url in getAllReplicas():
            if url==SELF_URL: continue
            try: requests.post(f"{url}/replicate_order",json=orderToBeReplicated, timeout = 2)
            except: pass
    Thread(target=replicate,args=(order,),daemon=True).start()
    
    return jsonify(data={"transaction_number":transactionNum})

@app.route("/replicate_order", methods=["POST"])
def replicateOrder():
    replicatedOrder = request.json or {}
    transactionNum = replicatedOrder.get("transaction_number")
    if not all(k in replicatedOrder for k in ["transaction_number", "stock_name", "type", "quantity"]):
        logger.warning(f"Replica {REPLICA_ID}: Invalid replicated order data: {replicatedOrder}")
        return jsonify(error={"code": 400, "message": "Invalid replicated order data"}), 400
    if LEADER_ID == SELF_URL:
        return jsonify(error={"code": 409, "message": "Cannot replicate order to self (leader)"}), 409
    if isinstance(transactionNum,int) and loadOrderToMemory(replicatedOrder):
        loadOrderToDisk(replicatedOrder)
    return jsonify(message="Replicated")

@app.route("/orders/<int:transactionNum>", methods=["GET"])
def getOrder(transactionNum):
    try:
        with orders_list_lock:
            order = next((o for o in ordersList if o["transaction_number"] == transactionNum), None)
        if order:
            return jsonify({"data": order}), 200
        return jsonify({"error": {"code": 404, "message": "Order not found"}}), 404
    except Exception as e:
        logger.error(f"Replica {REPLICA_ID}: Error while fetching order {transactionNum}: {e}")
        return jsonify({"error": {"code": 500, "message": "Internal server error"}}), 500

@app.route("/get_missing_orders/<int:lastTransactionNum>", methods=["GET"])
def getMissingOrders(lastTransactionNum):
    with orders_list_lock:
        missingOrder = [o for o in ordersList if o["transaction_number"] > lastTransactionNum]
    return jsonify(data=missingOrder)

@app.route("/max_transaction", methods=["GET"])
def maxTransaction():
    try:
        with orders_list_lock:
            maxTransactionNum = max((order["transaction_number"] for order in ordersList), default=-1)
        return jsonify(max_transaction=maxTransactionNum)
    except Exception as e:
        logger.error(f"Replica {REPLICA_ID}: Error while calculating max transaction: {e}")
        return jsonify({"error": {"code": 500, "message": "Internal server error"}}), 500

# Reference: LAB 2  - Order Service Reference to implement the basic structure of the order service
if __name__ == "__main__":
    try:
        syncOnInit(orderLogInit)
        logger.info(f"Replica {REPLICA_ID}: Order log initialized and synchronization completed.")
    except Exception as e:
        logger.error(f"Replica {REPLICA_ID}: Error during initialization or synchronization: {e}")
        exit(1) 

    try:
        logger.info(f"Replica {REPLICA_ID} starting on port {ORDER_PORT}")
        app.run(host=ORDER_HOST, port=ORDER_PORT, threaded=True)
    except Exception as e:
        logger.error(f"Replica {REPLICA_ID}: Error while starting the Flask server: {e}")
        exit(1)
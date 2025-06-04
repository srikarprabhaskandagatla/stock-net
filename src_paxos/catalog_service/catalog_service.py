# Importing the Required Libraries
from flask import Flask, request, jsonify
import logging, csv, os, requests
from rwlock import RWLock

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Reference: https://flask.palletsprojects.com/en/stable/quickstart/ 
app = Flask(__name__)

# Global Environment variables from Docker Compose file
CATALOG_PORT = int(os.environ.get("CATALOG_PORT", "8997"))
CATALOG_HOST = os.environ.get("CATALOG_HOST", "0.0.0.0")
FRONTEND_SERVICE_URL = os.environ.get("FRONTEND_SERVICE_URL", "http://frontend-service:9001")
CACHE_ENABLED = int(os.environ.get("CACHE_ENABLED", "1"))
CATALOG_FILE = "catalog.csv"

catalog = {} # In-merory catalog
catalog_lock = RWLock()

def catalogInit():
    global catalog
    try:
        if os.path.exists(CATALOG_FILE):
            with open(CATALOG_FILE, mode="r") as file:
                reader = csv.DictReader(file)
                for row in reader:
                    catalog[row["stock_name"]] = {
                        "price": float(row["price"]),
                        "quantity": int(row["quantity"])
                    }
        else:
            logger.warning("Catalog file not found. Initializing with default catalog.")
            catalog = {
                "APPL": {"price": 150.0, "quantity": 100},
                "GOOG": {"price": 280.0, "quantity": 100},
                "MSFT": {"price": 200.0, "quantity": 100},
                "AMZN": {"price": 350.0, "quantity": 100},
                "TSLA": {"price": 345.0, "quantity": 100},
                "META": {"price": 600.0, "quantity": 100},
                "NFLX": {"price": 700.0, "quantity": 100},
                "NVDA": {"price": 380.0, "quantity": 100},
                "AMD": {"price": 990.0, "quantity": 100},
                "IBM": {"price": 100.0, "quantity": 100}
            }
            loadCatalogToDisk() 
    except Exception as e:
        logger.error(f"Error during catalog initialization: {e}")
        raise

# Helper Functions - Load and save catalog to disk, notify for invalidation when stock is updated
def loadCatalogToDisk(stockName=None):
    try:
        with catalog_lock.writer_lock:
            if stockName:
                try:
                    with open(CATALOG_FILE, mode="r") as file:
                        rows = list(csv.DictReader(file))
                except FileNotFoundError:
                    logger.error(f"Catalog file not found while updating stock: {stockName}")
                    return

                with open(CATALOG_FILE, mode="w", newline="") as file:
                    writer = csv.DictWriter(file, fieldnames=["stock_name", "price", "quantity"])
                    writer.writeheader()
                    for row in rows:
                        if row["stock_name"] == stockName:
                            row["quantity"] = catalog[stockName]["quantity"]
                        writer.writerow(row)
            else:
                # Create a new file
                with open(CATALOG_FILE, mode="w", newline="") as file:
                    writer = csv.DictWriter(file, fieldnames=["stock_name", "price", "quantity"])
                    writer.writeheader()
                    for stockName, data in catalog.items():
                        writer.writerow({
                            "stock_name": stockName,
                            "price": data["price"],
                            "quantity": data["quantity"]
                        })
    except Exception as e:
        logger.error(f"Error while saving catalog to disk: {e}")

def notifyForInvalidation(stockName):
    try:
        # Frontend call to invalidate cache
        response = requests.post(f"{FRONTEND_SERVICE_URL}/invalidate/{stockName}")
        if response.status_code == 200:
            logger.info(f"Invalidation of cache request sent. Stock Name: {stockName}")
        else:
            logger.info(f"Failed to invalidate cache for stock: {stockName}")
    except requests.RequestException as e:
        logger.error(f"Found error while sending cache invalidation request: {e}")

# API Endpoints - GET and POST for stock lookup and update stocks which is requested from frontend service        
@app.route("/stocks/<stockName>", methods=["GET"])
def stockLookup(stockName):
    try:
        with catalog_lock.reader_lock:
            stock = catalog.get(stockName)
            if stock:
                logger.info(f"Looking for stock: {stockName}")
                return jsonify({
                    "name": stockName,
                    "price": stock["price"],
                    "quantity": stock["quantity"]
                }), 200
            else:
                return jsonify({"error": {"code": 404, "message": "No stock found."}}), 404
    except Exception as e:
        logger.error(f"Error during stock lookup for {stockName}: {e}")
        return jsonify({"error": {"code": 500, "message": "Internal server error"}}), 500

# Reference: LAB 2 - Catalog Service - Update the stock quantity and price
@app.route("/stocks/<stockName>", methods=["POST"])
def stockUpdate(stockName):
    try:
        stockData = request.get_json()
        tradeType = stockData.get("type")
        stockQuantity = stockData.get("quantity")

        if not tradeType or not stockQuantity:
            return jsonify({"error": {"code": 400, "message": "Request Data is invalid"}}), 400

        with catalog_lock.writer_lock:  # Acquire writer lock while update
            stock = catalog.get(stockName)
            if not stock:
                return jsonify({"error": {"code": 404, "message": "No stock found."}}), 404

            if tradeType == "buy":
                stock["quantity"] -= stockQuantity
            elif tradeType == "sell":
                stock["quantity"] += stockQuantity
            else:
                return jsonify({"error": {"code": 400, "message": "Found invalid trade type"}}), 400

        logger.info(f"Updated the catalog for stock: {stockName}")
        loadCatalogToDisk(stockName)

        if CACHE_ENABLED == 1:
            # Only notify when cache is enabled
            notifyForInvalidation(stockName)

        return jsonify({"message": "Successfully updated the stock."}), 200
    except Exception as e:
        logger.error(f"Error during stock update for {stockName}: {e}")
        return jsonify({"error": {"code": 500, "message": "Internal server error"}}), 500

if __name__ == "__main__":
    try:
        catalogInit()
        logger.info("Catalog initialized Correctly.")
    except Exception as e:
        logger.error(f"Error during catalog initialization: {e}")
        exit(1) 

    try:
        app.run(host=CATALOG_HOST, port=CATALOG_PORT, threaded=True)
    except Exception as e:
        logger.error(f"Error while starting the Flask server: {e}")
        exit(1) 
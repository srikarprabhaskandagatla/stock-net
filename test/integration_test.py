# Importing the required libraries
import os, unittest, time, requests, logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("IntegrationTest")

CATALOG_URL = os.environ.get("CATALOG_SERVICE_URL", "http://localhost:8997")
FRONTEND_URL = os.environ.get("FRONTEND_SERVICE_URL", "http://localhost:9001")

class IntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stocks_to_reset = ["NFLX", "MSFT", "GOOG", "AMD"]
        for stock in cls.stocks_to_reset:
            logger.info(f"Restocking {stock} to high quantity")
            resp = requests.post(
                f"{CATALOG_URL}/stocks/{stock}",
                json={"type": "sell", "quantity": 1000},
                timeout=5
            )
            if resp.status_code not in (200, 404):
                logger.warning(f"Unexpected status when restocking {stock}: {resp.status_code}")

    def test_lookupNotFound(self):
        stock = "NoSuchStock"
        logger.info("--------------------Test 1: lookup nonexistent stock via frontend should return 404--------------------")
        r = requests.get(f"{FRONTEND_URL}/stocks/{stock}")
        self.assertEqual(r.status_code, 404)

    def test_endToEndBuyAndQuery(self):
        stock = "NFLX"
        logger.info("--------------------Test 2: end-to-end BUY then QUERY for Netflix--------------------")
        r1 = requests.get(f"{FRONTEND_URL}/stocks/{stock}")
        self.assertEqual(r1.status_code, 200)
        qty_before = r1.json()['data']['quantity']
        logger.info(f"Quantity before buy: {qty_before}")
        r2 = requests.post(
            f"{FRONTEND_URL}/orders",
            json={"stock_name": stock, "type": "buy", "quantity": 1}
        )
        self.assertEqual(r2.status_code, 200)
        txn = r2.json()['data']['transaction_number']
        logger.info(f"Received transaction number: {txn}")
        time.sleep(0.5)
        r3 = requests.get(f"{FRONTEND_URL}/orders/{txn}")
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(r3.json()['data']['type'], 'buy')
        logger.info("Order query returned correct type 'buy'")

        r4 = requests.get(f"{FRONTEND_URL}/stocks/{stock}")
        self.assertEqual(r4.status_code, 200)
        qty_after = r4.json()['data']['quantity']
        self.assertEqual(qty_after, qty_before - 1)
        logger.info(f"Quantity after buy: {qty_after}")

    def test_endToEndSellAndQuery(self):
        stock = "MSFT"
        logger.info("--------------------Test 3: end-to-end SELL then QUERY for MSFT--------------------")

        r1 = requests.get(f"{FRONTEND_URL}/stocks/{stock}")
        self.assertEqual(r1.status_code, 200)
        qty_before = r1.json()['data']['quantity']
        logger.info(f"Quantity before sell: {qty_before}")

        r2 = requests.post(
            f"{FRONTEND_URL}/orders",
            json={"stock_name": stock, "type": "sell", "quantity": 2}
        )
        self.assertEqual(r2.status_code, 200)
        txn = r2.json()['data']['transaction_number']
        logger.info(f"Sell transaction number: {txn}")
        time.sleep(0.5)
        r3 = requests.get(f"{FRONTEND_URL}/orders/{txn}")
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(r3.json()['data']['type'], 'sell')
        logger.info("Order query returned correct type 'sell'")
        r4 = requests.get(f"{FRONTEND_URL}/stocks/{stock}")
        self.assertEqual(r4.status_code, 200)
        qty_after = r4.json()['data']['quantity']
        self.assertEqual(qty_after, qty_before + 2)
        logger.info(f"Quantity after sell: {qty_after}")

    def test_invalidTradeType(self):
        stock = "AMD"
        logger.info("--------------------Test 4: invalid trade type should return 400 for AMD--------------------")
        r = requests.post(
            f"{FRONTEND_URL}/orders",
            json={"stock_name": stock, "type": "hold", "quantity": 1}
        )
        self.assertEqual(r.status_code, 400)
        logger.info("Received 400 for invalid trade type as expected")

    def test_cacheInvalidation(self):
        stock = "AMD"
        logger.info("--------------------Test 5: cache invalidation after buy for AMD--------------------")

        r1 = requests.get(f"{FRONTEND_URL}/stocks/{stock}")
        self.assertEqual(r1.status_code, 200)
        qty_before = r1.json()['data']['quantity']
        logger.info(f"Quantity before buy: {qty_before}")

        r2 = requests.post(
            f"{FRONTEND_URL}/orders",
            json={"stock_name": stock, "type": "buy", "quantity": 3}
        )
        self.assertEqual(r2.status_code, 200)
        txn = r2.json()['data']['transaction_number']
        logger.info(f"Placed buy order, txn {txn}")
        time.sleep(0.5)
        r3 = requests.get(f"{FRONTEND_URL}/stocks/{stock}")
        self.assertEqual(r3.status_code, 200)
        qty_after = r3.json()['data']['quantity']
        self.assertEqual(qty_after, qty_before - 3)
        logger.info(f"Quantity after buy and cache invalidation: {qty_after}")

if __name__ == '__main__':
    unittest.main()

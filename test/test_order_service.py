# Importing the required libraries
import unittest, os, logging
from src.order_service import order_service as svc
from src.order_service.order_service import app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("OrderServiceTest")

# Order Service Tests
class OrderServiceTest(unittest.TestCase):
    def setUp(self):
        try:
            os.remove(svc.ORDER_LOG_FILE)
            logger.debug(f"Removed existing log file {svc.ORDER_LOG_FILE}")
        except FileNotFoundError:
            logger.debug("No existing log file to remove")
        svc.LEADER_ID = None
        svc.transaction_number = 0
        svc.ordersList.clear()
        self.client = app.test_client()

    def test_healthCheck(self):
        logger.info("\nTest 1: Health ping returns healthy status")
        rv = self.client.get('/ping')
        self.assertEqual(rv.status_code, 200)
        data = rv.get_json()
        self.assertEqual(data['status'], 'healthy')
        self.assertIsNone(data.get('leader_id'))

    def test_setLeaderAndPing(self):
        logger.info("\nTest 2: Set leader and verify via ping")
        leader = svc.SELF_URL
        rv1 = self.client.post('/set_leader', json={'leader_id': leader})
        self.assertEqual(rv1.status_code, 200)
        rv2 = self.client.get('/ping')
        self.assertEqual(rv2.status_code, 200)
        self.assertEqual(rv2.get_json().get('leader_id'), leader)

    def test_set_leaderMissingId(self):
        logger.info("\nTest 3: Calling 'set_leader' without payload returns 400")
        rv = self.client.post('/set_leader', json={})
        self.assertEqual(rv.status_code, 400)

    def test_maxTransaction(self):
        logger.info("\nTest 4: 'max_transaction' initially -1")
        rv = self.client.get('/max_transaction')
        self.assertEqual(rv.status_code, 200)
        self.assertEqual(rv.get_json().get('max_transaction'), -1)

    def test_getMissingOrders(self):
        logger.info("\nTest 5: 'get_missing_orders' returns empty list when none")
        rv = self.client.get('/get_missing_orders/0')
        self.assertEqual(rv.status_code, 200)
        self.assertEqual(rv.get_json().get('data'), [])

    def test_getOrderNotFound(self):
        logger.info("\nTest 6: 'get_order' returns 404 if order not found")
        rv = self.client.get('/orders/0')
        self.assertEqual(rv.status_code, 404)
        err = rv.get_json().get('error')
        self.assertEqual(err.get('code'), 404)

    def test_replicateOrderConflictWhenLeader(self):
        logger.info("\nTest 7: 'replicate_order' returns 409 when self is leader")
        svc.LEADER_ID = svc.SELF_URL
        payload = {'transaction_number': 0, 'stock_name': 'X', 'type': 'buy', 'quantity': 1}
        rv = self.client.post('/replicate_order', json=payload)
        self.assertEqual(rv.status_code, 409)

    def test_replicateOrderInvalidData(self):
        logger.info("\nTest 8: 'replicate_order' returns 400 for invalid data")
        svc.LEADER_ID = None
        payload = {'transaction_number': 'zero'}
        rv = self.client.post('/replicate_order', json=payload)
        self.assertEqual(rv.status_code, 400)

    def test_replicateOrderAndGet(self):
        logger.info("\nTest 9: Successful 'replicate_order' followed by get_order")
        svc.LEADER_ID = None
        payload = {'transaction_number': 5, 'stock_name': 'ABC', 'type': 'sell', 'quantity': 3}
        rv1 = self.client.post('/replicate_order', json=payload)
        self.assertEqual(rv1.status_code, 200)

        rv2 = self.client.get('/orders/5')
        self.assertEqual(rv2.status_code, 200)
        data = rv2.get_json().get('data')
        self.assertEqual(data, payload)

if __name__ == '__main__':
    unittest.main()
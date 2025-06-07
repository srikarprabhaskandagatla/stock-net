# Importing the required libraries
import unittest, os, logging
from src_paxos.order_service import order_service as svc
from src_paxos.order_service.order_service import app

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

    def test_01_healthCheck(self):
        logger.info("-----Test 1: Health ping returns healthy status-----")
        rv = self.client.get('/ping')
        self.assertEqual(rv.status_code, 200)
        data = rv.get_json()
        self.assertEqual(data['status'], 'healthy')
        self.assertIsNone(data.get('leader_id'))

    def test_02_setLeaderAndPing(self):
        logger.info("-----Test 2: Set leader and verify via ping-----")
        leader = svc.SELF_URL
        rv1 = self.client.post('/set_leader', json={'leader_id': leader})
        self.assertEqual(rv1.status_code, 200)
        rv2 = self.client.get('/ping')
        self.assertEqual(rv2.status_code, 200)
        self.assertEqual(rv2.get_json().get('leader_id'), leader)

    def test_03_set_leaderMissingId(self):
        logger.info("-----Test 3: Calling 'set_leader' without payload returns 400-----")
        rv = self.client.post('/set_leader', json={})
        self.assertEqual(rv.status_code, 400)

    def test_04_maxTransaction(self):
        logger.info("-----Test 4: 'max_transaction' initially -1-----")
        rv = self.client.get('/max_transaction')
        self.assertEqual(rv.status_code, 200)
        self.assertEqual(rv.get_json().get('max_transaction'), -1)

    def test_05_getMissingOrders(self):
        logger.info("-----Test 5: 'get_missing_orders' returns empty list when none-----")
        rv = self.client.get('/get_missing_orders/0')
        self.assertEqual(rv.status_code, 200)
        self.assertEqual(rv.get_json().get('data'), [])

    def test_06_getOrderNotFound(self):
        logger.info("-----Test 6: 'get_order' returns 404 if order not found-----")
        rv = self.client.get('/orders/0')
        self.assertEqual(rv.status_code, 404)
        err = rv.get_json().get('error')
        self.assertEqual(err.get('code'), 404)

    def test_07_replicateOrderConflictWhenLeader(self):
        logger.info("-----Test 7: 'replicate_order' returns 409 when self is leader-----")
        svc.LEADER_ID = svc.SELF_URL
        payload = {'transaction_number': 0, 'stock_name': 'X', 'type': 'buy', 'quantity': 1}
        rv = self.client.post('/replicate_order', json=payload)
        self.assertEqual(rv.status_code, 409)

    def test_08_replicateOrderInvalidData(self):
        logger.info("-----Test 8: 'replicate_order' returns 400 for invalid data-----")
        svc.LEADER_ID = None
        payload = {'transaction_number': 'zero'}
        rv = self.client.post('/replicate_order', json=payload)
        self.assertEqual(rv.status_code, 400)

    def test_09_replicateOrderAndGet(self):
        logger.info("-----Test 9: Successful 'replicate_order' followed by get_order-----")
        svc.LEADER_ID = None
        payload = {'transaction_number': 5, 'stock_name': 'ABC', 'type': 'sell', 'quantity': 3}
        rv1 = self.client.post('/replicate_order', json=payload)
        self.assertEqual(rv1.status_code, 200)

        rv2 = self.client.get('/orders/5')
        self.assertEqual(rv2.status_code, 200)
        data = rv2.get_json().get('data')
        self.assertEqual(data, payload)

    def test_10_paxos_prepare_and_accept(self):
        logger.info("-----Test 10: Paxos prepare and accept flow-----")
        # Prepare phase
        proposal_number = 12345
        logger.info([rule.rule for rule in app.url_map.iter_rules()])
        rv_prepare = self.client.post('/paxos/prepare', json={'proposal_number': proposal_number})
        self.assertEqual(rv_prepare.status_code, 200)
        prepare_data = rv_prepare.get_json()
        self.assertIn('promise', prepare_data)
        self.assertTrue(prepare_data['promise'])

        # Accept phase
        value = {'transaction_number': 20, 'stock_name': 'APPL', 'type': 'buy', 'quantity': 5}
        rv_accept = self.client.post('/paxos/accept', json={'proposal_number': proposal_number, 'value': value})
        self.assertEqual(rv_accept.status_code, 200)
        accept_data = rv_accept.get_json()
        self.assertIn('accepted', accept_data)
        self.assertTrue(accept_data['accepted'])

if __name__ == '__main__':
    unittest.main()
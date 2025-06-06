# Importing the required libraries
import unittest, logging, requests
from unittest.mock import patch
from src.frontend_service.frontend_service import (
    app, cache,
    orderHandler, queryOrderHandler
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("FrontendServiceTest")

# Frontend Service Tests
class FrontendServiceTest(unittest.TestCase):
    def setUp(self):
        logger.info("setUp: Clearing cache and resetting test client")
        cache.cache.clear()
        cache.access_order.clear()
        self.client = app.test_client()

    def test_01_lookupThroughCatalog(self):
        logger.info("-----Test 1: 'GET /stocks/<name>' should return data from Catalog-----")
        rv = self.client.get('/stocks/APPL')
        self.assertEqual(rv.status_code, 200)
        payload = rv.get_json()
        self.assertEqual(payload['message'], 'Lookup successful')
        self.assertIn('data', payload)

    def test_02_cacheMissAndHit(self):
        logger.info("-----Test 2: Cache Miss then Cache hit for same key-----")
        # First request should be a miss and populate cache
        rv1 = self.client.get('/stocks/TSLA')
        self.assertEqual(rv1.status_code, 200)
        data1 = rv1.get_json()['data']
        # Second request should hit cache
        rv2 = self.client.get('/stocks/TSLA')
        self.assertEqual(rv2.status_code, 200)
        data2 = rv2.get_json()['data']
        self.assertEqual(data1, data2)

    def test_03_invalidate(self):
        logger.info("-----Test 3: 'POST /invalidate/<name>' should clear Cache Entry-----")
        self.client.get('/stocks/AMD')
        rv = self.client.post('/invalidate/AMD')
        self.assertEqual(rv.status_code, 200)
        self.assertIn('Cache invalidated', rv.get_json()['message'])
        rv2 = self.client.get('/stocks/AMD')
        self.assertEqual(rv2.status_code, 200)

    @patch('src.frontend_service.frontend_service.requests.get')
    def test_04_lookupCatalogError(self, mock_get):
        logger.info("-----Test 4: 'GET /stocks/<name>' when catalog-service request fails-----")
        mock_get.side_effect = requests.RequestException("Connection failed")
        rv = self.client.get('/stocks/NoSuchStock')
        self.assertEqual(rv.status_code, 500)
        self.assertIn('error', rv.get_json())

    @patch('src.frontend_service.frontend_service.orderHandler')
    def test_05_order(self, mock_handle):
        logger.info("-----Test 5: 'POST /orders' success scenario-----")
        mock_handle.return_value = ({"data": {"transaction_number": 99}}, 200)
        rv = self.client.post(
            '/orders',
            json={"stock_name": "APPL", "type": "buy", "quantity": 1}
        )
        self.assertEqual(rv.status_code, 200)
        data = rv.get_json()['data']
        self.assertEqual(data['transaction_number'], 99)

    @patch('src.frontend_service.frontend_service.orderHandler')
    def test_06_order_route_failure(self, mock_handle):
        logger.info("-----Test 6: 'POST /orders' failure scenario-----")
        mock_handle.return_value = ({"error": {"code": 503, "message": "Leader down"}}, 503)
        rv = self.client.post(
            '/orders',
            json={"stock_name": "APPL", "type": "buy", "quantity": 1}
        )
        self.assertEqual(rv.status_code, 503)
        err = rv.get_json()['error']
        self.assertEqual(err['code'], 503)

    @patch('src.frontend_service.frontend_service.queryOrderHandler')
    def test_07_get_order_success(self, mock_query):
        logger.info("-----Test 7: 'GET /orders/<id>' success scenario-----")
        mock_query.return_value = (
            {"data": {"transaction_number": 7, "stock_name": "MSFT", "type": "sell", "quantity": 2}}, 
            200
        )
        rv = self.client.get('/orders/7')
        self.assertEqual(rv.status_code, 200)
        d = rv.get_json()['data']
        self.assertEqual(d['number'], 7)
        self.assertEqual(d['name'], 'MSFT')
        self.assertEqual(d['type'], 'sell')
        self.assertEqual(d['quantity'], 2)

    @patch('src.frontend_service.frontend_service.queryOrderHandler')
    def test_08_get_order_failure(self, mock_query):
        logger.info("-----Test 8: 'GET /orders/<id>' failure scenario-----")
        mock_query.return_value = ({"error": {"code": 404, "message": "Not found"}}, 404)
        rv = self.client.get('/orders/123')
        self.assertEqual(rv.status_code, 404)
        err = rv.get_json()['error']
        self.assertEqual(err['code'], 404)

if __name__ == '__main__':
    unittest.main()
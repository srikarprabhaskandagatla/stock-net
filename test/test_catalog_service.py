import unittest
import json
import os
import logging
from src.catalog_service.catalog_service import app, catalogInit, CATALOG_FILE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("CatalogServiceTest")

class CatalogServiceTest(unittest.TestCase):
    def setUp(self):
        if os.path.exists(CATALOG_FILE):
            logger.info("setUp: Removing existing catalog file (if any) and initializing catalog")
            os.remove(CATALOG_FILE)
        catalogInit()
        self.client = app.test_client()

    def test_existingLookup(self):
        logger.info("Test 1: lookup existing stock (AppleInc) with new GET route")
        rv = self.client.get('/stocks/AppleInc')
        self.assertEqual(rv.status_code, 200)

        data = rv.get_json()
        self.assertEqual(data['name'], 'AppleInc')
        self.assertEqual(data['quantity'], 100)

    def test_lookupNotFound(self):
        logger.info("--------------Test 2: lookup nonexistent stock (NoSuchStock)--------------------")
        rv = self.client.get('/stocks/NoSuchStock')
        self.assertEqual(rv.status_code, 404)
        err = rv.get_json()['error']
        self.assertEqual(err['code'], 404)

    def test_buyReducesQuality(self):
        logger.info("-----------------Test 3: buy order reduces quantity (MSFT)-------------------------")
        before = self.client.get('/stocks/MSFT').get_json()['quantity']
        rv = self.client.post(
            '/stocks/MSFT',
            data=json.dumps({"type": "buy", "quantity": 5}),
            content_type='application/json'
        )
        self.assertEqual(rv.status_code, 200)
        after = self.client.get('/stocks/MSFT').get_json()['quantity']
        self.assertEqual(after, before - 5)

    def test_sellIncreasesQuantity(self):
        logger.info("------------------Test 4: sell order increases quantity (AMD)-----------------------")
        before = self.client.get('/stocks/AMD').get_json()['quantity']
        rv = self.client.post(
            '/stocks/AMD',
            data=json.dumps({"type": "sell", "quantity": 10}),
            content_type='application/json'
        )
        self.assertEqual(rv.status_code, 200)
        after = self.client.get('/stocks/AMD').get_json()['quantity']
        self.assertEqual(after, before + 10)

    def test_invalidTradeType(self):
        logger.info("----------------------Test 5: invalid trade type (hold)-------------------------------")
        rv = self.client.post(
            '/stocks/MSFT',
            data=json.dumps({"type": "hold", "quantity": 5}),
            content_type='application/json'
        )
        self.assertEqual(rv.status_code, 400)
        err = rv.get_json()['error']
        self.assertEqual(err['code'], 400)

    def test_missingRequestData(self):
        logger.info("-----------------------Test 6: missing request data---------------------------")
        rv1 = self.client.post(
            '/stocks/AppleInc',
            data=json.dumps({"quantity": 5}),
            content_type='application/json'
        )
        self.assertEqual(rv1.status_code, 400)
        rv2 = self.client.post(
            '/stocks/AppleInc',
            data=json.dumps({"type": "buy"}),
            content_type='application/json'
        )
        self.assertEqual(rv2.status_code, 400)

    def test_update_nonexistent_stock(self):
        logger.info("--------------------Test 7: update on nonexistent stock (UnknownStock)------------------------")
        rv = self.client.post(
            '/stocks/UnknownStock',
            data=json.dumps({"type": "buy", "quantity": 1}),
            content_type='application/json'
        )
        self.assertEqual(rv.status_code, 404)
        err = rv.get_json()['error']
        self.assertEqual(err['code'], 404)

if __name__ == '__main__':
    unittest.main()

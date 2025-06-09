# Design Document
This document provides a comprehensive overview of the architecture, components, and design decisions for the Stock Net microservices-based stock trading simulation system. It outlines the goals, requirements, service interactions, caching strategy, replication, fault tolerance mechanisms, and deployment approach, serving as a reference for both implementation and future enhancements.

# Table of Contents
<nav>
  <ul>
    <li><a href="#1-overview">1. Overview</a></li>
    <li><a href="#2-goals-and-requirements">2. Goals and Requirements</a></li>
    <li><a href="#3-flow-description">3. Flow Description</a></li>
    <li><a href="#4-detailed-design">4. Detailed Design</a>
      <ul>
        <li><a href="#41-client-service-client_load_testpy">4.1. Client Service (client_load_test.py)</a></li>
        <li><a href="#42-catalog-service-catalog_servicepy">4.2. Catalog Service (catalog_service.py)</a></li>
        <li><a href="#43-front-end-service-frontend_servicepy">4.3. Front-end Service (frontend_service.py)</a></li>
        <li><a href="#44-order-service-order_servicepy">4.4. Order Service (order_service.py)</a></li>
      </ul>
    </li>
    <li><a href="#5-data-storage">5. Data Storage</a></li>
    <li><a href="#6-caching-strategy">6. Caching Strategy</a></li>
    <li><a href="#7-replication-and-fault-tolerance">7. Replication and Fault Tolerance</a></li>
    <li><a href="#8-api-definitions-summary">8. API Definitions Summary</a></li>
    <li><a href="#9-deployment-docker-and-aws">9. Deployment (Docker and AWS)</a></li>
    <li><a href="#10-testing">10. Testing</a></li>
  </ul>
</nav>

## 1. Overview
This document details about the microservices-based system for stock trading simulation. The primary goal is to improve performance, reliability, and fault tolerance by introducing caching, replication, and failure handling mechanisms. The system consists of a Front-end service, a Catalog service, and an Order service. This incorporates the requirements specified for caching (Part 1), replication (Part 2), and fault tolerance (Part 3).

## 2. Goals and Requirements

* **Microservices Architecture:** Maintain the three-service structure: Front-end, Catalog, Order.
* **API Implementation:**
    * Front-end exposes `GET /stocks/<stock_name>`, `POST /orders`.
    * Front-end adds a new API: `GET /orders/<order_number>`.
    * Internal API contracts between services are flexible but must support the required functionality.
* **Concurrency:** All microservices must handle concurrent requests. The provided implementation uses Flask's `threaded=True` option.
* **Catalog Initialization:** Catalog service initializes with at least 10 stocks, each with an initial volume of 100.
* **Client Simulation:** A client interacts with the Front-end by querying random stocks and potentially making trades based on a configurable probability `p`. The client verifies successful orders at the end.
* **Caching (Part 1):**
    * Implement an in-memory cache in the Front-end service for `GET /stocks/<stock_name>` requests.
    * Use a Least Recently Used (LRU) cache replacement policy.
    * Cache size must be configurable and set lower than the total number of stocks to exercise the replacement policy.
    * Implement cache consistency using server-push invalidation: Catalog service notifies the Front-end service to invalidate specific stock entries after trades.
* **Replication (Part 2):**
    * Replicate the Order service with three instances (replicas).
    * Each replica has a unique ID and its own persistent storage (CSV file).
    * Implement a static leader election mechanism: Front-end selects the replica with the highest ID as the leader by pinging them in descending order of ID.
    * Front-end notifies all replicas of the chosen leader.
    * Front-end directs all order processing (`POST /orders`) and order query (`GET /orders/<order_number>`) requests solely to the leader.
    * The leader propagates new order information to follower replicas.
* **Fault Tolerance (Part 3):**
    * Handle crash failures of any Order service replica (leader or follower).
    * If the Front-end detects the leader is unresponsive (e.g., request timeout), it must re-run the leader election process to select a new leader from the remaining responsive replicas.
    * When a crashed Order service replica restarts, it must synchronize its state by retrieving missed order information from other replicas based on its last known order number.

## 3. Flow Description

1.  **Stock Lookup (`GET /stocks/<stock_name>`):**
    * Client sends request to Front-end.
    * Front-end checks its LRU cache.
    * If hit, returns cached data.
    * If miss, queries Catalog service, caches the result (if cache enabled), and returns to Client.

2.  **Trade (`POST /orders`):**
    * Client sends request to Front-end.
    * Front-end forwards the request to the current Order Service Leader.
    * Leader validates the trade against the Catalog service (checks quantity).
    * If valid:
        * Leader updates the Catalog service (decrementing/incrementing quantity).
        * Leader generates a transaction number, persists the order locally.
        * Leader asynchronously propagates the order details to all follower replicas.
        * Leader returns the transaction number to the Front-end, which returns it to the Client.
    * Catalog service, upon successful update, sends an invalidation request to the Front-end for the specific stock, clearing it from the cache.

3.  **Order Query (`GET /orders/<order_number>`):**
    * Client sends request to Front-end.
    * Front-end forwards the request to the current Order Service Leader.
    * Leader looks up the order in its persisted log and returns the details.

4.  **Leader Failure:**
    * If the Front-end fails to communicate with the Leader (timeout/error), it initiates the leader re-election process among the available Order service replicas.

5.  **Replica Recovery:**
    * A restarting Order service replica reads its log to find the highest transaction number it possesses.
    * It then queries other replicas for orders with higher transaction numbers.
    * It updates its own log and in-memory state based on the retrieved information.

## 4. Detailed Design

### 4.1. Client Service (`client_load_test.py`)

* **Functionality:** Simulates user behavior, measures request latencies, and verifies order consistency.
* **Workflow:**
    * Initialize with `FRONTEND_SERVICE_URL`.
    * Run multiple client sessions concurrently (`ThreadPoolExecutor`).
    * Each session iterates `NUM_ITERATIONS` times:
        * Choose a random stock from `STOCKS`.
        * Perform `lookupStock` (`GET /stocks/...`), record latency.
        * With probability `p`, perform `buyStock` (`POST /orders`) with random type/quantity, record latency. Store successful `transaction_number` and order details.
        * Wait randomly (`time.sleep`).
    * After iterations, query details for all successful orders using `queryOrderDetails` (`GET /orders/...`), record latency.
    * Verify retrieved order details against locally stored details (implicit, should be added for full verification).
    * Aggregate latencies.
    * Plot average latencies vs. trade probability `p`.
* **Dependencies:** `requests`, `matplotlib`, `numpy`.
* **Configuration:** `FRONTEND_SERVICE_URL`, `NUM_ITERATIONS`, `NUM_CLIENTS`, `CACHE_ENABLED` (for plotting title), `STOCKS`, `probability_values`.

### 4.2. Catalog Service (`catalog_service.py`)

* **Functionality:** Manages stock information (price, quantity). Provides lookup and update capabilities. Handles cache invalidation notifications.
* **API Endpoints:**
    * `GET /stocks/<stockName>`: Returns stock details (price, quantity).
    * `POST /stocks/<stockName>`: Updates stock quantity based on trade type ('buy' decreases, 'sell' increases). Triggers cache invalidation if enabled.
* **Data Storage:**
    * In-memory dictionary (`catalog`) for fast access.
    * Persistent storage in `catalog.csv`. Loaded on startup (`catalogInit`). Updated after trades (`loadCatalogToDisk`).
* **Concurrency:** Uses `RWLock` (`reader_lock` for lookups, `writer_lock` for updates and persistence) to allow concurrent reads but exclusive writes.
* **Cache Invalidation:** If `CACHE_ENABLED=1`, after a successful `POST /stocks/<stockName>`, calls `notifyForInvalidation` which sends a `POST /invalidate/<stockName>` request to the Front-end service.
* **Framework:** Flask (`threaded=True`).
* **Dependencies:** `flask`, `requests`, `csv`, `rwlock`.
* **Configuration:** `CATALOG_PORT`, `CATALOG_HOST`, `FRONTEND_SERVICE_URL`, `CACHE_ENABLED`, `CATALOG_FILE`.

### 4.3. Front-end Service (`frontend_service.py`)

* **Functionality:** Acts as an API gateway, performs caching, handles leader election, and routes requests to the appropriate backend services.
* **API Endpoints:**
    * `GET /stocks/<stock_name>`: Looks up stock, utilizing the cache.
    * `POST /orders`: Forwards trade requests to the Order Service Leader.
    * `GET /orders/<int:order_number>`: Forwards order query requests to the Order Service Leader.
    * `POST /invalidate/<stock_name>`: Internal endpoint called by Catalog service to invalidate a cache entry.
* **Caching:**
    * Uses `LRUCache` class (implemented with `deque` and `dict`) if `CACHE_ENABLED=1`.
    * Cache capacity set by `CACHE_SIZE`.
    * `get`: Retrieves from cache, updates access order.
    * `put`: Adds/updates cache, handles eviction based on LRU if capacity is reached.
    * `invalidate`: Removes an entry from the cache.
    * Thread-safe via `threading.Lock` within `LRUCache`.
* **Leader Election (`findLeader`, `notifyOrderServiceReplicas`):**
    * Runs on startup and when the current leader becomes unresponsive.
    * Pings Order service replicas (URLs from `ORDER_SERVICE_URLS`) in descending order of inferred ID (based on URL/port).
    * First responsive replica becomes the `LEADER_URL`.
    * Notifies all replicas via `POST /set_leader`.
    * Raises an exception if no leader can be found.
* **Request Handling (`orderHandler`, `queryOrderHandler`):**
    * Ensures a leader is selected (`LEADER_URL` is not `None`).
    * Sends requests to the `LEADER_URL`.
    * Implements a retry mechanism (default 3 retries): If a request to the leader fails (`requests.RequestException`), it calls `findLeader` to potentially elect a new leader and retries the request.
    * Returns appropriate success or error responses (including 503 if leader is unavailable after retries).
* **Framework:** Flask (`threaded=True`).
* **Dependencies:** `flask`, `requests`, `collections.deque`, `threading`.
* **Configuration:** `CATALOG_SERVICE_URL`, `ORDER_SERVICE_URLS`, `FRONTEND_PORT`, `FRONTEND_HOST`, `CACHE_ENABLED`, `CACHE_SIZE`.

### 4.4. Order Service (`order_service.py`)

* **Functionality:** Manages order processing, persistence, replication, and state synchronization. Operates in Leader or Follower mode.
* **API Endpoints:**
    * `GET /ping`: Health check. Returns status and current leader (if known).
    * `POST /set_leader`: Called by Front-end to inform the replica of the current leader's URL. Triggers leader state recovery if self becomes leader.
    * `POST /orders`: (Leader Only) Processes a new trade request. Interacts with Catalog Service, generates transaction number, persists order, and propagates to followers. Returns 403 if called on a follower. Returns 503 if leader recovery is in progress.
    * `GET /orders/<int:transactionNumToQuery>`: (Leader Recommended, Implementation allows any replica) Retrieves order details from the local log file. Returns 404 if not found.
    * `POST /replicate_order`: (Follower Only) Called by the Leader to replicate an order. Persists the order locally. Returns 409 if called on the leader.
    * `GET /get_missing_orders/<int:lastOrderNum>`: Returns orders from the in-memory list with transaction numbers greater than `lastOrderNum`. Used for recovery.
    * `GET /max_transaction`: Returns the highest transaction number known by this replica (from in-memory list). Used during leader recovery.
* **State:**
    * `REPLICA_ID`, `SELF_URL`, `LEADER_ID` (URL of the leader).
    * `transactionNumber` (Leader only counter, initialized during recovery).
    * `ordersList` (in-memory list of orders).
    * `leaderRecoveryCompleted` (Flag to indicate if leader initialization is done).
* **Data Storage:**
    * Persistent storage in `order_log_{REPLICA_ID}.csv`. Each order is appended (`loadOrderToDisk`).
    * Orders loaded into `ordersList` on startup (`orderLogInit`).
* **Concurrency:** Uses `threading.Lock` for `transaction_lock`, `orders_list_lock`, `order_log_lock`, `leader_recovery_lock` to protect shared state.
* **Replication:**
    * Leader sends orders to followers via `sendToFollowers` (background thread) by calling `POST /replicate_order` on follower URLs.
    * Followers receive orders via `/replicate_order`, persist them (`loadOrderToDisk`), and update memory (`loadOrderToMemory`).
* **Fault Tolerance & Recovery:**
    * **Startup Sync (`orderLogInit`, `syncOnInit`, `appendMissingOrders`):** Loads local CSV, then asks other replicas for orders newer than its max known order number. Persists and loads received orders.
    * **Leader Recovery (`recoverStateForLeader`):** When elected leader (`/set_leader`), queries max transaction number from all other replicas, sets its `transactionNumber` counter to `max(all_max_transactions) + 1`, and runs `appendMissingOrders` to ensure it has all orders before accepting requests (`leaderRecoveryCompleted = True`).
* **Framework:** Flask (`threaded=True`).
* **Dependencies:** `flask`, `requests`, `csv`, `threading`.
* **Configuration:** `REPLICA_ID`, `ORDER_PORT`, `ORDER_HOST`, `CATALOG_SERVICE_URL`, `TOTAL_REPLICAS`, `ORDER_LOG_FILE`, `SELF_URL` (constructed).

## 5. Data Storage

* **Catalog Service:** Uses a single `catalog.csv` file for persistence, alongside an in-memory dictionary for performance. Data consistency relies on the `RWLock`.
* **Order Service:** Each replica maintains its own independent `order_log_{REPLICA_ID}.csv` file. Consistency across replicas is achieved through leader propagation and follower recovery mechanisms. Data is also held in an in-memory list (`ordersList`) for faster querying during recovery (`get_missing_orders`, `max_transaction`).

## 6. Caching Strategy

* **Location:** Front-end Service.
* **Type:** In-memory.
* **Policy:** Least Recently Used (LRU). Implemented using `collections.deque` to track access order and a `dict` for O(1) lookups.
* **Size:** Configurable via `CACHE_SIZE` environment variable. Must be smaller than the number of stocks.
* **Consistency:** Server-Push Invalidation.
    * Catalog service detects changes (trades).
    * Catalog service sends `POST /invalidate/<stock_name>` to the Front-end service.
    * Front-end service removes the specified `stock_name` from its cache upon receiving the invalidation request.
* **Scope:** Caches results of `GET /stocks/<stock_name>`.

## 7. Replication and Fault Tolerance

* **Scope:** Order Service.
* **Model:** Leader-Follower Replication (3 replicas).
* **Leader Election:** Static, preference-based. Front-end service manages election.
    * On startup or leader failure detection (timeout), Front-end pings replicas (highest ID first).
    * First responsive replica is designated leader.
    * Front-end notifies all replicas of the leader via `POST /set_leader`.
* **Data Propagation:** Leader asynchronously sends committed orders to all followers via `POST /replicate_order`. Followers persist the data.
* **Failure Detection:** Front-end detects leader failure through request timeouts/errors during `orderHandler` or `queryOrderHandler`.
* **Failover:** Upon leader failure detection, Front-end triggers leader re-election.
* **Replica Recovery:**
    * Restarting replica loads its state from its local `order_log_X.csv`.
    * Determines its maximum known transaction number (`maxTransactionNum`).
    * Calls `GET /get_missing_orders/<maxTransactionNum>` on other replicas.
    * Applies received orders (validating transaction numbers) to its in-memory state and persists them to its log file.
    * A newly elected leader performs additional recovery (`recoverStateForLeader`) to determine the correct next global transaction number and ensure it has the complete order history before serving requests.

## 8. API Definitions Summary

| Service         | Endpoint                                | Method | Description                                      | Called By                  |
| :-------------- | :-------------------------------------- | :----- | :----------------------------------------------- | :------------------------- |
| **Front-end** | `/stocks/<stock_name>`                  | GET    | Lookup stock info (cached)                       | Client                     |
|                 | `/orders`                               | POST   | Place a buy/sell order                           | Client                     |
|                 | `/orders/<order_number>`                | GET    | Query a specific order                           | Client                     |
|                 | `/invalidate/<stock_name>`              | POST   | Invalidate cache entry                           | Catalog Svc                |
| **Catalog** | `/stocks/<stockName>`                   | GET    | Get stock details                                | Front-end Svc, Order Svc |
|                 | `/stocks/<stockName>`                   | POST   | Update stock quantity                            | Order Svc                  |
| **Order (Any)** | `/ping`                                 | GET    | Health check                                     | Front-end Svc              |
|                 | `/set_leader`                           | POST   | Set the leader URL                               | Front-end Svc              |
|                 | `/orders/<transactionNumToQuery>`       | GET    | Get order details (primarily Leader)             | Front-end Svc              |
|                 | `/get_missing_orders/<lastOrderNum>`    | GET    | Get orders newer than `lastOrderNum`             | Order Svc (Recovery)       |
|                 | `/max_transaction`                      | GET    | Get highest known transaction number             | Order Svc (Leader Recovery)|
| **Order (Leader)**| `/orders`                               | POST   | Process order                                    | Front-end Svc              |
| **Order (Follower)**| `/replicate_order`                    | POST   | Replicate order 

## 9. Deployment (Docker and AWS)

* The application is designed to be deployed using Docker and Docker Compose.
* The `docker-compose.yml` file defines the services (catalog, order-service-1, order-service-2, order-service-3, frontend, client, test), their builds, ports, volumes, environment variables (including service URLs, ports, replica IDs, cache settings), dependencies, and network configuration (`stock-net`).
* Each service runs in its own container.
* Volumes are used to mount source code and potentially persist log files.

## 10. Testing

* **Unit Tests:** Provided for each service (`test_catalog_service.py`, `test_frontend_service.py`, `test_order_service.py`). These tests  verify individual component logic and API endpoints.
* **Integration Tests:** `integration_test.py` performs end-to-end tests by sending requests to the Front-end service and verifying the interactions and state changes across services (e.g., checking stock quantity updates after trades, verifying order queries, testing cache invalidation indirectly).
* **Test Execution:** The `test` service in `docker-compose.yml` runs all test suites sequentially within the Docker network.
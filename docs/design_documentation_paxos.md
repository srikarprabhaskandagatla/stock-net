# Design Document With Paxos
This document provides an in-depth overview of the Stock Bazaar application's architecture and design, with a focus on reliability, consistency, and fault tolerance achieved through the Paxos consensus protocol. It explains the roles of each microservice, the flow of data and requests, and the mechanisms for caching, replication, and recovery. The document serves as a reference for understanding how Paxos is integrated into the system to ensure strong consistency and high availability, even in the presence of failures.

# Table of Contents
<nav>
  <ul>
    <li><a href="#1-introduction">1. Introduction</a>
      <ul>
        <li><a href="#11-purpose">1.1 Purpose</a></li>
        <li><a href="#12-scope">1.2 Scope</a></li>
        <li><a href="#13-system-overview">1.3 System Overview</a></li>
      </ul>
    </li>
    <li><a href="#2-flow-interactions">2. Flow Interactions</a></li>
    <li><a href="#3-component-design">3. Component Design</a>
      <ul>
        <li><a href="#31-client-service-client_load_testpy">3.1 Client Service (client_load_test.py)</a></li>
        <li><a href="#32-catalog-service-catalog_servicepy">3.2 Catalog Service (catalog_service.py)</a></li>
        <li><a href="#33-front-end-service-frontend_servicepy">3.3 Front-end Service (frontend_service.py)</a></li>
        <li><a href="#34-order-service-order_servicepy">3.4 Order Service (order_service.py)</a></li>
      </ul>
    </li>
    <li><a href="#4-data-models">4. Data Models</a></li>
    <li><a href="#5-communication-protocols">5. Communication Protocols</a></li>
    <li><a href="#6-caching-strategy-front-end">6. Caching Strategy (Front-end)</a></li>
    <li><a href="#7-replication-strategy-order-service">7. Replication Strategy (Order Service)</a></li>
    <li><a href="#8-fault-tolerance-strategy">8. Fault Tolerance Strategy</a></li>
    <li><a href="#9-consensus-protocol-paxos">9. Consensus Protocol (Paxos)</a></li>
    <li><a href="#10-deployment-docker-compose-and-aws">10. Deployment (Docker Compose and AWS)</a></li>
  </ul>
</nav>

## 1. Introduction
This document describes the design and architecture of the Stock Bazaar application, focusing on reliability, consistency, and fault tolerance using the Paxos consensus protocol. The system uses microservices—Client, Front-end, Catalog, and Order services—with clear roles. By leveraging caching, replication, and Paxos, the application achieves high availability, strong consistency for orders, and resilience to failures. This documentation covers component interactions, data models, communication protocols, and strategies for caching, replication, and fault tolerance.

### 1.1 Purpose
This document details the design for enhancing the Stock Bazaar application by incorporating caching, replication, and fault tolerance mechanisms with paxos. The goal is to improve performance, ensure data durability, and increase service availability.

### 1.2 Scope
The project involves modifications to the existing Front-end, Catalog, and Order microservices, introducing new functionalities and resilience patterns. It also includes a client simulation component for testing and verification. An optional extension involves implementing the Paxos consensus protocol for the Order service.

### 1.3 System Overview
The application follows a microservice architecture(All the code is written in **src_paxos** directory for paxos):

* **Client Service:** Simulates user interactions (stock lookups, trades) and verifies order consistency.
* **Front-end Service:** Acts as the API gateway for clients, interacts with Catalog and Order services, and implements caching.
* **Catalog Service:** Manages stock information (name, price, volume) and notifies the Front-end service of changes.
* **Order Service:** Handles trade execution logic, manages order history, and is replicated for fault tolerance and data durability.

## 2. Flow Interactions

* **Lookup:**
    1.  `Client` -> `Frontend` -> Cache Check
    2.  *If Cache Hit:* `Frontend` -> `Client`
    3.  *If Cache Miss:* `Frontend` -> `Catalog` -> `Frontend` (Update Cache) -> `Client`

* **Trade:**
    1.  `Client` -> `Frontend` -> `Order Leader`
    2.  `Order Leader` -> `Catalog` (Update Stock)
    3.  `Catalog` -> `Frontend` (Invalidate Cache)
    4.  `Order Leader` -> Replicate to `Followers`
    5.  `Order Leader` -> `Frontend` -> `Client`

* **Order Query:**
    * `Client` -> `Frontend` -> `Order Leader` -> `Frontend` -> `Client`

* **Leader Failure:**
    * `Client` -> `Frontend` -> `Order Leader` (Fails) -> `Frontend` (Detects Failure) -> `Frontend` (Select New Leader) -> `Frontend` -> New `Order Leader` -> ... (subsequent interaction)

* **Replica Recovery:**
    * Restarted `Replica` -> Ask Other Replicas (Sync Request) -> Other Replicas -> Restarted `Replica` (Update State)

## 3. Component Design

### 3.1 Client Service (`client_load_test.py`)

* **Responsibilities:**
    * Simulate concurrent client sessions.
    * Perform stock lookup requests (`GET /stocks/<stock_name>`).
    * Perform trade requests (`POST /orders`) with a configurable probability `p`.
    * Record details of successful orders locally.
    * Perform order query requests (`GET /orders/<order_number>`) to verify recorded orders before exiting.
    * Measure and report request latencies.
* **Configuration:**
    * `FRONTEND_SERVICE_URL`: Address of the Front-end service.
    * `NUM_ITERATIONS`: Number of lookup/trade cycles per client.
    * `NUM_CLIENTS`: Number of concurrent clients to simulate.
    * `probability_p`: Probability of making a trade after a lookup.
    * `CACHE_ENABLED`: Flag (passed via env, primarily affects plot title).
* **Concurrency:**
    * Uses `concurrent.futures.ThreadPoolExecutor` to run multiple `clientSession` instances concurrently.
* **Verification:**
    * Compares data from `GET /orders/<order_number>` with locally stored details of successful trades.
* **Latency Measurement:**
    * Wraps API calls (`lookupStock`, `buyStock`, `queryOrderDetails`) with `measureLatency` function to record execution time.

### 3.2 Catalog Service (`catalog_service.py`)

* **Responsibilities:**
    * Maintain the master list of available stocks, their prices, and quantities.
    * Provide stock information via a REST API.
    * Update stock quantities based on trades.
    * Persist catalog data to a CSV file (`catalog.csv`).
    * Notify the Front-end service to invalidate its cache when stock quantities change.
* **API Endpoints:**
    * `GET /stocks/<stockName>`: Returns details for a specific stock.
    * `POST /stocks/<stockName>`: (Internal) Updates the quantity of a stock after a trade. Expects JSON body `{"type": "buy"|"sell", "quantity": int}`.
* **Data Management:**
    * Uses an in-memory dictionary (`catalog`) for fast lookups.
    * Initializes from `catalog.csv` if it exists, otherwise uses default hardcoded values (at least 10 stocks, volume 100).
    * Uses `loadCatalogToDisk()` to write changes back to `catalog.csv` for persistence (updates specific stock row or rewrites entire file on init).
    * Uses a `RWLock` (`catalog_lock`) to allow concurrent reads while ensuring exclusive access for writes (updates).
* **Cache Invalidation:**
    * If `CACHE_ENABLED` is true, calls `notifyForInvalidation(stockName)` after successfully updating a stock via `POST /stocks/<stockName>`. This function sends a `POST` request to the Front-end's `/invalidate/<stockName>` endpoint.
* **Concurrency:**
    * Uses Flask with `threaded=True` and the `RWLock` for thread-safe access to the shared catalog dictionary and CSV file.

### 3.3 Front-end Service (`frontend_service.py`)

* **Responsibilities:**
    * Act as the single point of contact for clients.
    * Route client requests to the appropriate backend service (Catalog or Order).
    * Implement client-side caching for stock lookups (`GET /stocks/<stock_name>`).
    * Manage Order Service leader selection and failover.
    * Forward order-related requests (`POST /orders`, `GET /orders/<order_number>`) only to the current Order Service leader.
    * Handle cache invalidation requests from the Catalog Service.
* **API Endpoints:**
    * `GET /stocks/<stock_name>`: Handles stock lookup requests, utilizing the cache.
    * `POST /orders`: Handles trade requests, forwarding them to the Order Service leader.
    * `GET /orders/<order_number>`: Handles order query requests, forwarding them to the Order Service leader.
    * `POST /invalidate/<stock_name>`: (Internal) Endpoint called by the Catalog Service to invalidate a specific stock entry in the cache.
* **Caching (Part 1 Implementation):**
    * Uses an `LRUCache` class instance (`cache`) if `CACHE_ENABLED=1`.
    * `LRUCache` uses a dictionary for $O(1)$ lookup and a `collections.deque` to track access order for $O(1)$ updates/evictions.
    * A `threading.Lock` within `LRUCache` ensures thread safety.
    * Cache size is configurable via `CACHE_SIZE` environment variable.
    * `GET /stocks/<stock_name>` checks the cache first (`cache.get`). On miss, fetches from Catalog, stores result (`cache.put`), and returns. On hit, returns cached data.
    * `POST /invalidate/<stock_name>` calls `cache.invalidate(stock_name)` to remove the entry.
* **Replication & Leader Management (Part 2 Implementation):**
    * Reads Order Service replica URLs from `ORDER_SERVICE_URLS`.
    * `findLeader()`: Iterates through replicas (sorted by URL/ID descending) and sends `GET /ping` requests. The first responsive replica is designated as the leader (`LEADER_URL`).
    * `notifyOrderServiceReplicas()`: After finding a leader, sends a `POST /set_leader` request to all replicas (including the leader itself) with the leader's URL.
    * `orderHandler()` (for `POST /orders`) and `orderQueryHandler()` (for `GET /orders/<order_number>`): Send requests only to the current `LEADER_URL`.
* **Fault Tolerance (Part 3 Implementation):**
    * `orderHandler()` and `orderQueryHandler()` include retry logic. If a request to the `LEADER_URL` fails (e.g., `requests.RequestException`, non-200 status), it calls `findLeader()` to potentially select a new leader and retries the request up to `max_retries` times.
    * Handles cases where the leader might be temporarily unresponsive during its recovery phase (`resp.json().get("recovery_done", True)` check and 503 handling).
* **Concurrency:**
    * Uses Flask with `threaded=True` to handle multiple client requests simultaneously. Cache operations and leader variable access are protected by locks within their respective methods/classes.

### 3.4 Order Service (`order_service.py`)

* **Responsibilities:**
    * Process trade requests validated by the Catalog Service (Leader role).
    * Assign unique, sequential transaction numbers to orders (Leader role).
    * Persist order details to a local CSV log file (`order_log_{REPLICA_ID}.csv`).
    * Maintain an in-memory list of orders.
    * Replicate new orders to follower replicas (Leader role).
    * Accept replicated orders from the leader (Follower role).
    * Handle leader status updates from the Front-end service.
    * Synchronize state with other replicas upon recovery from a crash.
    * Participate in Paxos consensus (Optional).
* **API Endpoints:**
    * `GET /ping`: Health check endpoint, also returns leader status and recovery status.
    * `POST /set_leader`: (Internal) Called by Front-end to inform replica of the current leader. Triggers recovery if this replica becomes the leader.
    * `POST /orders`: (Leader Only) Processes a new trade request. Interacts with Catalog, assigns transaction number, logs locally, initiates replication/Paxos, and returns transaction number.
    * `POST /replicate_order`: (Follower Only, Non-Paxos) Accepts order data from the leader and persists it locally.
    * `GET /orders/<transactionNum>`: Retrieves details of a specific order from local storage.
    * `GET /get_missing_orders/<lastTransactionNum>`: (Internal) Returns orders with transaction numbers greater than `lastTransactionNum`. Used for recovery synchronization.
    * `GET /max_transaction`: (Internal) Returns the highest transaction number known to this replica. Used during recovery.
    * `POST /paxos/prepare`: (Acceptor Role - Paxos) Handles the prepare phase message.
    * `POST /paxos/accept`: (Acceptor Role - Paxos) Handles the accept phase message.
* **Data Management:**
    * Uses an in-memory list (`ordersList`) sorted by transaction number.
    * Uses `loadOrderToDisk()` to append new orders to the replica-specific CSV log file (`order_log_{REPLICA_ID}.csv`).
    * `orderLogInit()`: Loads existing orders from the CSV file into `ordersList` on startup.
    * Uses various `threading.Lock` instances (`transaction_lock`, `orders_list_lock`, `order_log_lock`, `proposal_lock`) for thread-safe access to shared state (transaction counter, order list, log file, Paxos variables).
* **Replication (Part 2 - Implemented via Paxos/Replication Logic):**
    * The leader (`LEADER_ID == SELF_URL`) handles `POST /orders`.
    * After local processing (log, memory update), the leader initiates replication.
    * In the provided Paxos code, replication happens implicitly after consensus is achieved. The `replicate` function sends the committed order via `POST /replicate_order` to followers. (Note: In a pure non-Paxos leader/follower setup, the leader would just send the replication request directly after committing locally).
    * Followers handle `POST /replicate_order`, call `loadOrderToMemory` and `loadOrderToDisk` to persist the data.
* **Fault Tolerance & Recovery (Part 3 Implementation):**
    * `orderLogInit()`: Loads state from disk on startup.
    * `syncOnInit()`: Called after `orderLogInit`, triggers `appendMissingOrders` to fetch potentially missed orders from other replicas based on the highest local transaction number found.
    * `recover()`: (Background thread triggered when becoming leader)
        * Finds the maximum transaction number across all responsive replicas (by calling `/max_transaction` on others).
        * Updates its own `transactionNumber` counter to be one greater than the global maximum.
        * Calls `appendMissingOrders` to ensure its own state is fully synchronized up to the point before it took over leadership.
        * Sets `leaderRecoveryCompleted = True` upon completion.
    * `/ping` endpoint returns `recovery_done` status, preventing the Front-end from sending requests before recovery is complete.
* **Paxos Consensus (Part 4 Implementation):**
    * **Roles:** The Leader acts as the Proposer. All replicas act as Acceptors and Learners.
    * **Proposal Numbers (`pid`):** Generated using timestamp and replica ID to ensure uniqueness and rough ordering: `(int(time.time()*1000)<<16)|REPLICA_ID`.
    * **State Variables:** `promisedId`, `acceptedId`, `acceptedValue` track Paxos protocol state per replica. Protected by `proposal_lock`.
    * **Phase 1 (Prepare):**
        1.  Leader (`POST /orders`) sends `POST /paxos/prepare` with `pid` to all replicas.
        2.  Acceptors (`/paxos/prepare` endpoint): If `pid > promisedId`, update `promisedId`, respond with promise (`promise=True`) and any previously accepted value (`acceptedId`, `acceptedValue`). Otherwise, reject (`promise=False`, include current `promisedId`).
    * **Phase 2 (Accept):**
        1.  If Leader receives promises from a majority:
            * **Chooses value:** If any promise included a previously accepted value, it must choose the value associated with the highest `acceptedId` received. Otherwise, it can use its proposed order data.
            * Sends `POST /paxos/accept` with `pid` and chosen `value` to all replicas.
        2.  Acceptors (`/paxos/accept` endpoint): If `pid >= promisedId`, update `promisedId`, `acceptedId = pid`, `acceptedValue = value`, respond `accepted=True`. Otherwise, reject (`accepted=False`, include `promisedId`).
    * **Learning:**
        1.  If Leader receives accepts from a majority: The value is chosen/committed.
        2.  Leader proceeds to assign transaction number, log locally (`loadOrderToDisk`, `loadOrderToMemory`).
        3.  Leader sends the committed order to followers via `POST /replicate_order` (acting as the learn notification).
    * **Fault Tolerance:** The system requires a majority (`TOTAL_REPLICAS // 2 + 1`) for both prepare and accept phases. If one replica fails, the remaining two can still form a majority and make progress.
* **Concurrency:**
    * Uses Flask with `threaded=True`. Locks protect critical sections related to transaction numbers, order lists, file I/O, and Paxos state variables. Replication/Recovery tasks are often run in background threads (`threading.Thread`).

## 4. Data Models

* **Stock Data (Catalog & Cache):**
    ```json
    {
      "name": "StockName",
      "price": 150.0,
      "quantity": 100
    }
    ```

* **Order Data (Request/Log/Response):**
    * **`POST /orders` Request Body:**
        ```json
        {
          "stock_name": "StockName",
          "type": "buy" | "sell",
          "quantity": 20
        }
        ```
    * **Order Log / In-Memory Structure / Replication Message:**
        ```json
        {
          "transaction_number": 12345,
          "stock_name": "StockName",
          "type": "buy" | "sell",
          "quantity": 20
        }
        ```
    * **`GET /orders/<order_number>` Response Body (Success):**
        ```json
        {
          "data": {
            "number": 12345,
            "name": "StockName",
            "type": "buy",
            "quantity": 20
          }
        }
        ```
    * **Error Response Body (Generic):**
        ```json
        {
          "error": {
            "code": 404,
            "message": "Specific error message"
          }
        }
        ```

## 5. Communication Protocols

* `Client` <-> `Front-end`: Synchronous REST/HTTP.
* `Front-end` <-> `Catalog`: Synchronous REST/HTTP.
* `Front-end` <-> `Order Service` (Leader): Synchronous REST/HTTP.
* `Catalog` -> `Front-end` (Invalidation): Asynchronous REST/HTTP (Catalog sends, doesn't wait for complex processing).
* `Order Leader` -> `Order Followers` (Replication/Paxos/Sync): Asynchronous/Synchronous REST/HTTP (depends on specific call, e.g., Paxos requests are synchronous, replication post-consensus might be fire-and-forget in a background thread).

## 6. Caching Strategy (Front-end)

* **Type:** In-memory, client-side (relative to backend services).
* **Policy:** Least Recently Used (LRU).
* **Implementation:** Custom `LRUCache` class using `dict` and `deque`.
* **Consistency:** Server-push invalidation. Catalog service explicitly tells Front-end (`POST /invalidate/<stock_name>`) to remove an item after a trade updates the stock quantity.
* **Scope:** Caches responses from `GET /stocks/<stock_name>`.
* **Configuration:** Cache size set by `CACHE_SIZE` environment variable. Must be less than the total number of stocks to exercise eviction. Enabled/disabled by `CACHE_ENABLED`.

## 7. Replication Strategy (Order Service)

* **Model:** Leader-Follower (Single Leader).
* **Leader Selection:** Performed by the Front-end service. No dynamic election protocol within Order service replicas. Front-end pings replicas (highest ID first) and notifies all replicas of the chosen leader via `/set_leader`.
* **Write Path:** Front-end sends writes (`POST /orders`) only to the leader.
* **Data Propagation (with Paxos):** Consensus is reached before commit. The chosen value (order) is then logged locally by the leader and replicated to followers via `POST /replicate_order`.
* **Data Propagation (without Paxos - Conceptual):** Leader would commit locally (log, memory), then asynchronously send the order data to followers via `POST /replicate_order`.
* **Read Path:** Front-end sends reads (`GET /orders/<order_number>`) only to the leader. (Note: For read scalability, reads could potentially be served by followers in alternative designs, but this design directs them to the leader for simplicity and strong consistency).
* **Consistency:** Strong consistency for reads/writes directed to the leader. Eventual consistency for followers receiving replicated data (though the delay is typically small). Paxos ensures all replicas agree on the order of operations, leading to identical states over time assuming replication completes.

## 8. Fault Tolerance Strategy

* **Failure Detection:** Primarily handled by the Front-end service. `requests.RequestException` or non-200 HTTP status codes during communication with the Order Service leader are interpreted as potential failures. The Order Service replicas use timeouts and exception handling when communicating internally during recovery.
* **Order Service Leader Failure:** Front-end retries the request. If retries fail, it runs `findLeader()` to select a new leader (the next highest responsive ID).
* **Order Service Follower Failure:** Followers are passive receivers. Failure doesn't impede new writes (if a majority remains for Paxos). Reads are unaffected as they go to the leader. Recovery follows the replica restart process.
* **Order Service Replica Restart/Recovery:**
    1.  Load local state from `order_log_{REPLICA_ID}.csv` (`orderLogInit`).
    2.  Identify highest local transaction number (`maxTransactionNum`).
    3.  Contact other replicas (`getAllReplicas`) via `GET /get_missing_orders/{maxTransactionNum}` to fetch orders missed during downtime (`appendMissingOrders`).
    4.  Apply fetched orders to local memory (`ordersList`) and disk log (`loadOrderToDisk`).
    5.  If designated as leader (`POST /set_leader`), run the `recover` function in the background to ensure the `transactionNumber` counter is globally correct and sync any final missing orders before accepting new requests (`leaderRecoveryCompleted = True`).
* **Catalog Service Failure:** Front-end requests to Catalog will fail. Lookups will return errors. Orders requiring catalog interaction (stock check/update) will fail at the Order Service Leader. (No specific replication/failover is designed for the Catalog service in this spec).

## 9. Consensus Protocol (Paxos)

* **Purpose:** Ensure all Order Service replicas agree on the same sequence of incoming orders (writes), preventing inconsistencies due to concurrent requests potentially arriving at different replicas or being replicated out of order.
* **Implementation:** Integrated into the `POST /orders` flow on the Leader.
* **Phases:** Implements Basic Paxos Prepare and Accept phases.
* **Majority Requirement:** Requires $N/2 + 1$ (i.e., 2 out of 3) replicas to respond successfully to both Prepare and Accept phases for an order to be committed.
* **Failure Handling:** Tolerates the failure of 1 out of 3 replicas without halting progress. If the leader fails mid-Paxos, the Front-end will eventually select a new leader, which will start new Paxos rounds for subsequent requests. In-flight Paxos rounds might fail, requiring client retry.

## 10. Deployment (Docker Compose and AWS)

* The provided `docker-compose.paxos.yml` defines the services:
    * `catalog-service-paxos`: Single instance of the Catalog service.
    * `order-service-paxos-1`, `order-service-paxos-2`, `order-service-paxos-3`: Three replicas of the Order service, each configured with a unique `REPLICA_ID` and `ORDER_PORT`. Persisted data volumes map to `./src_paxos/order_service`.
    * `frontend-service-paxos`: Single instance of the Front-end service, configured with Catalog and Order service URLs.
    * `client-service-paxos`: Single instance to run the client simulation script.
* All services are connected via a bridge network `paxos-net`, allowing communication using service names.
* `depends_on` is used to control startup order loosely.
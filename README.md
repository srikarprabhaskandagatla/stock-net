<h1 align="center">
  <br>
    Stock Net: 2 Tier Stock Trading System
  <br>
</h1>

<p align="center"> 
  <a href="https://www.python.org/">
    <img src="https://img.shields.io/badge/-Python-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  </a>
  <a href="https://flask.palletsprojects.com/en/stable/">
    <img src="https://img.shields.io/badge/-Flask-white?style=flat-square&logo=flask&logoColor=000000" alt="Flask">
  </a>
  <a href="https://www.docker.com/">
    <img src="https://img.shields.io/badge/-Docker-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker">
  </a>
</p>

<p align="center">
  <a href="#what-is-stock-net?">Whhat is Stock Net?</a>
  •
  <a href="#how-does-it-work">How does it work?</a>
  •
  <a href="#execution-steps">Execution Steps</a>
  •
  <a href="#run-the-code-on-cloud">Run the Code on Cloud</a>
  •
  <a href="#contribution">Contribution</a>
</p>

# What is Stock Net?
This is a 2-Tier Toy Stock Trading System, designed with two distinct layers: a front-end tier and a back-end tier. Each tier is implemented using microservices. The front-end consists of a single microservice that handles all client interactions. The back-end is divided into two separate microservices: one for the stock catalog and another for processing stock orders. Clients connect to the front-end service to perform buy/sell operations, making this a distributed application.

# How does it work?
The system consists of a Front-end service, a Catalog service, and an Order service. The client works according to the instructions shown in [Instructions](/docs/instructions_cs677.md). The client contacts the frontend service with either a lookup or trade request (BUY/SELL). The frontend service takes care of the rest. For a lookup, it checks the cache; if the cache is missed, it contacts the catalog service. For a trade request, the frontend contacts the order service, and to update the catalog log, the order service contacts the catalog service directly.

This system is implemented using Flask with a thread-per-request model. It is available in two versions: one without the Paxos Consensus Algorithm and another with Paxos integrated. For more details, refer to the [Design Documentation (Non-Paxos)](/docs/design_documentation.md) and [Design Documentation (Paxos)](/docs/design_documentation_paxos.md).

The final outputs, such as latency plots over probability and replication workings, are given in [Evaluation Report](/docs/evaluation_report.md).

# Execution Steps
Firstly, clone this repository using the command below:
```bash
git clone https://github.com/srikarprabhaskandagatla/stock-net.git
```

### Start the Docker Container

To start a Docker container, run the following script under root folder:

Start all conatiners (Non-Paxos):
```bash
./bash.sh
```

Start all conatiners (Paxos):
```bash
./bash.sh paxos
```

This command will bring up all the microservice images (client, frontend, order (all three replicas), catalog) in Docker in the following order: `Catalog Service -> Order Service -> Frontend Service -> Client Service -> Test Service`

- Catalog Service will generate catalog_service.csv under the catalog-service folder (`src/catalog-service/ for non-Paxos, for Paxos - src_paxos/catalog-service/`), which holds the catalog data.

- Order Service will generate `order_service-1, 2, and 3` (`src/order-service/ for non-Paxos, for Paxos - src_paxos/order-service/`) under the order-service folder, which contains all the transactions made.

- Client Service will generate load_test.png (`src/client/ for non-Paxos, for Paxos - src/client/`) under the client folder, which plots lookup, order query, and trade latency.

- Test Service will generate unit and integration test log results under the `test/output` (Non-Paxos) and `test_paxos/output` (Paxos) folder, holding the output of the tests.

`client.py` contains the client logic, but it does not include any plotting functionality. Therefore, *`Client_load_test.py` is used as the client in both Non-Paxos and Paxos versions which has the plotting functionality*.

### Stop the Docker Container

To stop a Docker containers, run the following script under root folder:

Stop all conatiners (Non-Paxos):
```bash
docker-compose down
```

Stop all conatiners (Non-Paxos):
```bash
docker-compose -f docker-compose.paxos.yml down
```

# Run the Code on Cloud
The application (`Frontend Service`, `Catalog Service`, and `Order Service`) is hosted on AWS and is connected to the local client using an HTTP link. Detailed information is provided in the following [AWS Report](/docs/aws_report.md).

# Contribution
If you have any feedback, suggestions, or find a bug, feel free to open an issue or submit a pull request — your contributions are always welcome!

This project is licensed under the MIT License. For more details, see the [LICENSE](LICENSE) file.
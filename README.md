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
The system consists of a Front-end service, a Catalog service, and an Order service.

# Execution Steps
### Start the Docker Container

To start a Docker container, run the following script under root folder:

For changes without paxos:
```bash
./bash.sh
```

For changes with paxos:
```bash
./bash.sh paxos
```

This command will bring up all the micro-services images(client, frontend, order, catalog) up in the docker in the order:
Catalog Service -> Order Service -> Frontend Service -> Client Service -> Test Service

Catalog Service will generate **catalog_service.csv** under catalog-service folder, which holds the catalog data.
Order Service will generate **order_service.py** under order-service folder, which has all the transactions made.
Client Service will generate **load_test.png** graph under client folder, which plots lookup, order query and trade latency.
Test Service will generate unit and integration test log results under test/output folder, holding the output of the tests.

### Stop the Docker Container

To stop a Docker containers, run the following script under root folder:

For changes without paxos:
```bash
docker-compose down
```

For changes with paxos:
```bash
docker-compose -f docker-compose.paxos.yml down
```

# Run the Code on Cloud
The code is hosted on AWS.

# Contribution
If you have any feedback, suggestions, or find a bug, feel free to open an issue or submit a pull request — your contributions are always welcome!

This project is licensed under the MIT License. For more details, see the [LICENSE](LICENSE) file.
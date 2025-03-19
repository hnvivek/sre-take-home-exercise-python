import yaml
import argparse
import os
import time
import asyncio
import aiohttp
import logging
from logging.handlers import TimedRotatingFileHandler
from urllib.parse import urlparse
from prometheus_client import Counter, Gauge, Summary, start_http_server
from collections import defaultdict

logger = logging.getLogger(__name__)
# Set up logger with daily rotation
handler = TimedRotatingFileHandler(
    filename="logs/monitor_endpoints.log",
    when="H",
    interval=1,  # Rotate every hour
    backupCount=24,  # Keep logs for a day
    encoding="utf-8"
)
logger.addHandler(handler)

# Define simple Prometheus metrics
# 1. Endpoint up/down status (1 = up, 0 = down)
STATUS = Gauge('endpoint_status', 'Status of endpoint (1=UP, 0=DOWN)', ['endpoint'])

# 2. Response time
RESPONSE_TIME = Summary('endpoint_response_time_seconds', 'Response time in seconds', ['endpoint'])

# 3. Status code counter
STATUS_CODES = Counter('endpoint_status_codes_total', 'Count of HTTP status codes', ['endpoint', 'code'])

# global domain_stats
domain_stats = defaultdict(lambda: {"up": 0, "total": 0})


class EndpointConfig:
    def __init__(self, name, url, method="GET", headers=None, body=None, file_path=None):
        self.name = name
        self.url = url
        self.method = method.upper()
        self.headers = headers or {}
        self.body = body
        self.file_path = file_path
        self.domain = self.get_domain(url)
        self.stats = {"up": 0, "total": 0}

    def __repr__(self):
        return f"EndpointConfig(name={self.name}, url={self.url}, method={self.method})"

    # Function to parse domain from url
    @staticmethod
    def get_domain(url):
        parsed_url = urlparse(url)
        return parsed_url.netloc.split(":")[0]  # ignore port number

    def update_stats(self, result):
        """Update stats based on the health check result."""
        self.stats["total"] += 1
        if result == "UP":
            self.stats["up"] += 1

    def availability_percentage(self):
        """Calculate availability percentage."""
        if self.stats["total"] > 0:
            return round(100 * self.stats["up"] / self.stats["total"])
        return 0


class ConfigLoader:
    def __init__(self, path):
        self.path = path
        self.endpoints = {}
        self.file_endpoints = {}  # Track which endpoints come from which files
        self.mod_times = {}  # Track file modification times
        self.load_configs()

    def load_configs(self):
        """Load configuration from the specified path (file or directory)."""
        # Keep track of current files
        current_files = set()

        if os.path.isdir(self.path):
            for file_name in os.listdir(self.path):
                if file_name.endswith(".yaml"):
                    file_path = os.path.join(self.path, file_name)
                    current_files.add(file_path)
                    self._load_file(file_path)
        elif os.path.isfile(self.path) and self.path.endswith(".yaml"):
            current_files.add(self.path)
            self._load_file(self.path)

        # Remove endpoints from files that no longer exist
        for file_path in list(self.file_endpoints.keys()):
            if file_path not in current_files:
                self._remove_file_endpoints(file_path)

    def _load_file(self, file_path):
        """Load a single YAML file and update configurations."""
        try:
            # Check if the file has been modified
            current_mod_time = os.path.getmtime(file_path)
            if file_path in self.mod_times and current_mod_time == self.mod_times[file_path]:
                # File hasn't changed, no need to reload
                return

            with open(file_path, "r") as file:
                config_data = yaml.safe_load(file)

                # Get endpoints from this file
                current_file_endpoints = set()
                for ep in config_data:
                    name = ep.get("name")
                    self.endpoints[name] = EndpointConfig(**{**ep, "file_path": file_path})
                    current_file_endpoints.add(name)

                # Remove endpoints that were in this file but are no longer present
                if file_path in self.file_endpoints:
                    removed_endpoints = self.file_endpoints[file_path] - current_file_endpoints
                    for name in removed_endpoints:
                        if name in self.endpoints:
                            logger.debug(f"Removing endpoint: {name}")
                            del self.endpoints[name]

                # Update the tracking of which endpoints belong to this file
                self.file_endpoints[file_path] = current_file_endpoints

                # Update modification time
                self.mod_times[file_path] = current_mod_time
                logger.debug(f"Updated file {file_path} with mod time {current_mod_time}")

        except (FileNotFoundError, yaml.YAMLError) as e:
            logger.error(f"Error loading {file_path}: {e}")
            # If file doesn't exist, remove any endpoints it previously defined
            if file_path in self.file_endpoints:
                self._remove_file_endpoints(file_path)

    def _remove_file_endpoints(self, file_path):
        """Remove all endpoints that were defined in the specified file."""
        if file_path not in self.file_endpoints:
            return

        logger.info(f"Removing endpoints from deleted file: {file_path}")
        for name in self.file_endpoints[file_path]:
            if name in self.endpoints:
                logger.debug(f"Removing endpoint: {name}")
                del self.endpoints[name]

        # Remove the file from tracking
        del self.file_endpoints[file_path]
        if file_path in self.mod_times:
            del self.mod_times[file_path]

    def refresh(self):
        """Check for configuration changes including deleted files and modifications."""
        current_files = set()

        if os.path.isdir(self.path):
            # If it"s a directory, check all YAML files in it
            for file_name in os.listdir(self.path):
                if file_name.endswith(".yaml"):
                    file_path = os.path.join(self.path, file_name)
                    current_files.add(file_path)

                    if os.path.exists(file_path):
                        current_mod_time = os.path.getmtime(file_path)
                        # Only reload if the file has been modified
                        if file_path not in self.mod_times or current_mod_time != self.mod_times[file_path]:
                            logger.info(f"Detected changes in {file_path}, reloading...")
                            self._load_file(file_path)

        elif os.path.isfile(self.path) and self.path.endswith(".yaml"):
            # If it's a single YAML file, check its modification time
            file_path = self.path
            current_files.add(file_path)

            if os.path.exists(file_path):
                current_mod_time = os.path.getmtime(file_path)
                if file_path not in self.mod_times or current_mod_time != self.mod_times[file_path]:
                    logger.info(f"Detected changes in {file_path}, reloading...")
                    self._load_file(file_path)

        # Check for deleted files and remove their endpoints
        for file_path in list(self.file_endpoints.keys()):
            if file_path not in current_files or not os.path.exists(file_path):
                logger.info(f"Config file deleted: {file_path}")
                self._remove_file_endpoints(file_path)


async def check_health(session, endpoint, response_time_threshold=0.5):
    try:
        start_time = time.monotonic()  # Start the timer

        async with session.get(endpoint.url, timeout=1) as response:
            elapsed_time = time.monotonic() - start_time  # Calculate elapsed time

            # Record response time
            RESPONSE_TIME.labels(endpoint=endpoint.name).observe(elapsed_time)

            # Count the status code
            STATUS_CODES.labels(endpoint=endpoint.name, code=str(response.status)).inc()

            if 200 <= response.status < 300 and elapsed_time < response_time_threshold:
                STATUS.labels(endpoint=endpoint.name).set(1)
                logger.debug(
                    f"Endpoint {endpoint.url} is UP (Status: {response.status}, Response Time: {elapsed_time:.2f}s)")
                return "UP"
            else:
                STATUS.labels(endpoint=endpoint.name).set(0)
                logger.debug(
                    f"Endpoint {endpoint.url} is DOWN (Status: {response.status}, Response Time: {elapsed_time:.2f}s)")
                return "DOWN"
    except Exception as e:
        # Record error
        STATUS.labels(endpoint=endpoint.name).set(0)
        STATUS_CODES.labels(endpoint=endpoint.name, code="error").inc()
        logger.error(f"Error checking {endpoint.url}: {e}")
        return "DOWN"


# dynamic clean up of domains
def clean_domains(endpoints):
    # Set of active domains
    active_domains = set(endpoint.domain for endpoint in endpoints)

    # Then clean up domain_stats to only include active domains
    domains_to_remove = [domain for domain in domain_stats if domain not in active_domains]
    for domain in domains_to_remove:
        logger.debug(f"Removing domain {domain} from domain_stats")
        del domain_stats[domain]


# Main function to monitor endpoints
async def monitor_endpoints(file_path, interval):
    config_loader = ConfigLoader(file_path)

    while True:
        config_loader.refresh()
        endpoints = config_loader.endpoints.values()

        if not endpoints:  # Check if there are no endpoints
            logger.warning("No endpoints available. Exiting monitoring loop.")
            break  # Exit the loop

        clean_domains(endpoints)

        async with aiohttp.ClientSession() as session:
            tasks = [check_health(session, endpoint) for endpoint in endpoints]
            results = await asyncio.gather(*tasks)

            for endpoint, result in zip(endpoints, results):
                endpoint.update_stats(result)

                domain_stats[endpoint.domain]["total"] += 1
                if result == "UP":
                    domain_stats[endpoint.domain]["up"] += 1

        # Log cumulative availability percentages
        for domain, stats in domain_stats.items():
            availability = round(100 * stats["up"] / stats["total"])
            logger.debug(f"{domain}: UP: {stats["up"]}, Total: {stats["total"]}")
            logger.info(f"{domain} has {availability}% availability percentage")

        logger.info("---")
        await asyncio.sleep(interval)


def start_metrics_server(port=8000):
    """Start the Prometheus metrics HTTP server"""
    start_http_server(port)
    logger.info(f"Prometheus metrics available at http://localhost:{port}/metrics")


async def main():
    parser = argparse.ArgumentParser(description="Monitor endpoint health")
    parser.add_argument(
        "config_path",
        help="Path to configuration file or directory containing YAML configurations"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=15,
        help="Check interval in seconds (default: 15)"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO)"
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    try:
        # Start the metrics server
        start_metrics_server()
        # Run the monitor
        await monitor_endpoints(args.config_path, args.interval)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Monitoring stopped by user.")


# Entry point of the program
if __name__ == "__main__":
    asyncio.run(main())

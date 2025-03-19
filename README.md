# Endpoint Health Monitoring Service

This repository contains a health monitoring service built in Python that tracks endpoint availability and provides timely insights about service health.

## Features

- Monitors multiple endpoints defined in YAML configuration files
- Calculates and logs availability percentage by domain
- Provides Prometheus metrics for monitoring and alerting
- Supports hot reloading of configuration changes without the need for reboot
- Logs results with hourly rotation
- Highly configurable through command-line arguments

## Requirements

- Python 3.7+
- Dependencies listed in `requirements.txt`

## Installation

1. Clone this repository
   ```
   git clone https://github.com/hnvivek/sre-take-home-exercise-python.git
   cd sre-take-home-exercise-python
   ```

2. Install required dependencies
   ```
   pip3 install -r requirements.txt
   ```

## Usage

Run the monitoring service by providing a YAML configuration file or directory:

```
python3 main.py /path/to/config.yaml --interval 15 --log-level INFO
```

To verify at the individual endpoint level, set the logging level to DEBUG. This will provide statistics for each endpoint.

```
python3 main.py configs --interval 15 --log-level DEBUG
```
### Sample output
```commandline
logs
2025-03-18 22:05:08,501 - __main__ - DEBUG - Endpoint https://fetch.com/careers is UP (Status: 200, Response Time: 0.24s)
2025-03-18 22:05:08,503 - __main__ - DEBUG - Endpoint https://fetch.com/ is UP (Status: 200, Response Time: 0.24s)
2025-03-18 22:05:08,550 - __main__ - DEBUG - Endpoint https://fetch.com/some/post/endpoint is DOWN (Status: 404, Response Time: 0.29s)
2025-03-18 22:05:08,813 - __main__ - DEBUG - Endpoint https://www.fetchrewards.com/ is DOWN (Status: 200, Response Time: 0.55s)
2025-03-18 22:05:08,814 - __main__ - DEBUG - fetch.com: UP: 6, Total: 9
2025-03-18 22:05:08,814 - __main__ - INFO - fetch.com has 67% availability percentage
2025-03-18 22:05:08,814 - __main__ - DEBUG - www.fetchrewards.com: UP: 1, Total: 3
2025-03-18 22:05:08,814 - __main__ - INFO - www.fetchrewards.com has 33% availability percentage

```
### Command-line Arguments

- `config_path` (required): Path to YAML configuration file or directory containing YAML files (extracts all files in directory)
- `--interval` (optional): Check interval in seconds (default: 15)
- `--log-level` (optional): Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL; default: INFO)

### YAML Configuration Format

The YAML configuration must follow this format:

```yaml
- headers:
    user-agent: fetch-synthetic-monitor
  method: GET
  name: fetch index page
  url: https://fetch.com/

- headers:
    user-agent: fetch-synthetic-monitor
  method: GET
  name: fetch careers page
  url: https://fetch.com/careers

- body: '{"foo":"bar"}'
  headers:
    content-type: application/json
    user-agent: fetch-synthetic-monitor
  method: POST
  name: fetch some fake post endpoint
  url: https://fetch.com/some/post/endpoint

- name: fetch rewards index page
  url: https://www.fetchrewards.com/

```

## Metrics

The service exposes Prometheus metrics on http://localhost:8000/metrics, including:

- `endpoint_status`: Status of endpoint (1=UP, 0=DOWN)
- `endpoint_response_time_seconds`: Response time in seconds
- `endpoint_status_codes_total`: Count of HTTP status codes

## Availability Calculation

An endpoint is considered available if it meets both conditions:
- Returns a status code between 200-299
- Responds in less than 500ms

Availability is calculated cumulatively by domain (ignoring port numbers) and logged every 15 seconds.

## Issues Identified and Changes Made

After reviewing the original code, I found several issues that needed fixing:

### Key Issues Fixed:

1. **Missing Default Handling**: Original code didn't provide defaults for headers, body, and methods. Added proper defaults to handle missing config values.

2. **Missing Response Time Check**: Original code only checked status codes but didn't consider response time. Added a 500ms threshold to mark slow endpoints as DOWN.

3. **Poor Domain Extraction**: String splitting for domain extraction was used and didn't work with URLs containing port numbers. Switched to urlparse to properly extract domains while ignoring ports.

4. **Better Code Organization**: Restructured code into classes (EndpointConfig, ConfigLoader) for better organization and maintainability.

5. **Synchronous Requests**: The original code used synchronous requests which would hang when monitoring many endpoints. I switched to `aiohttp` to make concurrent requests and avoid this bottleneck.

6. **Limited Error Handling**: Original code had minimal exception handling so, I have improved error catching 

7. **Fixed Domain Stats**: Domain stats calculation had issues with how availability was tracked. Improved to ensure accurate cumulative calculations.


### Additional Enhancements:

1. **Improved CLI Arguments**: Added command-line options for interval and log level to make the tool more configurable.

2. **Directory-based Configs**: Added support for loading multiple YAML files from a directory instead of just a single file.

3. **Hot Reload**: Any config change required stopping and restarting the service. I implemented hot reloading to detect file changes so the service picks up new or modified endpoints automatically.

4. **Structured Logging**: Replaced print statements with proper logging including timestamps and levels. Added log rotation for easier management.

5. **Prometheus Metrics**: Added metrics endpoint exposing status, response times, and status codes for better observability.

## Known Limitations and Future Improvements

- Implement tests for better code quality assurance.
- Develop monitoring dashboards with Grafana to enhance tracking capabilities and enable real-time alerts.
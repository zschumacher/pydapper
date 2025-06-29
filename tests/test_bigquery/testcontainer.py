import requests
from testcontainers.core.generic import DockerContainer
from testcontainers.core.waiting_utils import wait_container_is_ready
from urllib3.exceptions import ConnectionError


class BigQueryEmulatorContainer(DockerContainer):
    def __init__(
        self,
        image: str = "ghcr.io/goccy/bigquery-emulator:latest",
        project: str = "default",
        dataset: str = "default",
        **kwargs,
    ):
        super().__init__(image, **kwargs)
        self.with_command(f"--project={project} --dataset={dataset}")
        self.port = 9050
        self.with_exposed_ports(9050)

    @wait_container_is_ready()
    def _connect(self):
        port = self.get_exposed_port(9050)
        url = f"http://localhost:{port}/projects"
        try:
            response = requests.get(url)
            if response.status_code != 200:
                raise RuntimeError(f"BigQuery emulator returned status code {response.status_code}")
            return True
        except (ConnectionError, requests.exceptions.ConnectionError):
            return False

    def start(self):
        super().start()
        self._connect()
        return self

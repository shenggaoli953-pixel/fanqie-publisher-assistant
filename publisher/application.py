from collections.abc import Callable
from pathlib import Path

from publisher.accounts import AccountProfile, AccountRegistry
from publisher.browser import EdgePublisherGateway
from publisher.repository import JsonRepository
from publisher.service import PublishingService


class ApplicationContext:
    def __init__(self, data_dir: Path) -> None:
        self.accounts = AccountRegistry(data_dir)

    def active_profile(self) -> AccountProfile:
        return self.accounts.active()

    def switch(self, profile_id: str) -> AccountProfile:
        return self.accounts.set_active(profile_id)

    def service(self) -> PublishingService:
        return PublishingService(
            JsonRepository(self.accounts.workspace_dir(self.active_profile().profile_id))
        )

    def gateway_factory(self) -> Callable[[], EdgePublisherGateway]:
        profile_dir = self.accounts.edge_profile_dir(self.active_profile().profile_id)
        return lambda: EdgePublisherGateway(profile_dir)

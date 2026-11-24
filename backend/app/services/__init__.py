"""领域服务注册表：通用资源路由按模块 key 分派到独立业务服务。"""
from __future__ import annotations

from app.services.base import BaseModuleService
from app.services.crawler_config import CrawlerConfigService
from app.services.parser_rule import ParserRuleService
from app.services.proxy_pool import ProxyPoolService
from app.services.cookie_mgr import CookieMgrService
from app.services.rate_limiter import RateLimiterService
from app.services.extraction_template import ExtractionTemplateService
from app.services.data_validator import DataValidatorService
from app.services.crawl_schedule import CrawlScheduleService
from app.services.result_store import ResultStoreService
from app.services.dedup_engine import DedupEngineService
from app.services.field_mapper import FieldMapperService
from app.services.error_retry import ErrorRetryService
from app.services.batch_tracker import BatchTrackerService
from app.services.export_channel import ExportChannelService
from app.services.crawl_audit import CrawlAuditService
from app.services.source_auth import SourceAuthService
from app.services.html_cleaner import HtmlCleanerService
from app.services.incremental_sync import IncrementalSyncService
from app.services.error_logger import ErrorLoggerService
from app.services.session_manager import SessionManagerService
from app.services.data_cleanup import DataCleanupService
from app.services.collection_plan import CollectionPlanService
from app.services.source_license import SourceLicenseService
from app.services.claim_record import ClaimRecordService, SessionAttributionService

# 同表别名服务：允许不同命名的模块 key 访问同一份领域数据
class CrawlPlanService(CollectionPlanService):
    MODULE = "collection_plan"


class LicenseAliasService(SourceLicenseService):
    MODULE = "source_license"


SERVICES: dict[str, BaseModuleService] = {
    "crawler_config": CrawlerConfigService(),
    "parser_rule": ParserRuleService(),
    "proxy_pool": ProxyPoolService(),
    "cookie_mgr": CookieMgrService(),
    "rate_limiter": RateLimiterService(),
    "extraction_template": ExtractionTemplateService(),
    "data_validator": DataValidatorService(),
    "crawl_schedule": CrawlScheduleService(),
    "result_store": ResultStoreService(),
    "dedup_engine": DedupEngineService(),
    "field_mapper": FieldMapperService(),
    "error_retry": ErrorRetryService(),
    "batch_tracker": BatchTrackerService(),
    "export_channel": ExportChannelService(),
    "crawl_audit": CrawlAuditService(),
    "source_auth": SourceAuthService(),
    "html_cleaner": HtmlCleanerService(),
    "incremental_sync": IncrementalSyncService(),
    "error_logger": ErrorLoggerService(),
    "session_manager": SessionManagerService(),
    "data_cleanup": DataCleanupService(),
    # 采集会话归属能力新增的领域数据
    "collection_plan": CollectionPlanService(),
    "crawl_plan": CrawlPlanService(),
    "source_license": SourceLicenseService(),
    "license": LicenseAliasService(),
    "claim_record": ClaimRecordService(),
    "session_attribution": SessionAttributionService(),
}


def service_for(module: str) -> BaseModuleService | None:
    return SERVICES.get(module)

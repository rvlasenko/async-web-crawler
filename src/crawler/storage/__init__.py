from crawler.storage.base import DataStorage
from crawler.storage.csv_storage import CSVStorage
from crawler.storage.json_storage import JSONStorage
from crawler.storage.postgres_storage import PostgreSQLStorage

__all__ = ["DataStorage", "CSVStorage", "JSONStorage", "PostgreSQLStorage"]

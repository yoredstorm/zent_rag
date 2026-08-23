# =============================================================================
# Plugins — files (fixtures reales), postgres (dev), SQL opcionales (mocks)
# =============================================================================
from __future__ import annotations

import csv
import json

import pytest

from src.connectors.plugin.plugins.api_plugins import GraphqlPlugin, RestApiPlugin
from src.connectors.plugin.plugins.files import CsvPlugin, ExcelPlugin, JsonFilePlugin, PdfPlugin
from src.connectors.plugin.plugins.s3_compat import S3CompatPlugin
from src.connectors.plugin.plugins.sql_optional import MysqlPlugin


@pytest.fixture
def files_dir(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from src.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    return tmp_path


class TestCsvPlugin:
    @pytest.mark.asyncio
    async def test_discover_infers_types(self, files_dir) -> None:
        path = files_dir / "products.csv"
        with open(path, "w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["name", "price", "active"])
            writer.writerow(["Paracetamol", "1990", "true"])
            writer.writerow(["Ibuprofeno", "2500", "false"])

        plugin = CsvPlugin({"object_key": "products.csv"}, {})
        result = await plugin.test_connection()
        assert result.ok is True

        discovery = await plugin.discover()
        cols = {c.name: c.data_type for c in discovery.tables[0].columns}
        assert cols["name"] == "text"
        assert cols["price"] == "integer"
        assert cols["active"] == "boolean"

    @pytest.mark.asyncio
    async def test_missing_file_error(self, files_dir) -> None:
        plugin = CsvPlugin({"object_key": "nope.csv"}, {})
        result = await plugin.test_connection()
        assert result.ok is False
        assert "not found" in result.message


class TestExcelPlugin:
    @pytest.mark.asyncio
    async def test_discover_sheets(self, files_dir) -> None:
        from openpyxl import Workbook

        path = files_dir / "catalog.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "Productos"
        ws.append(["name", "price"])
        ws.append(["Paracetamol", 1990])
        wb.save(path)

        plugin = ExcelPlugin({"object_key": "catalog.xlsx"}, {})
        result = await plugin.test_connection()
        assert result.ok is True
        discovery = await plugin.discover()
        assert discovery.tables[0].name == "Productos"


class TestJsonFilePlugin:
    @pytest.mark.asyncio
    async def test_discover_keys(self, files_dir) -> None:
        path = files_dir / "data.json"
        path.write_text(
            json.dumps(
                [
                    {"id": 1, "name": "a"},
                    {"id": 2, "name": "b", "extra": True},
                ]
            ),
            encoding="utf-8",
        )
        plugin = JsonFilePlugin({"object_key": "data.json"}, {})
        assert (await plugin.test_connection()).ok is True
        discovery = await plugin.discover()
        cols = {c.name: c.data_type for c in discovery.tables[0].columns}
        assert cols["id"] == "int"
        assert cols["name"] == "str"
        assert "extra" in cols

    @pytest.mark.asyncio
    async def test_invalid_json(self, files_dir) -> None:
        (files_dir / "bad.json").write_text("{not json", encoding="utf-8")
        plugin = JsonFilePlugin({"object_key": "bad.json"}, {})
        result = await plugin.test_connection()
        assert result.ok is False


class TestPdfPlugin:
    @pytest.mark.asyncio
    async def test_valid_pdf_magic(self, files_dir) -> None:
        (files_dir / "doc.pdf").write_bytes(b"%PDF-1.7 fake content")
        plugin = PdfPlugin({"object_key": "doc.pdf"}, {})
        assert (await plugin.test_connection()).ok is True

    @pytest.mark.asyncio
    async def test_invalid_pdf_rejected(self, files_dir) -> None:
        (files_dir / "doc.pdf").write_bytes(b"not a pdf")
        plugin = PdfPlugin({"object_key": "doc.pdf"}, {})
        result = await plugin.test_connection()
        assert result.ok is False
        assert "PDF" in result.message


class TestApiPlugins:
    @pytest.mark.asyncio
    async def test_rest_requires_base_url(self) -> None:
        plugin = RestApiPlugin({}, {})
        result = await plugin.test_connection()
        assert result.ok is False

    @pytest.mark.asyncio
    async def test_graphql_requires_url(self) -> None:
        plugin = GraphqlPlugin({}, {})
        result = await plugin.test_connection()
        assert result.ok is False

    @pytest.mark.asyncio
    async def test_rest_blocks_private_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plugin = RestApiPlugin({"base_url": "http://10.0.0.9/x"}, {})
        result = await plugin.test_connection()
        assert result.ok is False
        assert "Blocked" in result.message


class TestSqlOptional:
    @pytest.mark.asyncio
    async def test_mysql_missing_driver_clear_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "CONNECTOR_SSRF_BLOCK_PRIVATE", False)
        plugin = MysqlPlugin(
            {"host": "db.example.com", "user": "u", "database": "d"},
            {"password": "p"},
        )
        result = await plugin.test_connection()
        # Sin driver instalado en CI: error claro, nunca crash.
        assert result.ok is False
        assert "driver not installed" in result.message


class TestS3Plugin:
    @pytest.mark.asyncio
    async def test_requires_credentials(self) -> None:
        plugin = S3CompatPlugin({"bucket": "b"}, {})
        result = await plugin.test_connection()
        assert result.ok is False
        assert "aws_access_key_id" in result.message

    @pytest.mark.asyncio
    async def test_blocks_private_endpoint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plugin = S3CompatPlugin(
            {"bucket": "b", "endpoint_url": "http://10.0.0.8:9000"},
            {
                "aws_access_key_id": "k",
                "aws_secret_access_key": "s",
            },
        )
        result = await plugin.test_connection()
        assert result.ok is False
        assert "Blocked" in result.message

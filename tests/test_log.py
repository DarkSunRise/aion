"""Tests for structured logging configuration."""

import logging

import structlog

from aion.log import configure_logging


class TestConfigureLogging:
    def test_console_mode(self):
        """configure_logging in console mode doesn't crash."""
        configure_logging(json_output=False, level="DEBUG")
        logger = structlog.get_logger("test.console")
        logger.info("test message", key="value")

    def test_json_mode(self):
        """configure_logging in JSON mode doesn't crash."""
        configure_logging(json_output=True, level="INFO")
        logger = structlog.get_logger("test.json")
        logger.info("test message", key="value")

    def test_stdlib_loggers_still_work(self):
        """stdlib loggers (used in memory/) are formatted by structlog."""
        configure_logging(json_output=False, level="DEBUG")
        stdlib_logger = logging.getLogger("test.stdlib")
        stdlib_logger.info("stdlib message")

    def test_all_levels(self):
        """All log levels work without error."""
        configure_logging(json_output=False, level="DEBUG")
        logger = structlog.get_logger("test.levels")
        logger.debug("debug")
        logger.info("info")
        logger.warning("warning")
        logger.error("error")

    def test_level_setting(self):
        """Level string is applied to root logger."""
        configure_logging(json_output=False, level="ERROR")
        root = logging.getLogger()
        assert root.level == logging.ERROR

        configure_logging(json_output=False, level="DEBUG")
        assert root.level == logging.DEBUG

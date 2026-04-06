"""Tests for agent_harness.log."""

import logging
import os
import tempfile

from agent_harness.log import setup_logging


class TestSetupLogging:
    def test_default_console_level_is_info(self) -> None:
        setup_logging()
        root = logging.getLogger("agent_harness")
        assert root.level <= logging.INFO

    def test_verbose_sets_debug(self) -> None:
        setup_logging(verbose=True)
        root = logging.getLogger("agent_harness")
        assert root.level == logging.DEBUG

    def test_file_handler_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            setup_logging(agent_dir=tmpdir)
            log_dir = os.path.join(tmpdir, "logs")
            assert os.path.isdir(log_dir)

            # Emit a log and check file exists
            logger = logging.getLogger("agent_harness.test")
            logger.info("test message")

            log_files = os.listdir(log_dir)
            assert len(log_files) == 1
            assert log_files[0].endswith(".log")

    def test_log_format_contains_expected_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            setup_logging(agent_dir=tmpdir, verbose=True)
            logger = logging.getLogger("agent_harness.test_format")
            logger.info("check format")

            log_dir = os.path.join(tmpdir, "logs")
            log_files = os.listdir(log_dir)
            with open(os.path.join(log_dir, log_files[0])) as f:
                content = f.read()
            assert "INFO" in content
            assert "check format" in content

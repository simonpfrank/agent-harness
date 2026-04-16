"""Tests for tools/profile_data.py custom tool."""

import json
import os
import tempfile

import pytest


class TestProfileDataCSV:
    def test_profiles_all_columns(self) -> None:
        from tools.profile_data import profile_data

        csv = "name,age,joined\nAlice,30,2024-01-15\nBob,25,2023-06-01\nCharlie,35,2022-11-20\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv)
            f.flush()
            result = json.loads(profile_data(f.name))
        os.unlink(f.name)

        assert result["total_rows"] == 3
        assert result["total_columns"] == 3
        assert len(result["columns"]) == 3

    def test_column_metadata_fields(self) -> None:
        from tools.profile_data import profile_data

        csv = "id,value\n1,hello\n2,world\n3,test\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv)
            f.flush()
            result = json.loads(profile_data(f.name))
        os.unlink(f.name)

        col = result["columns"][0]
        expected_keys = {
            "name", "data_type", "population_rate",
            "unique_percent", "pattern", "sample_values", "characteristics",
        }
        assert expected_keys == set(col.keys())

    def test_numeric_detection(self) -> None:
        from tools.profile_data import profile_data

        csv = "amount\n100.50\n200.75\n300.00\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv)
            f.flush()
            result = json.loads(profile_data(f.name))
        os.unlink(f.name)

        col = result["columns"][0]
        assert col["data_type"] == "numeric"

    @pytest.mark.skip(reason="stats field commented out for lean profile testing")
    def test_numeric_stats(self) -> None:
        from tools.profile_data import profile_data

        csv = "amount\n100.50\n200.75\n300.00\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv)
            f.flush()
            result = json.loads(profile_data(f.name))
        os.unlink(f.name)

        col = result["columns"][0]
        assert col["stats"]["min"] == 100.5
        assert col["stats"]["max"] == 300.0
        assert col["stats"]["mean"] == 200.42

    @pytest.mark.skip(reason="stats field commented out for lean profile testing")
    def test_numeric_stats_not_on_text(self) -> None:
        from tools.profile_data import profile_data

        csv = "name\nAlice\nBob\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv)
            f.flush()
            result = json.loads(profile_data(f.name))
        os.unlink(f.name)

        col = result["columns"][0]
        assert col["stats"] is None

    @pytest.mark.skip(reason="unique_count field commented out for lean profile testing")
    def test_unique_count(self) -> None:
        from tools.profile_data import profile_data

        csv = "colour\nred\nred\nblue\ngreen\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv)
            f.flush()
            result = json.loads(profile_data(f.name))
        os.unlink(f.name)

        col = result["columns"][0]
        assert col["unique_count"] == 3

    def test_date_detection(self) -> None:
        from tools.profile_data import profile_data

        csv = "event_date\n2024-01-15\n2024-02-20\n2024-03-25\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv)
            f.flush()
            result = json.loads(profile_data(f.name))
        os.unlink(f.name)

        col = result["columns"][0]
        assert col["data_type"] == "date"
        assert "YYYY-MM-DD" in col["pattern"]

    def test_text_detection(self) -> None:
        from tools.profile_data import profile_data

        csv = "city\nLondon\nParis\nBerlin\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv)
            f.flush()
            result = json.loads(profile_data(f.name))
        os.unlink(f.name)

        col = result["columns"][0]
        assert col["data_type"] == "text"

    def test_population_rate(self) -> None:
        from tools.profile_data import profile_data

        csv = "name,val\nAlice,hello\nBob,\nCharlie,world\nDave,\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv)
            f.flush()
            result = json.loads(profile_data(f.name))
        os.unlink(f.name)

        val_col = result["columns"][1]
        assert val_col["population_rate"] == 0.5

    def test_unique_percent(self) -> None:
        from tools.profile_data import profile_data

        csv = "colour\nred\nred\nblue\ngreen\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv)
            f.flush()
            result = json.loads(profile_data(f.name))
        os.unlink(f.name)

        col = result["columns"][0]
        assert col["unique_percent"] == 75.0  # 3 unique out of 4

    def test_sample_values_limited(self) -> None:
        from tools.profile_data import profile_data

        rows = "\n".join(f"v{i}" for i in range(20))
        csv = f"item\n{rows}\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv)
            f.flush()
            result = json.loads(profile_data(f.name))
        os.unlink(f.name)

        col = result["columns"][0]
        assert len(col["sample_values"]) <= 5

    def test_characteristics_all_unique(self) -> None:
        from tools.profile_data import profile_data

        csv = "id\n1\n2\n3\n4\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv)
            f.flush()
            result = json.loads(profile_data(f.name))
        os.unlink(f.name)

        col = result["columns"][0]
        assert "all_unique" in col["characteristics"]

    def test_characteristics_sparse(self) -> None:
        from tools.profile_data import profile_data

        csv = "id,val\n1,hello\n2,\n3,\n4,\n5,\n6,\n7,\n8,\n9,\n10,\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv)
            f.flush()
            result = json.loads(profile_data(f.name))
        os.unlink(f.name)

        val_col = result["columns"][1]
        assert "sparse" in val_col["characteristics"]

    def test_max_sample_rows(self) -> None:
        from tools.profile_data import profile_data

        rows = "\n".join(str(i) for i in range(500))
        csv = f"num\n{rows}\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv)
            f.flush()
            result = json.loads(profile_data(f.name, max_sample_rows=10))
        os.unlink(f.name)

        # Should still work — profiling is on sampled rows
        assert result["total_rows"] <= 10


class TestRemoveColumns:
    def test_removes_named_columns(self) -> None:
        from tools.profile_data import profile_data

        csv = "id,name,status,junk\n1,Alice,active,x\n2,Bob,inactive,y\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv)
            f.flush()
            result = json.loads(profile_data(f.name, remove_columns="status,junk"))
        os.unlink(f.name)

        col_names = [c["name"] for c in result["columns"]]
        assert col_names == ["id", "name"]
        assert result["total_columns"] == 2

    def test_remove_columns_case_insensitive(self) -> None:
        from tools.profile_data import profile_data

        csv = "Name,Age\nAlice,30\nBob,25\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv)
            f.flush()
            result = json.loads(profile_data(f.name, remove_columns="name"))
        os.unlink(f.name)

        col_names = [c["name"] for c in result["columns"]]
        assert col_names == ["Age"]

    def test_remove_columns_empty_string_ignored(self) -> None:
        from tools.profile_data import profile_data

        csv = "a,b\n1,2\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv)
            f.flush()
            result = json.loads(profile_data(f.name, remove_columns=""))
        os.unlink(f.name)

        assert result["total_columns"] == 2


class TestProfileDataEncoding:
    def test_latin1_encoding(self) -> None:
        from tools.profile_data import profile_data

        with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as f:
            f.write("name\nCaf\xe9\nR\xe9sum\xe9\n".encode("latin-1"))
            f.flush()
            result = json.loads(profile_data(f.name))
        os.unlink(f.name)

        col = result["columns"][0]
        assert any("Caf" in v for v in col["sample_values"])


class TestProfileDataExcel:
    def test_xlsx_file(self) -> None:
        from tools.profile_data import profile_data

        pandas = pytest.importorskip("pandas")
        openpyxl = pytest.importorskip("openpyxl")
        import pandas as pd

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            df = pd.DataFrame({"name": ["Alice", "Bob"], "age": ["30", "25"]})
            df.to_excel(f.name, index=False)
            result = json.loads(profile_data(f.name))
        os.unlink(f.name)

        assert result["total_columns"] == 2
        assert result["total_rows"] == 2


class TestProfileDataEdgeCases:
    def test_missing_file_raises(self) -> None:
        from tools.profile_data import profile_data

        with pytest.raises(FileNotFoundError):
            profile_data("/no/such/file.csv")

    def test_unsupported_extension(self) -> None:
        from tools.profile_data import profile_data

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"hello")
            f.flush()
            with pytest.raises(ValueError, match="Unsupported"):
                profile_data(f.name)
        os.unlink(f.name)

    def test_empty_csv(self) -> None:
        from tools.profile_data import profile_data

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("col_a,col_b\n")
            f.flush()
            result = json.loads(profile_data(f.name))
        os.unlink(f.name)

        assert result["total_rows"] == 0
        assert result["total_columns"] == 2

    def test_returns_valid_json(self) -> None:
        from tools.profile_data import profile_data

        csv = "x\n1\n2\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv)
            f.flush()
            raw = profile_data(f.name)
        os.unlink(f.name)

        # Must be valid JSON string
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)


class TestProfileDataDiscovery:
    def test_discovered_by_registry(self) -> None:
        from agent_harness.tools import discover_tools, registry

        discover_tools("tools")
        assert "profile_data" in registry
